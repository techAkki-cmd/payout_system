import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from threading import Lock

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.models import Transaction, TransactionStatus, TransactionType, User

MONEY_QUANTUM = Decimal("0.01")
WITHDRAWAL_LOCK_PERIOD = timedelta(hours=24)
_wallet_lock_registry: dict[uuid.UUID, Lock] = {}
_wallet_lock_registry_guard = Lock()


def withdraw(
    session: Session,
    user_id: uuid.UUID,
    amount: Decimal,
    reference_id: str | None = None,
) -> Transaction:
    wallet_lock = get_wallet_lock(user_id)
    if not wallet_lock.acquire(blocking=False):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="User wallet is busy; retry shortly.",
        )

    try:
        withdrawal_amount = amount.quantize(MONEY_QUANTUM)
        if withdrawal_amount <= Decimal("0.00"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Withdrawal amount must be positive.",
            )

        # `nowait` fails fast if another request is already mutating this wallet.
        user = session.scalar(select(User).where(User.id == user_id).with_for_update(nowait=True))
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")

        now = datetime.now(UTC)
        if user.last_withdrawal_at is not None:
            last_withdrawal_at = user.last_withdrawal_at
            if last_withdrawal_at.tzinfo is None:
                last_withdrawal_at = last_withdrawal_at.replace(tzinfo=UTC)
            if now - last_withdrawal_at < WITHDRAWAL_LOCK_PERIOD:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail="Withdrawals are limited to once every 24 hours.",
                )

        if withdrawal_amount > user.withdrawable_balance:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Insufficient withdrawable balance.",
            )

        user.withdrawable_balance -= withdrawal_amount
        user.last_withdrawal_at = now
        transaction = Transaction(
            user_id=user.id,
            sale_id=None,
            type=TransactionType.WITHDRAWAL,
            amount=-withdrawal_amount,
            status=TransactionStatus.INITIATED,
            reference_id=reference_id,
        )
        session.add(transaction)
        session.commit()
        session.refresh(transaction)
        return transaction
    except DBAPIError as exc:
        session.rollback()
        if is_lock_error(exc):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="User wallet is busy; retry shortly.",
            ) from exc
        raise
    except Exception:
        session.rollback()
        raise
    finally:
        wallet_lock.release()


def is_lock_error(exc: DBAPIError) -> bool:
    original = str(exc.orig).lower() if getattr(exc, "orig", None) is not None else str(exc).lower()
    return any(
        marker in original
        for marker in (
            "could not obtain lock",
            "lock not available",
            "database is locked",
            "nowait",
        )
    )


def get_wallet_lock(user_id: uuid.UUID) -> Lock:
    with _wallet_lock_registry_guard:
        if user_id not in _wallet_lock_registry:
            _wallet_lock_registry[user_id] = Lock()
        return _wallet_lock_registry[user_id]
