from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import SaleStatus, Transaction, TransactionStatus, TransactionType
from app.services.advance_payout import process_advance_payouts
from app.services.reconciliation import reconcile_sale
from app.services.recovery import recover_failed_withdrawal
from app.services.withdrawal import withdraw
from tests.conftest import SaleFactory, UserFactory


def test_advance_payout_computes_exact_ten_percent_and_locks_sale(
    db_session: Session,
    user_factory: UserFactory,
    sale_factory: SaleFactory,
) -> None:
    # Arrange
    earnings = Decimal("250.00")
    expected_advance = Decimal("25.00")
    user = user_factory(balance=Decimal("0.00"))
    sale = sale_factory(user, earnings=earnings)

    # Act
    processed_count = process_advance_payouts(db_session)

    # Assert
    db_session.refresh(user)
    db_session.refresh(sale)
    transaction = db_session.scalar(select(Transaction))
    assert processed_count == 1
    assert user.withdrawable_balance == expected_advance
    assert sale.advance_paid == expected_advance
    assert sale.is_advance_processed is True
    assert transaction is not None
    assert transaction.type == TransactionType.ADVANCE_PAYOUT
    assert transaction.amount == expected_advance
    assert transaction.status == TransactionStatus.SUCCESS


def test_advance_payout_does_not_process_same_sale_twice(
    db_session: Session,
    user_factory: UserFactory,
    sale_factory: SaleFactory,
) -> None:
    # Arrange
    expected_advance = Decimal("10.00")
    user = user_factory(balance=Decimal("0.00"))
    sale_factory(user, earnings=Decimal("100.00"))

    # Act
    first_run_count = process_advance_payouts(db_session)
    second_run_count = process_advance_payouts(db_session)

    # Assert
    db_session.refresh(user)
    transactions = db_session.scalars(select(Transaction)).all()
    assert first_run_count == 1
    assert second_run_count == 0
    assert user.withdrawable_balance == expected_advance
    assert len(transactions) == 1


def test_reconciliation_approved_credits_earnings_minus_advance(
    db_session: Session,
    user_factory: UserFactory,
    sale_factory: SaleFactory,
) -> None:
    # Arrange
    starting_balance = Decimal("10.00")
    earnings = Decimal("100.00")
    advance_paid = Decimal("10.00")
    expected_remaining_payout = earnings - advance_paid
    expected_wallet_balance = starting_balance + expected_remaining_payout
    user = user_factory(balance=starting_balance)
    sale = sale_factory(
        user,
        earnings=earnings,
        advance_paid=advance_paid,
        is_advance_processed=True,
    )

    # Act
    transaction = reconcile_sale(db_session, sale.id, SaleStatus.APPROVED)

    # Assert
    db_session.refresh(user)
    db_session.refresh(sale)
    assert sale.status == SaleStatus.APPROVED
    assert user.withdrawable_balance == expected_wallet_balance
    assert transaction.type == TransactionType.FINAL_PAYOUT
    assert transaction.amount == expected_remaining_payout
    assert transaction.status == TransactionStatus.SUCCESS


def test_reconciliation_rejected_debits_advance_and_allows_negative_balance(
    db_session: Session,
    user_factory: UserFactory,
    sale_factory: SaleFactory,
) -> None:
    # Arrange
    starting_balance = Decimal("2.00")
    advance_paid = Decimal("10.00")
    expected_adjustment = -advance_paid
    expected_wallet_balance = starting_balance + expected_adjustment
    user = user_factory(balance=starting_balance)
    sale = sale_factory(
        user,
        earnings=Decimal("100.00"),
        advance_paid=advance_paid,
        is_advance_processed=True,
    )

    # Act
    transaction = reconcile_sale(db_session, sale.id, SaleStatus.REJECTED)

    # Assert
    db_session.refresh(user)
    db_session.refresh(sale)
    assert sale.status == SaleStatus.REJECTED
    assert user.withdrawable_balance == expected_wallet_balance
    assert transaction.type == TransactionType.RECONCILIATION_ADJUSTMENT
    assert transaction.amount == expected_adjustment


def test_withdraw_debits_balance_and_creates_initiated_ledger_entry(
    db_session: Session,
    user_factory: UserFactory,
) -> None:
    # Arrange
    starting_balance = Decimal("50.00")
    withdrawal_amount = Decimal("30.00")
    user = user_factory(balance=starting_balance)

    # Act
    transaction = withdraw(db_session, user.id, withdrawal_amount, reference_id="gateway-123")

    # Assert
    db_session.refresh(user)
    assert user.withdrawable_balance == starting_balance - withdrawal_amount
    assert user.last_withdrawal_at is not None
    assert transaction.type == TransactionType.WITHDRAWAL
    assert transaction.status == TransactionStatus.INITIATED
    assert transaction.amount == -withdrawal_amount
    assert transaction.reference_id == "gateway-123"


def test_withdrawal_fails_if_within_24_hours(
    db_session: Session,
    user_factory: UserFactory,
) -> None:
    # Arrange
    user = user_factory(balance=Decimal("50.00"))
    user.last_withdrawal_at = datetime.now(UTC) - timedelta(hours=1)
    db_session.commit()

    # Act / Assert
    with pytest.raises(HTTPException) as exc_info:
        withdraw(db_session, user.id, Decimal("10.00"))

    assert exc_info.value.status_code == 429


def test_withdraw_rejects_insufficient_balance(
    db_session: Session,
    user_factory: UserFactory,
) -> None:
    # Arrange
    user = user_factory(balance=Decimal("5.00"))

    # Act / Assert
    with pytest.raises(HTTPException) as exc_info:
        withdraw(db_session, user.id, Decimal("10.00"))

    assert exc_info.value.status_code == 400


def test_recover_failed_withdrawal_credits_balance_and_writes_audit_entry(
    db_session: Session,
    user_factory: UserFactory,
) -> None:
    # Arrange
    starting_balance = Decimal("20.00")
    withdrawal_amount = Decimal("15.00")
    user = user_factory(balance=starting_balance)
    withdrawal = withdraw(db_session, user.id, withdrawal_amount, reference_id="gateway-456")

    # Act
    recovery = recover_failed_withdrawal(db_session, withdrawal.id)

    # Assert
    db_session.refresh(user)
    db_session.refresh(withdrawal)
    assert withdrawal.status == TransactionStatus.FAILED
    assert user.withdrawable_balance == starting_balance
    assert recovery.type == TransactionType.FAILED_RECOVERY
    assert recovery.amount == withdrawal_amount
    assert recovery.status == TransactionStatus.SUCCESS
