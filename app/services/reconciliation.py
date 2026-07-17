import uuid
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Sale, SaleStatus, Transaction, TransactionStatus, TransactionType, User

MONEY_QUANTUM = Decimal("0.01")


def reconcile_sale(session: Session, sale_id: uuid.UUID, new_status: SaleStatus) -> Transaction:
    try:
        if new_status not in {SaleStatus.APPROVED, SaleStatus.REJECTED}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Sale can only be reconciled as approved or rejected.",
            )

        sale = session.scalar(select(Sale).where(Sale.id == sale_id).with_for_update())
        if sale is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sale not found.")

        # Locking the user row keeps reconciliation wallet writes serialized per user.
        user = session.scalar(select(User).where(User.id == sale.user_id).with_for_update())
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

        sale.status = new_status
        if new_status == SaleStatus.APPROVED:
            amount = (sale.earnings - sale.advance_paid).quantize(MONEY_QUANTUM)
            transaction_type = TransactionType.FINAL_PAYOUT
        else:
            amount = (-sale.advance_paid).quantize(MONEY_QUANTUM)
            transaction_type = TransactionType.RECONCILIATION_ADJUSTMENT

        user.withdrawable_balance += amount
        transaction = Transaction(
            user_id=user.id,
            sale_id=sale.id,
            type=transaction_type,
            amount=amount,
            status=TransactionStatus.SUCCESS,
        )
        session.add(transaction)
        session.commit()
        session.refresh(transaction)
        return transaction
    except Exception:
        session.rollback()
        raise
