from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import get_db
from app.main import app
from app.models import Base, Sale, Transaction, TransactionStatus, TransactionType, User


@pytest.fixture()
def session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    with testing_session() as db:
        yield db

    Base.metadata.drop_all(engine)


@pytest.fixture()
def client(session: Session) -> Generator[TestClient, None, None]:
    def override_get_db() -> Generator[Session, None, None]:
        yield session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def create_user(session: Session, balance: Decimal = Decimal("0.00")) -> User:
    user = User(username="merchant", withdrawable_balance=balance)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user


def create_sale(session: Session, user: User, earnings: Decimal = Decimal("100.00")) -> Sale:
    sale = Sale(user_id=user.id, brand_name="Acme", earnings=earnings)
    session.add(sale)
    session.commit()
    session.refresh(sale)
    return sale


def test_create_sale_for_existing_user_returns_created_sale(
    client: TestClient,
    session: Session,
) -> None:
    user = create_user(session)

    response = client.post(
        "/api/v1/sales/",
        json={
            "user_id": str(user.id),
            "brand_name": "Acme",
            "earnings": "125.50",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["user_id"] == str(user.id)
    assert body["brand_name"] == "Acme"
    assert body["status"] == "PENDING"
    assert body["earnings"] == "125.50"
    assert body["advance_paid"] == "0.00"
    assert body["is_advance_processed"] is False


def test_create_sale_for_missing_user_returns_not_found(client: TestClient) -> None:
    response = client.post(
        "/api/v1/sales/",
        json={
            "user_id": "00000000-0000-0000-0000-000000000000",
            "brand_name": "Acme",
            "earnings": "10.00",
        },
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "User not found."}


def test_list_sales_returns_only_requested_users_sales(
    client: TestClient,
    session: Session,
) -> None:
    user = create_user(session)
    other_user = User(username="other", withdrawable_balance=Decimal("0.00"))
    session.add(other_user)
    session.commit()
    session.refresh(other_user)
    create_sale(session, user, Decimal("10.00"))
    create_sale(session, other_user, Decimal("99.00"))

    response = client.get(f"/api/v1/sales/{user.id}")

    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == str(user.id)
    assert len(body["sales"]) == 1
    assert body["sales"][0]["earnings"] == "10.00"


def test_reconciliation_approved_returns_final_payout_transaction(
    client: TestClient,
    session: Session,
) -> None:
    user = create_user(session, balance=Decimal("10.00"))
    sale = create_sale(session, user, Decimal("100.00"))
    sale.advance_paid = Decimal("10.00")
    sale.is_advance_processed = True
    session.commit()

    response = client.post(f"/api/v1/reconciliation/{sale.id}", json={"status": "APPROVED"})

    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "FINAL_PAYOUT"
    assert body["amount"] == "90.00"
    session.refresh(user)
    assert user.withdrawable_balance == Decimal("100.00")


def test_advance_trigger_returns_processed_count(client: TestClient, session: Session) -> None:
    user = create_user(session)
    create_sale(session, user, Decimal("100.00"))

    response = client.post("/api/v1/payouts/advance/trigger")

    assert response.status_code == 200
    assert response.json() == {"processed_count": 1}
    session.refresh(user)
    assert user.withdrawable_balance == Decimal("10.00")


def test_withdrawal_success_returns_accepted_debit_transaction(
    client: TestClient,
    session: Session,
) -> None:
    user = create_user(session, balance=Decimal("50.00"))

    response = client.post(
        "/api/v1/withdrawals/",
        json={
            "user_id": str(user.id),
            "amount": "25.00",
            "reference_id": "gateway-789",
        },
    )

    assert response.status_code == 202
    body = response.json()["transaction"]
    assert body["type"] == "WITHDRAWAL"
    assert body["status"] == "INITIATED"
    assert body["amount"] == "-25.00"
    assert body["reference_id"] == "gateway-789"


def test_withdrawal_within_twenty_four_hours_returns_rate_limit(
    client: TestClient,
    session: Session,
) -> None:
    user = create_user(session, balance=Decimal("50.00"))
    user.last_withdrawal_at = datetime.now(UTC) - timedelta(hours=1)
    session.commit()

    response = client.post(
        "/api/v1/withdrawals/",
        json={"user_id": str(user.id), "amount": "10.00"},
    )

    assert response.status_code == 429
    assert response.json() == {"detail": "Withdrawals are limited to once every 24 hours."}


def test_failed_withdrawal_webhook_creates_recovery_transaction(
    client: TestClient,
    session: Session,
) -> None:
    user = create_user(session, balance=Decimal("20.00"))
    withdrawal = Transaction(
        user_id=user.id,
        type=TransactionType.WITHDRAWAL,
        amount=Decimal("-15.00"),
        status=TransactionStatus.INITIATED,
        reference_id="gateway-failed",
    )
    user.withdrawable_balance = Decimal("5.00")
    session.add(withdrawal)
    session.commit()
    session.refresh(withdrawal)

    response = client.post(
        "/api/v1/webhooks/withdrawals/failed",
        json={"transaction_id": str(withdrawal.id)},
    )

    assert response.status_code == 200
    body = response.json()["recovery_transaction"]
    assert body["type"] == "FAILED_RECOVERY"
    assert body["amount"] == "15.00"
    session.refresh(user)
    assert user.withdrawable_balance == Decimal("20.00")
    assert session.scalar(select(Transaction).where(Transaction.id == withdrawal.id)).status == (
        TransactionStatus.FAILED
    )
