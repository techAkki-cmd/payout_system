import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Transaction, User
from app.schemas import TransactionListResponse

router = APIRouter()
DBSession = Depends(get_db)


@router.get(
    "/{user_id}",
    response_model=TransactionListResponse,
    summary="Fetch ledger transactions for a user",
    description="Returns append-only ledger entries ordered newest first for dashboard auditing.",
)
def list_transactions_for_user(
    user_id: uuid.UUID,
    db: Session = DBSession,
) -> TransactionListResponse:
    try:
        user = db.scalar(select(User).where(User.id == user_id))
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

        transactions = db.scalars(
            select(Transaction)
            .where(Transaction.user_id == user_id)
            .order_by(Transaction.created_at.desc())
        ).all()
        return TransactionListResponse(user_id=user_id, transactions=list(transactions))
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database operation failed.",
        ) from exc
