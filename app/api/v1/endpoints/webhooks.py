from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas import FailedWithdrawalWebhookRequest, FailedWithdrawalWebhookResponse
from app.services import recover_failed_withdrawal

router = APIRouter()
DBSession = Depends(get_db)


@router.post(
    "/withdrawals/failed",
    response_model=FailedWithdrawalWebhookResponse,
    summary="Handle failed withdrawal webhook",
    description=(
        "Marks a failed withdrawal and writes a recovery ledger entry that credits the user."
    ),
)
def handle_failed_withdrawal_webhook(
    payload: FailedWithdrawalWebhookRequest,
    db: Session = DBSession,
) -> FailedWithdrawalWebhookResponse:
    try:
        recovery_transaction = recover_failed_withdrawal(db, payload.transaction_id)
        return FailedWithdrawalWebhookResponse(recovery_transaction=recovery_transaction)
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail="Database operation failed.") from exc
