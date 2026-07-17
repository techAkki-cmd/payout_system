from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas import AdvancePayoutTriggerResponse
from app.services import process_advance_payouts

router = APIRouter()
DBSession = Depends(get_db)


@router.post(
    "/advance/trigger",
    response_model=AdvancePayoutTriggerResponse,
    summary="Trigger advance payouts",
    description="Manually runs advance payout processing for pending, unprocessed sales.",
)
def trigger_advance_payouts(db: Session = DBSession) -> AdvancePayoutTriggerResponse:
    try:
        processed_count = process_advance_payouts(db)
        return AdvancePayoutTriggerResponse(processed_count=processed_count)
    except SQLAlchemyError as exc:
        raise HTTPException(status_code=500, detail="Database operation failed.") from exc
