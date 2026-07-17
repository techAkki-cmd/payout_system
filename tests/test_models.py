from decimal import Decimal

from sqlalchemy import Numeric
from sqlalchemy.orm import configure_mappers

from app.models import Base, Sale, SaleStatus, Transaction, TransactionStatus, TransactionType, User


def test_models_are_registered_in_metadata() -> None:
    assert {"users", "sales", "transactions"}.issubset(Base.metadata.tables.keys())


def test_relationships_configure_without_mapper_errors() -> None:
    configure_mappers()

    assert User.sales.property.back_populates == "user"
    assert User.transactions.property.back_populates == "user"
    assert Sale.transactions.property.back_populates == "sale"
    assert Transaction.sale.property.back_populates == "transactions"


def test_money_columns_use_fixed_precision_numeric() -> None:
    money_columns = [
        User.__table__.c.withdrawable_balance,
        Sale.__table__.c.earnings,
        Sale.__table__.c.advance_paid,
        Transaction.__table__.c.amount,
    ]

    for column in money_columns:
        assert isinstance(column.type, Numeric)
        assert column.type.precision == 10
        assert column.type.scale == 2


def test_enum_and_default_configuration() -> None:
    assert Sale.status.property.columns[0].default.arg == SaleStatus.PENDING
    assert Sale.__table__.c.status.server_default.arg == SaleStatus.PENDING.value
    assert Sale.__table__.c.advance_paid.default.arg == Decimal("0.00")
    assert User.__table__.c.withdrawable_balance.default.arg == Decimal("0.00")

    assert {item.value for item in SaleStatus} == {"PENDING", "APPROVED", "REJECTED"}
    assert {item.value for item in TransactionType} == {
        "ADVANCE_PAYOUT",
        "FINAL_PAYOUT",
        "RECONCILIATION_ADJUSTMENT",
        "WITHDRAWAL",
        "FAILED_RECOVERY",
    }
    assert {item.value for item in TransactionStatus} == {"INITIATED", "SUCCESS", "FAILED"}


def test_sales_worker_indexes_exist() -> None:
    index_columns = {
        tuple(column.name for column in index.columns) for index in Sale.__table__.indexes
    }

    assert ("status",) in index_columns
    assert ("is_advance_processed",) in index_columns
