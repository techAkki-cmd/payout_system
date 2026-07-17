from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas import WithdrawalRequest, WithdrawalResponse
from app.services import withdraw

router = APIRouter()
DBSession = Depends(get_db)


@router.post(
    "/",
    response_model=WithdrawalResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Initiate a withdrawal",
    description=(
        "Debits a user's withdrawable balance and creates an initiated withdrawal ledger entry."
    ),
)
def initiate_withdrawal(
    payload: WithdrawalRequest,
    db: Session = DBSession,
) -> WithdrawalResponse:
    try:
        transaction = withdraw(db, payload.user_id, payload.amount, payload.reference_id)
        return WithdrawalResponse(transaction=transaction)
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database operation failed.",
        ) from exc
