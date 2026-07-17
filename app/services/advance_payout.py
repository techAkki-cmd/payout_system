from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Sale, SaleStatus, Transaction, TransactionStatus, TransactionType, User

MONEY_QUANTUM = Decimal("0.01")
ADVANCE_RATE = Decimal("0.10")


def process_advance_payouts(session: Session) -> int:
    try:
        sales = session.scalars(
            select(Sale)
            .where(Sale.status == SaleStatus.PENDING, Sale.is_advance_processed.is_(False))
            .with_for_update(skip_locked=True)
        ).all()

        processed_count = 0
        for sale in sales:
            # Locking the user row prevents overlapping workers from racing wallet credits.
            user = session.scalar(select(User).where(User.id == sale.user_id).with_for_update())
            if user is None:
                continue

            advance_amount = (sale.earnings * ADVANCE_RATE).quantize(MONEY_QUANTUM)
            sale.advance_paid = advance_amount
            sale.is_advance_processed = True
            user.withdrawable_balance += advance_amount

            session.add(
                Transaction(
                    user_id=user.id,
                    sale_id=sale.id,
                    type=TransactionType.ADVANCE_PAYOUT,
                    amount=advance_amount,
                    status=TransactionStatus.SUCCESS,
                )
            )
            processed_count += 1

        session.commit()
        return processed_count
    except Exception:
        session.rollback()
        raise
