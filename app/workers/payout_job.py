from collections.abc import Callable
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models import Sale, SaleStatus, Transaction, TransactionStatus, TransactionType, User

MONEY_QUANTUM = Decimal("0.01")
ADVANCE_RATE = Decimal("0.10")

SessionFactory = Callable[[], Session]


def process_advance_payout_batch(
    session_factory: SessionFactory = SessionLocal,
    batch_size: int = 100,
) -> int:
    session = session_factory()
    try:
        sales = session.scalars(
            select(Sale)
            .where(Sale.status == SaleStatus.PENDING, Sale.is_advance_processed.is_(False))
            .limit(batch_size)
            # SKIP LOCKED lets parallel workers divide the queue without blocking each other.
            .with_for_update(skip_locked=True)
        ).all()

        processed_count = 0
        for sale in sales:
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
    finally:
        session.close()


def run_advance_payout_worker(
    session_factory: SessionFactory = SessionLocal,
    batch_size: int = 100,
    max_batches: int | None = None,
) -> int:
    total_processed = 0
    batches_processed = 0

    while max_batches is None or batches_processed < max_batches:
        processed_count = process_advance_payout_batch(session_factory, batch_size)
        if processed_count == 0:
            break

        total_processed += processed_count
        batches_processed += 1

    return total_processed
