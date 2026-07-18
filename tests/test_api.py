from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models import TransactionStatus, TransactionType
from tests.conftest import SaleFactory, TransactionFactory, UserFactory


def test_dashboard_html_is_served(client: TestClient) -> None:
    # Arrange / Act
    response = client.get("/")

    # Assert
    assert response.status_code == 200
    assert "Creator Payout Operations Console" in response.text
    assert "Run 10% Advance Payout Worker" in response.text


def test_create_and_fetch_demo_user(client: TestClient) -> None:
    # Arrange
    payload = {"username": "mumbai_creator"}

    # Act
    create_response = client.post("/api/v1/users/", json=payload)
    created_user = create_response.json()
    fetch_response = client.get(f"/api/v1/users/{created_user['id']}")

    # Assert
    assert create_response.status_code == 201
    assert fetch_response.status_code == 200
    assert fetch_response.json()["username"] == payload["username"]
    assert fetch_response.json()["withdrawable_balance"] == "0.00"


def test_list_transactions_for_user_returns_ledger_rows(
    client: TestClient,
    user_factory: UserFactory,
    transaction_factory: TransactionFactory,
) -> None:
    # Arrange
    user = user_factory(balance=Decimal("25.00"))
    transaction = transaction_factory(
        user=user,
        amount=Decimal("-10.00"),
        transaction_type=TransactionType.WITHDRAWAL,
        status=TransactionStatus.INITIATED,
        reference_id="dashboard-list",
    )

    # Act
    response = client.get(f"/api/v1/transactions/{user.id}")

    # Assert
    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == str(user.id)
    assert len(body["transactions"]) == 1
    assert body["transactions"][0]["id"] == str(transaction.id)
    assert body["transactions"][0]["amount"] == "-10.00"


def test_wallet_audit_endpoint_confirms_matching_ledger(
    client: TestClient,
    user_factory: UserFactory,
    transaction_factory: TransactionFactory,
) -> None:
    # Arrange
    user = user_factory(balance=Decimal("40.00"))
    transaction_factory(
        user=user,
        amount=Decimal("40.00"),
        transaction_type=TransactionType.FINAL_PAYOUT,
        status=TransactionStatus.SUCCESS,
    )

    # Act
    response = client.get(f"/api/v1/audit/wallet/{user.id}")

    # Assert
    assert response.status_code == 200
    assert response.json() == {
        "is_valid": True,
        "message": "Wallet balance matches the append-only ledger.",
    }


def test_wallet_audit_endpoint_reports_mismatch(
    client: TestClient,
    user_factory: UserFactory,
    transaction_factory: TransactionFactory,
) -> None:
    # Arrange
    user = user_factory(balance=Decimal("25.00"))
    transaction_factory(
        user=user,
        amount=Decimal("40.00"),
        transaction_type=TransactionType.FINAL_PAYOUT,
        status=TransactionStatus.SUCCESS,
    )

    # Act
    response = client.get(f"/api/v1/audit/wallet/{user.id}")

    # Assert
    assert response.status_code == 409
    assert "Critical wallet audit failed" in response.json()["detail"]


def test_create_sale_for_existing_user_returns_created_sale(
    client: TestClient,
    user_factory: UserFactory,
) -> None:
    # Arrange
    user = user_factory()
    sale_payload = {
        "user_id": str(user.id),
        "brand_name": "Acme",
        "earnings": "125.50",
    }

    # Act
    response = client.post("/api/v1/sales/", json=sale_payload)

    # Assert
    assert response.status_code == 201
    body = response.json()
    assert body["user_id"] == str(user.id)
    assert body["brand_name"] == sale_payload["brand_name"]
    assert body["status"] == "PENDING"
    assert body["earnings"] == sale_payload["earnings"]
    assert body["advance_paid"] == "0.00"
    assert body["is_advance_processed"] is False


def test_create_sale_for_missing_user_returns_not_found(client: TestClient) -> None:
    # Arrange
    sale_payload = {
        "user_id": "00000000-0000-0000-0000-000000000000",
        "brand_name": "Acme",
        "earnings": "10.00",
    }

    # Act
    response = client.post("/api/v1/sales/", json=sale_payload)

    # Assert
    assert response.status_code == 404
    assert response.json() == {"detail": "User not found."}


