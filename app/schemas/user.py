import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    username: str
    withdrawable_balance: Decimal = Field(decimal_places=2)
    last_withdrawal_at: datetime | None
    created_at: datetime
    updated_at: datetime
