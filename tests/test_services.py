from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.models import Base, Sale, SaleStatus, Transaction, TransactionStatus, TransactionType, User
from app.services.advance_payout import process_advance_payouts
from app.services.reconciliation import reconcile_sale
from app.services.recovery import recover_failed_withdrawal
from app.services.withdrawal import withdraw


@pytest.fixture()
def session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    with testing_session() as db:
        yield db

    Base.metadata.drop_all(engine)


def create_user(session: Session, balance: Decimal = Decimal("0.00")) -> User:
    user = User(username="merchant", withdrawable_balance=balance)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def create_sale(
    session: Session,
    user: User,
    earnings: Decimal = Decimal("100.00"),
    advance_paid: Decimal = Decimal("0.00"),
    is_advance_processed: bool = False,
) -> Sale:
    sale = Sale(
        user_id=user.id,
        brand_name="Acme",
        earnings=earnings,
        advance_paid=advance_paid,
        is_advance_processed=is_advance_processed,
    )
    session.add(sale)
    session.commit()
    session.refresh(sale)
    return sale


def test_process_advance_payouts_credits_ten_percent_once(session: Session) -> None:
    user = create_user(session)
    sale = create_sale(session, user, earnings=Decimal("250.00"))

    assert process_advance_payouts(session) == 1

    session.refresh(user)
    session.refresh(sale)
    transaction = session.scalar(select(Transaction))

    assert user.withdrawable_balance == Decimal("25.00")
    assert sale.advance_paid == Decimal("25.00")
    assert sale.is_advance_processed is True
    assert transaction is not None
    assert transaction.type == TransactionType.ADVANCE_PAYOUT
    assert transaction.amount == Decimal("25.00")
    assert transaction.status == TransactionStatus.SUCCESS

    assert process_advance_payouts(session) == 0
    session.refresh(user)
    assert user.withdrawable_balance == Decimal("25.00")
    assert len(session.scalars(select(Transaction)).all()) == 1


def test_reconcile_approved_sale_credits_remaining_payout(session: Session) -> None:
    user = create_user(session, balance=Decimal("10.00"))
    sale = create_sale(
        session,
        user,
        earnings=Decimal("100.00"),
        advance_paid=Decimal("10.00"),
        is_advance_processed=True,
    )

    transaction = reconcile_sale(session, sale.id, SaleStatus.APPROVED)

    session.refresh(user)
    session.refresh(sale)
    assert sale.status == SaleStatus.APPROVED
    assert user.withdrawable_balance == Decimal("100.00")
    assert transaction.type == TransactionType.FINAL_PAYOUT
    assert transaction.amount == Decimal("90.00")
    assert transaction.status == TransactionStatus.SUCCESS


def test_reconcile_rejected_sale_debits_advance_and_allows_negative_balance(
    session: Session,
) -> None:
    user = create_user(session, balance=Decimal("2.00"))
    sale = create_sale(
        session,
        user,
        earnings=Decimal("100.00"),
        advance_paid=Decimal("10.00"),
        is_advance_processed=True,
    )

    transaction = reconcile_sale(session, sale.id, SaleStatus.REJECTED)

    session.refresh(user)
    session.refresh(sale)
    assert sale.status == SaleStatus.REJECTED
    assert user.withdrawable_balance == Decimal("-8.00")
    assert transaction.type == TransactionType.RECONCILIATION_ADJUSTMENT
    assert transaction.amount == Decimal("-10.00")


def test_withdraw_debits_balance_and_creates_initiated_ledger_entry(session: Session) -> None:
    user = create_user(session, balance=Decimal("50.00"))

    transaction = withdraw(session, user.id, Decimal("30.00"), reference_id="gateway-123")

    session.refresh(user)
    assert user.withdrawable_balance == Decimal("20.00")
    assert user.last_withdrawal_at is not None
    assert transaction.type == TransactionType.WITHDRAWAL
    assert transaction.status == TransactionStatus.INITIATED
    assert transaction.amount == Decimal("-30.00")
    assert transaction.reference_id == "gateway-123"


def test_withdraw_enforces_twenty_four_hour_lock(session: Session) -> None:
    user = create_user(session, balance=Decimal("50.00"))
    user.last_withdrawal_at = datetime.now(UTC) - timedelta(hours=1)
    session.commit()

    with pytest.raises(HTTPException) as exc_info:
        withdraw(session, user.id, Decimal("10.00"))

    assert exc_info.value.status_code == 429


def test_withdraw_rejects_insufficient_balance(session: Session) -> None:
    user = create_user(session, balance=Decimal("5.00"))

    with pytest.raises(HTTPException) as exc_info:
        withdraw(session, user.id, Decimal("10.00"))

    assert exc_info.value.status_code == 400


def test_recover_failed_withdrawal_credits_balance_and_writes_audit_entry(
    session: Session,
) -> None:
    user = create_user(session, balance=Decimal("20.00"))
    withdrawal = withdraw(session, user.id, Decimal("15.00"), reference_id="gateway-456")

    recovery = recover_failed_withdrawal(session, withdrawal.id)

    session.refresh(user)
    session.refresh(withdrawal)
    assert withdrawal.status == TransactionStatus.FAILED
    assert user.withdrawable_balance == Decimal("20.00")
    assert recovery.type == TransactionType.FAILED_RECOVERY
    assert recovery.amount == Decimal("15.00")
    assert recovery.status == TransactionStatus.SUCCESS
