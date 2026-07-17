import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models import Sale, User
from app.schemas import SaleCreateRequest, SaleListResponse, SaleResponse

router = APIRouter()
DBSession = Depends(get_db)


@router.post(
    "/",
    response_model=SaleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Ingest a new sale",
    description=(
        "Creates a pending sale for an existing user. Advance payout processing is separate."
    ),
)
def create_sale(payload: SaleCreateRequest, db: Session = DBSession) -> Sale:
    try:
        user = db.scalar(select(User).where(User.id == payload.user_id))
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

        sale = Sale(
            user_id=payload.user_id,
            brand_name=payload.brand_name,
            earnings=payload.earnings.quantize(Decimal("0.01")),
        )
        db.add(sale)
        db.commit()
        db.refresh(sale)
        return sale
    except HTTPException:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database operation failed.",
        ) from exc


@router.get(
    "/{user_id}",
    response_model=SaleListResponse,
    summary="Fetch sales for a user",
    description="Returns all sales for a user ordered by creation time.",
)
def list_sales_for_user(user_id: uuid.UUID, db: Session = DBSession) -> SaleListResponse:
    try:
        user = db.scalar(select(User).where(User.id == user_id))
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

        sales = db.scalars(
            select(Sale).where(Sale.user_id == user_id).order_by(Sale.created_at)
        ).all()
        return SaleListResponse(user_id=user_id, sales=list(sales))
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Database operation failed.",
        ) from exc
