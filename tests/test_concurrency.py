from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Transaction, TransactionType, User
from tests.conftest import UserFactory


def test_concurrent_full_balance_withdrawals_do_not_double_spend(
    client: TestClient,
    db_session: Session,
    user_factory: UserFactory,
) -> None:
    # Arrange
    starting_balance = Decimal("100.00")
    withdrawal_amount = Decimal("100.00")
    user = user_factory(username="merchant", balance=starting_balance)
    start_line = Barrier(2)

    def submit_withdrawal(reference_id: str) -> int:
        start_line.wait()
        response = client.post(
            "/api/v1/withdrawals/",
            json={
                "user_id": str(user.id),
                "amount": str(withdrawal_amount),
                "reference_id": reference_id,
            },
        )
        return response.status_code

    # Act
    with ThreadPoolExecutor(max_workers=2) as executor:
        status_codes = list(
            executor.map(submit_withdrawal, ("attack-click-1", "attack-click-2"))
        )

    # Assert
    db_session.expire_all()
    refreshed_user = db_session.scalar(select(User).where(User.id == user.id))
    withdrawal_debits = db_session.scalars(
        select(Transaction).where(
            Transaction.user_id == user.id,
            Transaction.type == TransactionType.WITHDRAWAL,
        )
    ).all()

    assert status_codes.count(202) == 1
    assert sum(status_code in {400, 409, 429} for status_code in status_codes) == 1
    assert refreshed_user is not None
    assert refreshed_user.withdrawable_balance >= Decimal("0.00")
    assert refreshed_user.withdrawable_balance == Decimal("0.00")
    assert len(withdrawal_debits) == 1
    assert withdrawal_debits[0].amount == -withdrawal_amount
