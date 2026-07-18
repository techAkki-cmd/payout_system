import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models import TransactionStatus, TransactionType


class TransactionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    sale_id: uuid.UUID | None
    type: TransactionType
    amount: Decimal = Field(decimal_places=2)
    status: TransactionStatus
    reference_id: str | None
    created_at: datetime
    updated_at: datetime


class TransactionListResponse(BaseModel):
    user_id: uuid.UUID
    transactions: list[TransactionResponse]
