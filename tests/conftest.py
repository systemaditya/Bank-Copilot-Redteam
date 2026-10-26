from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from app.config import PROJECT_ROOT, Settings
from app.db import (
    Account,
    Customer,
    InboundEmail,
    Staff,
    init_db,
    make_engine,
    make_session_factory,
)
from app.rag import HashingEmbedder, PolicyRetriever, load_chunks
from app.seed import seed_database
from app.tools import ToolContext, customer_registry, staff_registry

POLICY_DOCS = PROJECT_ROOT / "data" / "policy_docs"


@pytest.fixture
def settings() -> Settings:
    # Offline everything: hashing embeddings instead of a model, no audit file.
    return Settings(
        _env_file=None,
        database_url="sqlite://",
        policy_docs_dir=POLICY_DOCS,
        embedding_backend="hashing",
        max_tool_rounds=3,
        audit_enabled=False,
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
def retriever() -> PolicyRetriever:
    return PolicyRetriever(load_chunks(POLICY_DOCS), HashingEmbedder())


@pytest.fixture
def registry(retriever: PolicyRetriever):
    return customer_registry(retriever)


@pytest.fixture
def staff_tools(retriever: PolicyRetriever):
    return staff_registry(retriever)


@pytest.fixture
def alice(customers: list[Customer]) -> Customer:
    return customers[0]


@pytest.fixture
def bob(customers: list[Customer]) -> Customer:
    return customers[1]


@pytest.fixture
def alice_ctx(db: Session, alice: Customer) -> ToolContext:
    return ToolContext(db=db, customer_id=alice.id, actor=f"customer:{alice.customer_number}")


@pytest.fixture
def agent_staff(db: Session) -> Staff:
    return db.scalars(select(Staff).order_by(Staff.id)).first()


@pytest.fixture
def benign_email(db: Session) -> InboundEmail:
    return db.scalars(
        select(InboundEmail).where(InboundEmail.label == "benign").order_by(InboundEmail.id)
    ).first()


def chequing(customer: Customer) -> Account:
    return next(a for a in customer.accounts if a.account_type == "chequing")
