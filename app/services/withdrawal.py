import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Transaction, TransactionStatus, TransactionType, User

MONEY_QUANTUM = Decimal("0.01")
WITHDRAWAL_LOCK_PERIOD = timedelta(hours=24)


def withdraw(
    session: Session,
    user_id: uuid.UUID,
    amount: Decimal,
    reference_id: str | None = None,
) -> Transaction:
    try:
        withdrawal_amount = amount.quantize(MONEY_QUANTUM)
        if withdrawal_amount <= Decimal("0.00"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Withdrawal amount must be positive.",
            )

        # Locking the user row prevents concurrent requests from spending the same balance twice.
        user = session.scalar(select(User).where(User.id == user_id).with_for_update())
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

        now = datetime.now(UTC)
        if user.last_withdrawal_at is not None:
            last_withdrawal_at = user.last_withdrawal_at
            if last_withdrawal_at.tzinfo is None:
                last_withdrawal_at = last_withdrawal_at.replace(tzinfo=UTC)
            if now - last_withdrawal_at < WITHDRAWAL_LOCK_PERIOD:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Withdrawals are limited to once every 24 hours.",
                )

        if withdrawal_amount > user.withdrawable_balance:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Insufficient withdrawable balance.",
            )

        user.withdrawable_balance -= withdrawal_amount
        user.last_withdrawal_at = now
        transaction = Transaction(
            user_id=user.id,
            sale_id=None,
            type=TransactionType.WITHDRAWAL,
            amount=-withdrawal_amount,
            status=TransactionStatus.INITIATED,
            reference_id=reference_id,
        )
        session.add(transaction)
        session.commit()
        session.refresh(transaction)
        return transaction
    except Exception:
        session.rollback()
        raise
