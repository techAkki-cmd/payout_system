import uuid
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Transaction, TransactionStatus, User

MONEY_QUANTUM = Decimal("0.01")
AUDITED_TRANSACTION_STATUSES = (
    TransactionStatus.INITIATED,
    TransactionStatus.SUCCESS,
)


def validate_user_wallet_integrity(session: Session, user_id: uuid.UUID) -> bool:
    user = session.scalar(select(User).where(User.id == user_id))
    if user is None:
        raise RuntimeError(f"Critical wallet audit failed: user {user_id} was not found.")

    ledger_total = session.scalar(
        select(func.coalesce(func.sum(Transaction.amount), Decimal("0.00"))).where(
            Transaction.user_id == user_id,
            Transaction.status.in_(AUDITED_TRANSACTION_STATUSES),
        )
    )
    ledger_total = Decimal(ledger_total or Decimal("0.00")).quantize(MONEY_QUANTUM)
    wallet_balance = user.withdrawable_balance.quantize(MONEY_QUANTUM)

    if ledger_total != wallet_balance:
        raise RuntimeError(
            "Critical wallet audit failed: "
            f"user_id={user_id} ledger_total={ledger_total} "
            f"withdrawable_balance={wallet_balance}"
        )

    return True
