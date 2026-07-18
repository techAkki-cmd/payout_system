from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.database import SessionLocal
from app.models import Transaction, TransactionStatus, TransactionType
from app.services.recovery import build_recovery_reference_id, recover_failed_withdrawal

SessionFactory = Callable[[], Session]

RECOVERABLE_WITHDRAWAL_STATUSES = (
    TransactionStatus.FAILED,
    TransactionStatus.CANCELLED,
    TransactionStatus.REJECTED,
)


def process_failed_withdrawal_batch(
    session_factory: SessionFactory = SessionLocal,
    batch_size: int = 100,
) -> int:
    session = session_factory()
    try:
        failed_withdrawals = session.scalars(
            select(Transaction)
            .where(
                Transaction.type == TransactionType.WITHDRAWAL,
                Transaction.status.in_(RECOVERABLE_WITHDRAWAL_STATUSES),
            )
            .limit(batch_size)
            # SKIP LOCKED keeps multiple recovery workers from compensating the same row.
            .with_for_update(skip_locked=True)
        ).all()

        recovered_count = 0
        for withdrawal in failed_withdrawals:
            recovery_reference_id = build_recovery_reference_id(withdrawal.id)
            existing_recovery = session.scalar(
                select(Transaction).where(Transaction.reference_id == recovery_reference_id)
            )
            if existing_recovery is not None:
                continue

            recover_failed_withdrawal(session, withdrawal.id)
            recovered_count += 1

        return recovered_count
    finally:
        session.close()


def run_recovery_worker(
    session_factory: SessionFactory = SessionLocal,
    batch_size: int = 100,
    max_batches: int | None = None,
) -> int:
    total_recovered = 0
    batches_processed = 0

    while max_batches is None or batches_processed < max_batches:
        recovered_count = process_failed_withdrawal_batch(session_factory, batch_size)
        if recovered_count == 0:
            break

        total_recovered += recovered_count
        batches_processed += 1

    return total_recovered
