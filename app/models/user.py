from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Numeric, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampedUUIDMixin

if TYPE_CHECKING:
    from app.models.sale import Sale
    from app.models.transaction import Transaction


class User(TimestampedUUIDMixin, Base):
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    withdrawable_balance: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        default=Decimal("0.00"),
        server_default=text("0.00"),
        nullable=False,
    )
    last_withdrawal_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    sales: Mapped[list["Sale"]] = relationship(back_populates="user")
    transactions: Mapped[list["Transaction"]] = relationship(back_populates="user")
