import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Transaction, TransactionStatus, TransactionType, User


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
        if transaction.status == TransactionStatus.FAILED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Withdrawal transaction has already failed.",
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
            reference_id=f"failed_recovery:{transaction.id}",
        )
        session.add(recovery)
        session.commit()
        session.refresh(recovery)
        return recovery
    except Exception:
        session.rollback()
        raise
