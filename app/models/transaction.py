import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampedUUIDMixin
from app.models.enums import TransactionStatus, TransactionType

if TYPE_CHECKING:
    from app.models.sale import Sale
    from app.models.user import User


class Transaction(TimestampedUUIDMixin, Base):
    """Append-only ledger entry for every wallet movement.

    Balance-impacting events should create new transaction rows instead of mutating
    existing ones, preserving a traceable financial history for credits and debits.
    """

    __tablename__ = "transactions"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    sale_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("sales.id"))
    type: Mapped[TransactionType] = mapped_column(
        Enum(TransactionType, name="transaction_type"),
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    status: Mapped[TransactionStatus] = mapped_column(
        Enum(TransactionStatus, name="transaction_status"),
        nullable=False,
    )
    reference_id: Mapped[str | None] = mapped_column(String(255), unique=True)

    user: Mapped["User"] = relationship(back_populates="transactions")
    sale: Mapped["Sale | None"] = relationship(back_populates="transactions")
