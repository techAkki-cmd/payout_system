import uuid
from decimal import Decimal

from pydantic import BaseModel, Field

from app.models import SaleStatus
from app.schemas.transaction import TransactionResponse


class ReconciliationRequest(BaseModel):
    status: SaleStatus


class AdvancePayoutTriggerResponse(BaseModel):
    processed_count: int = Field(ge=0)


class WithdrawalRequest(BaseModel):
    user_id: uuid.UUID
    amount: Decimal = Field(gt=Decimal("0.00"), decimal_places=2)
    reference_id: str | None = Field(default=None, max_length=255)


class WithdrawalResponse(BaseModel):
    transaction: TransactionResponse


class FailedWithdrawalWebhookRequest(BaseModel):
    transaction_id: uuid.UUID


class FailedWithdrawalWebhookResponse(BaseModel):
    recovery_transaction: TransactionResponse
