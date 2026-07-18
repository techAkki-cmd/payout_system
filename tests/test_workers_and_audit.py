from collections.abc import Generator
from decimal import Decimal
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.audit import validate_user_wallet_integrity
from app.models import Base, Sale, Transaction, TransactionStatus, TransactionType, User
from app.services.recovery import recover_failed_withdrawal
from app.services.withdrawal import withdraw
from app.workers.payout_job import process_advance_payout_batch, run_advance_payout_worker
from app.workers.recovery_job import process_failed_withdrawal_batch


@pytest.fixture()
def session_factory() -> Generator[sessionmaker[Session], None, None]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    yield factory

    Base.metadata.drop_all(engine)


def create_user(session: Session, username: str, balance: Decimal = Decimal("0.00")) -> User:
    user = User(username=username, withdrawable_balance=balance)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def create_sale(session: Session, user: User, earnings: Decimal = Decimal("100.00")) -> Sale:
    sale = Sale(user_id=user.id, brand_name="Acme", earnings=earnings)
    session.add(sale)
    session.commit()
    session.refresh(sale)
    return sale


def test_advance_worker_processes_sales_in_batches(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        user = create_user(session, "merchant")
        create_sale(session, user, Decimal("100.00"))
        create_sale(session, user, Decimal("200.00"))
        create_sale(session, user, Decimal("300.00"))

    assert process_advance_payout_batch(session_factory, batch_size=2) == 2

    with session_factory() as session:
        user = session.query(User).filter_by(username="merchant").one()
        assert user.withdrawable_balance == Decimal("30.00")
        assert session.query(Transaction).count() == 2


def test_advance_worker_is_idempotent_when_run_twice(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        user = create_user(session, "merchant")
        create_sale(session, user, Decimal("100.00"))

    assert run_advance_payout_worker(session_factory, batch_size=100) == 1
    assert run_advance_payout_worker(session_factory, batch_size=100) == 0

    with session_factory() as session:
        user = session.query(User).filter_by(username="merchant").one()
        assert user.withdrawable_balance == Decimal("10.00")
        assert session.query(Transaction).count() == 1


def test_recovery_worker_credits_terminal_failed_withdrawals_once(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        user = create_user(session, "merchant", Decimal("-60.00"))
        for status in (
            TransactionStatus.FAILED,
            TransactionStatus.CANCELLED,
            TransactionStatus.REJECTED,
        ):
            session.add(
                Transaction(
                    user_id=user.id,
                    type=TransactionType.WITHDRAWAL,
                    amount=Decimal("-20.00"),
                    status=status,
                )
            )
        session.commit()

    assert process_failed_withdrawal_batch(session_factory, batch_size=100) == 3
    assert process_failed_withdrawal_batch(session_factory, batch_size=100) == 0

    with session_factory() as session:
        user = session.query(User).filter_by(username="merchant").one()
        assert user.withdrawable_balance == Decimal("0.00")
        recoveries = session.query(Transaction).filter_by(type=TransactionType.FAILED_RECOVERY)
        assert recoveries.count() == 3


def test_duplicate_recovery_is_rejected(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        user = create_user(session, "merchant", Decimal("-10.00"))
        withdrawal = Transaction(
            user_id=user.id,
            type=TransactionType.WITHDRAWAL,
            amount=Decimal("-10.00"),
            status=TransactionStatus.FAILED,
        )
        session.add(withdrawal)
        session.commit()
        session.refresh(withdrawal)

        recover_failed_withdrawal(session, withdrawal.id)

        with pytest.raises(HTTPException) as exc_info:
            recover_failed_withdrawal(session, withdrawal.id)

    assert exc_info.value.status_code == 400


def test_audit_passes_when_ledger_matches_wallet(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        user = create_user(session, "merchant", Decimal("30.00"))
        session.add(
            Transaction(
                user_id=user.id,
                type=TransactionType.ADVANCE_PAYOUT,
                amount=Decimal("30.00"),
                status=TransactionStatus.SUCCESS,
            )
        )
        session.commit()

        assert validate_user_wallet_integrity(session, user.id) is True


def test_audit_raises_when_ledger_and_wallet_diverge(
    session_factory: sessionmaker[Session],
) -> None:
    with session_factory() as session:
        user = create_user(session, "merchant", Decimal("25.00"))
        session.add(
            Transaction(
                user_id=user.id,
                type=TransactionType.ADVANCE_PAYOUT,
                amount=Decimal("30.00"),
                status=TransactionStatus.SUCCESS,
            )
        )
        session.commit()

        with pytest.raises(RuntimeError, match="Critical wallet audit failed"):
            validate_user_wallet_integrity(session, user.id)


def test_withdrawal_lock_failure_maps_to_conflict() -> None:
    session = Mock(spec=Session)
    lock_error = OperationalError(
        statement="select users for update nowait",
        params={},
        orig=Exception("could not obtain lock on row in relation users"),
    )
    session.scalar.side_effect = lock_error

    with pytest.raises(HTTPException) as exc_info:
        withdraw(session, User().id, Decimal("10.00"))

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "User wallet is busy; retry shortly."
    session.rollback.assert_called_once()
