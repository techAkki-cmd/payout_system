import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models import SaleStatus


class SaleCreateRequest(BaseModel):
    user_id: uuid.UUID
    brand_name: str = Field(min_length=1, max_length=255)
    earnings: Decimal = Field(gt=Decimal("0.00"), decimal_places=2)


class SaleResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    brand_name: str
    status: SaleStatus
    earnings: Decimal = Field(decimal_places=2)
    advance_paid: Decimal = Field(decimal_places=2)
    is_advance_processed: bool
    created_at: datetime
    updated_at: datetime


class SaleListResponse(BaseModel):
    user_id: uuid.UUID
    sales: list[SaleResponse]
