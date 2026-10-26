from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.config import PROJECT_ROOT, Settings
from app.db import Account, Customer, init_db, make_engine, make_session_factory
from app.seed import seed_database
from app.tools import ToolContext, default_registry


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        database_url="sqlite://",
        policy_docs_dir=PROJECT_ROOT / "data" / "policy_docs",
        max_tool_rounds=3,
    )


@pytest.fixture
def engine() -> Iterator[Engine]:
    eng = make_engine("sqlite://")
    init_db(eng)
    with make_session_factory(eng)() as db:
        seed_database(db, n_customers=5, seed=7)
    yield eng
    eng.dispose()


@pytest.fixture
def db(engine: Engine) -> Iterator[Session]:
    with make_session_factory(engine)() as session:
        yield session


@pytest.fixture
def customers(db: Session) -> list[Customer]:
    return list(db.scalars(select(Customer).order_by(Customer.id)))


@pytest.fixture
def registry(settings: Settings):
    return default_registry(settings.policy_docs_dir)


@pytest.fixture
def alice(customers: list[Customer]) -> Customer:
    return customers[0]


@pytest.fixture
def bob(customers: list[Customer]) -> Customer:
    return customers[1]


@pytest.fixture
def alice_ctx(db: Session, alice: Customer) -> ToolContext:
    return ToolContext(db=db, customer_id=alice.id)


def chequing(customer: Customer) -> Account:
    return next(a for a in customer.accounts if a.account_type == "chequing")
