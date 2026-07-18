from collections.abc import Callable, Generator
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.database import get_db
from app.main import app
from app.models import Base, Sale, Transaction, TransactionStatus, TransactionType, User

SessionFactory = sessionmaker[Session]
UserFactory = Callable[..., User]
SaleFactory = Callable[..., Sale]
TransactionFactory = Callable[..., Transaction]


@pytest.fixture()
def test_engine(tmp_path) -> Generator[Engine, None, None]:
    database_path = tmp_path / "payout_test.db"
    engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)

    yield engine

    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture()
def session_factory(test_engine: Engine) -> SessionFactory:
    return sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


@pytest.fixture()
def db_session(session_factory: SessionFactory) -> Generator[Session, None, None]:
    with session_factory() as session:
        yield session
        session.rollback()


@pytest.fixture()
def client(session_factory: SessionFactory) -> Generator[TestClient, None, None]:
    def override_get_db() -> Generator[Session, None, None]:
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture()
def user_factory(db_session: Session) -> UserFactory:
    def create_user(username: str = "merchant", balance: Decimal = Decimal("0.00")) -> User:
        user = User(username=username, withdrawable_balance=balance)
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
        return user

    return create_user


@pytest.fixture()
def sale_factory(db_session: Session) -> SaleFactory:
    def create_sale(
        user: User,
        earnings: Decimal = Decimal("100.00"),
        brand_name: str = "Acme",
        advance_paid: Decimal = Decimal("0.00"),
        is_advance_processed: bool = False,
    ) -> Sale:
        sale = Sale(
            user_id=user.id,
            brand_name=brand_name,
            earnings=earnings,
            advance_paid=advance_paid,
            is_advance_processed=is_advance_processed,
        )
        db_session.add(sale)
        db_session.commit()
        db_session.refresh(sale)
        return sale

    return create_sale


@pytest.fixture()
def transaction_factory(db_session: Session) -> TransactionFactory:
    def create_transaction(
        user: User,
        amount: Decimal,
        transaction_type: TransactionType = TransactionType.WITHDRAWAL,
        status: TransactionStatus = TransactionStatus.INITIATED,
        reference_id: str | None = None,
    ) -> Transaction:
        transaction = Transaction(
            user_id=user.id,
            type=transaction_type,
            amount=amount,
            status=status,
            reference_id=reference_id,
        )
        db_session.add(transaction)
        db_session.commit()
        db_session.refresh(transaction)
        return transaction

    return create_transaction


@pytest.fixture()
def test_user(user_factory: UserFactory) -> User:
    return user_factory(username="merchant", balance=Decimal("0.00"))


@pytest.fixture()
def pending_sale(test_user: User, sale_factory: SaleFactory) -> Sale:
    return sale_factory(test_user, earnings=Decimal("100.00"))