def test_list_sales_returns_only_requested_users_sales(
    client: TestClient,
    user_factory: UserFactory,
    sale_factory: SaleFactory,
) -> None:
    # Arrange
    user = user_factory(username="merchant")
    other_user = user_factory(username="other")
    sale_factory(user, earnings=Decimal("10.00"))
    sale_factory(other_user, earnings=Decimal("99.00"))

    # Act
    response = client.get(f"/api/v1/sales/{user.id}")

    # Assert
    assert response.status_code == 200
    body = response.json()
    assert body["user_id"] == str(user.id)
    assert len(body["sales"]) == 1
    assert body["sales"][0]["earnings"] == "10.00"


def test_reconciliation_approved_returns_final_payout_transaction(
    client: TestClient,
    db_session: Session,
    user_factory: UserFactory,
    sale_factory: SaleFactory,
) -> None:
    # Arrange
    starting_balance = Decimal("10.00")
    advance_paid = Decimal("10.00")
    expected_final_payout = Decimal("90.00")
    user = user_factory(balance=starting_balance)
    sale = sale_factory(
        user,
        earnings=Decimal("100.00"),
        advance_paid=advance_paid,
        is_advance_processed=True,
    )

    # Act
    response = client.post(f"/api/v1/reconciliation/{sale.id}", json={"status": "APPROVED"})

    # Assert
    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "FINAL_PAYOUT"
    assert body["amount"] == "90.00"
    db_session.refresh(user)
    assert user.withdrawable_balance == starting_balance + expected_final_payout


def test_advance_trigger_returns_processed_count(
    client: TestClient,
    db_session: Session,
    user_factory: UserFactory,
    sale_factory: SaleFactory,
) -> None:
    # Arrange
    earnings = Decimal("100.00")
    expected_advance = Decimal("10.00")
    user = user_factory(balance=Decimal("0.00"))
    sale_factory(user, earnings=earnings)

    # Act
    response = client.post("/api/v1/payouts/advance/trigger")

    # Assert
    assert response.status_code == 200
    assert response.json() == {"processed_count": 1}
    db_session.refresh(user)
    assert user.withdrawable_balance == expected_advance


def test_withdrawal_fails_if_within_24_hours(
    client: TestClient,
    user_factory: UserFactory,
) -> None:
    # Arrange
    user = user_factory(balance=Decimal("50.00"))
    first_withdrawal_payload = {"user_id": str(user.id), "amount": "25.00"}
    second_withdrawal_payload = {"user_id": str(user.id), "amount": "5.00"}

    # Act
    first_response = client.post("/api/v1/withdrawals/", json=first_withdrawal_payload)
    second_response = client.post("/api/v1/withdrawals/", json=second_withdrawal_payload)

    # Assert
    assert first_response.status_code == 202
    assert second_response.status_code == 429
    assert second_response.json() == {
        "detail": "Withdrawals are limited to once every 24 hours."
    }


def test_failed_withdrawal_webhook_credits_exact_amount_and_updates_ledger(
    client: TestClient,
    db_session: Session,
    user_factory: UserFactory,
    transaction_factory: TransactionFactory,
) -> None:
    # Arrange
    starting_balance = Decimal("20.00")
    withdrawal_amount = Decimal("15.00")
    user = user_factory(balance=starting_balance - withdrawal_amount)
    withdrawal = transaction_factory(
        user=user,
        amount=-withdrawal_amount,
        transaction_type=TransactionType.WITHDRAWAL,
        status=TransactionStatus.INITIATED,
        reference_id="gateway-failed",
    )

    # Act
    response = client.post(
        "/api/v1/webhooks/withdrawals/failed",
        json={"transaction_id": str(withdrawal.id)},
    )

    # Assert
    assert response.status_code == 200
    body = response.json()["recovery_transaction"]
    assert body["type"] == "FAILED_RECOVERY"
    assert body["amount"] == "15.00"
    db_session.refresh(user)
    db_session.refresh(withdrawal)
    assert user.withdrawable_balance == starting_balance
    assert withdrawal.status == TransactionStatus.FAILED
