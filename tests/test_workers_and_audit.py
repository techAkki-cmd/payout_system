from decimal import Decimal
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.core.audit import validate_user_wallet_integrity
from app.models import Transaction, TransactionStatus, TransactionType, User
from app.services.recovery import recover_failed_withdrawal
from app.services.withdrawal import withdraw
from app.workers.payout_job import process_advance_payout_batch, run_advance_payout_worker
from app.workers.recovery_job import process_failed_withdrawal_batch
from tests.conftest import SaleFactory, TransactionFactory, UserFactory


def test_advance_worker_processes_sales_in_batches(
    db_session: Session,
    session_factory: sessionmaker[Session],
    user_factory: UserFactory,
    sale_factory: SaleFactory,
) -> None:
    # Arrange
    user = user_factory(username="merchant")
    sale_factory(user, earnings=Decimal("100.00"))
    sale_factory(user, earnings=Decimal("200.00"))
    sale_factory(user, earnings=Decimal("300.00"))

    # Act
    processed_count = process_advance_payout_batch(session_factory, batch_size=2)

    # Assert
    db_session.refresh(user)
    assert processed_count == 2
    assert user.withdrawable_balance == Decimal("30.00")
    assert db_session.query(Transaction).count() == 2


def test_advance_worker_is_idempotent_when_run_twice(
    db_session: Session,
    session_factory: sessionmaker[Session],
    user_factory: UserFactory,
    sale_factory: SaleFactory,
) -> None:
    # Arrange
    user = user_factory(username="merchant")
    sale_factory(user, earnings=Decimal("100.00"))

    # Act
    first_total = run_advance_payout_worker(session_factory, batch_size=100)
    second_total = run_advance_payout_worker(session_factory, batch_size=100)

    # Assert
    db_session.refresh(user)
    assert first_total == 1
    assert second_total == 0
    assert user.withdrawable_balance == Decimal("10.00")
    assert db_session.query(Transaction).count() == 1


def test_recovery_worker_credits_terminal_failed_withdrawals_once(
    db_session: Session,
    session_factory: sessionmaker[Session],
    user_factory: UserFactory,
    transaction_factory: TransactionFactory,
) -> None:
    # Arrange
    user = user_factory(username="merchant", balance=Decimal("-60.00"))
    failed_statuses = (
        TransactionStatus.FAILED,
        TransactionStatus.CANCELLED,
        TransactionStatus.REJECTED,
    )
    for failed_status in failed_statuses:
        transaction_factory(
            user=user,
            amount=Decimal("-20.00"),
            transaction_type=TransactionType.WITHDRAWAL,
            status=failed_status,
        )

    # Act
    first_recovery_count = process_failed_withdrawal_batch(session_factory, batch_size=100)
    second_recovery_count = process_failed_withdrawal_batch(session_factory, batch_size=100)

    # Assert
    db_session.refresh(user)
    recoveries = db_session.query(Transaction).filter_by(type=TransactionType.FAILED_RECOVERY)
    assert first_recovery_count == 3
    assert second_recovery_count == 0
    assert user.withdrawable_balance == Decimal("0.00")
    assert recoveries.count() == 3


def test_duplicate_recovery_is_rejected(
    db_session: Session,
    user_factory: UserFactory,
    transaction_factory: TransactionFactory,
) -> None:
    # Arrange
    user = user_factory(username="merchant", balance=Decimal("-10.00"))
    withdrawal = transaction_factory(
        user=user,
        amount=Decimal("-10.00"),
        transaction_type=TransactionType.WITHDRAWAL,
        status=TransactionStatus.FAILED,
    )
    recover_failed_withdrawal(db_session, withdrawal.id)

    # Act / Assert
    with pytest.raises(HTTPException) as exc_info:
        recover_failed_withdrawal(db_session, withdrawal.id)

    assert exc_info.value.status_code == 400


def test_audit_passes_when_ledger_matches_wallet(
    db_session: Session,
    user_factory: UserFactory,
    transaction_factory: TransactionFactory,
) -> None:
    # Arrange
    user = user_factory(username="merchant", balance=Decimal("30.00"))
    transaction_factory(
        user=user,
        amount=Decimal("30.00"),
        transaction_type=TransactionType.ADVANCE_PAYOUT,
        status=TransactionStatus.SUCCESS,
    )

    # Act / Assert
    assert validate_user_wallet_integrity(db_session, user.id) is True


def test_audit_passes_after_failed_withdrawal_recovery(
    db_session: Session,
    user_factory: UserFactory,
    transaction_factory: TransactionFactory,
) -> None:
    # Arrange
    user = user_factory(username="merchant", balance=Decimal("100.00"))
    transaction_factory(
        user=user,
        amount=Decimal("100.00"),
        transaction_type=TransactionType.FINAL_PAYOUT,
        status=TransactionStatus.SUCCESS,
    )
    withdrawal = transaction_factory(
        user=user,
        amount=Decimal("-50.00"),
        transaction_type=TransactionType.WITHDRAWAL,
        status=TransactionStatus.INITIATED,
    )
    user.withdrawable_balance = Decimal("50.00")
    db_session.commit()

    recover_failed_withdrawal(db_session, withdrawal.id)

    # Act / Assert
    assert validate_user_wallet_integrity(db_session, user.id) is True


def test_audit_raises_when_ledger_and_wallet_diverge(
    db_session: Session,
    user_factory: UserFactory,
    transaction_factory: TransactionFactory,
) -> None:
    # Arrange
    user = user_factory(username="merchant", balance=Decimal("25.00"))
    transaction_factory(
        user=user,
        amount=Decimal("30.00"),
        transaction_type=TransactionType.ADVANCE_PAYOUT,
        status=TransactionStatus.SUCCESS,
    )

    # Act / Assert
    with pytest.raises(RuntimeError, match="Critical wallet audit failed"):
        validate_user_wallet_integrity(db_session, user.id)


def test_withdrawal_lock_failure_maps_to_conflict() -> None:
    # Arrange
    session = Mock(spec=Session)
    lock_error = OperationalError(
        statement="select users for update nowait",
        params={},
        orig=Exception("could not obtain lock on row in relation users"),
    )
    session.scalar.side_effect = lock_error

    # Act / Assert
    with pytest.raises(HTTPException) as exc_info:
        withdraw(session, User().id, Decimal("10.00"))

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "User wallet is busy; retry shortly."
    session.rollback.assert_called_once()
