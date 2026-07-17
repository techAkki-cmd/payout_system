import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Enum, ForeignKey, Index, Numeric, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampedUUIDMixin
from app.models.enums import SaleStatus

if TYPE_CHECKING:
    from app.models.transaction import Transaction
    from app.models.user import User


class Sale(TimestampedUUIDMixin, Base):
    """Represents an earning event and its advance-payout idempotency state.

    `is_advance_processed` is intentionally stored on the sale row so overlapping
    workers can lock/update the same source record and avoid paying an advance twice.
    """

    __tablename__ = "sales"
    __table_args__ = (
        Index("ix_sales_status", "status"),
        Index("ix_sales_is_advance_processed", "is_advance_processed"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    brand_name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[SaleStatus] = mapped_column(
        Enum(SaleStatus, name="sale_status"),
        default=SaleStatus.PENDING,
        server_default=SaleStatus.PENDING.value,
        nullable=False,
    )
    earnings: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    advance_paid: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        default=Decimal("0.00"),
        server_default=text("0.00"),
        nullable=False,
    )
    is_advance_processed: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=text("false"),
        nullable=False,
    )

    user: Mapped["User"] = relationship(back_populates="sales")
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="sale")
