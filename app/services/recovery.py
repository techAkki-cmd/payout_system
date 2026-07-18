import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Transaction, TransactionStatus, TransactionType, User

RECOVERY_REFERENCE_PREFIX = "failed_recovery"


def recover_failed_withdrawal(session: Session, transaction_id: uuid.UUID) -> Transaction:
    try:
        transaction = session.scalar(
            select(Transaction).where(Transaction.id == transaction_id).with_for_update()
        )
        if transaction is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Withdrawal transaction not found.",
            )
        if transaction.type != TransactionType.WITHDRAWAL:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only withdrawal transactions can be recovered.",
            )
        if transaction.status not in {
            TransactionStatus.FAILED,
            TransactionStatus.CANCELLED,
            TransactionStatus.REJECTED,
            TransactionStatus.INITIATED,
        }:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Withdrawal transaction is not eligible for recovery.",
            )

        recovery_reference_id = build_recovery_reference_id(transaction.id)
        existing_recovery = session.scalar(
            select(Transaction).where(Transaction.reference_id == recovery_reference_id)
        )
        if existing_recovery is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Withdrawal transaction has already been recovered.",
            )

        # Locking the user row keeps recovery credits serialized with withdrawals.
        user = session.scalar(select(User).where(User.id == transaction.user_id).with_for_update())
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

        recovery_amount = abs(transaction.amount)
        transaction.status = TransactionStatus.FAILED
        user.withdrawable_balance += recovery_amount

        recovery = Transaction(
            user_id=user.id,
            sale_id=None,
            type=TransactionType.FAILED_RECOVERY,
            amount=recovery_amount,
            status=TransactionStatus.SUCCESS,
            reference_id=recovery_reference_id,
        )
        session.add(recovery)
        session.commit()
        session.refresh(recovery)
        return recovery
    except Exception:
        session.rollback()
        raise


def build_recovery_reference_id(transaction_id: uuid.UUID) -> str:
    return f"{RECOVERY_REFERENCE_PREFIX}:{transaction_id}"
