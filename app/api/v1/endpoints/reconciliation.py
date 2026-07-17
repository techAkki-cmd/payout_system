import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import SaleStatus, Transaction
from app.schemas import ReconciliationRequest, TransactionResponse
from app.services import reconcile_sale

router = APIRouter()
DBSession = Depends(get_db)


@router.post(
    "/{sale_id}",
    response_model=TransactionResponse,
    summary="Reconcile a sale",
    description=(
        "Marks a sale as approved or rejected and writes the corresponding payout ledger entry."
    ),
)
def reconcile_sale_endpoint(
    sale_id: uuid.UUID,
    payload: ReconciliationRequest,
    db: Session = DBSession,
) -> Transaction:
    if payload.status == SaleStatus.PENDING:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Sale can only be reconciled as approved or rejected.",
        )

    try:
        return reconcile_sale(db, sale_id, payload.status)
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database operation failed.",
        ) from exc
