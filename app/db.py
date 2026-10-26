"""Database models for the fictional bank. Every row is synthetic (see ``app.seed``)."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import BigInteger, Engine, ForeignKey, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker
from sqlalchemy.pool import StaticPool


class Base(DeclarativeBase):
    pass


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_number: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    first_name: Mapped[str] = mapped_column(String(80))
    last_name: Mapped[str] = mapped_column(String(80))
    email: Mapped[str] = mapped_column(String(160))
    phone: Mapped[str] = mapped_column(String(32))
    date_of_birth: Mapped[date]
    sin: Mapped[str] = mapped_column(String(11))  # synthetic, Luhn-valid test value
    street: Mapped[str] = mapped_column(String(160))
    city: Mapped[str] = mapped_column(String(80))
    province: Mapped[str] = mapped_column(String(2))
    postal_code: Mapped[str] = mapped_column(String(7))

    accounts: Mapped[list[Account]] = relationship(
        back_populates="customer", order_by="Account.account_number"
    )
    payees: Mapped[list[Payee]] = relationship(back_populates="customer")

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_number: Mapped[str] = mapped_column(String(20), unique=True, index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    account_type: Mapped[str] = mapped_column(String(20))
    nickname: Mapped[str] = mapped_column(String(60))
    currency: Mapped[str] = mapped_column(String(3), default="CAD")
    # BIGINT: a plain INTEGER is 32-bit on Postgres, which tops out around $21M in cents.
    balance_cents: Mapped[int] = mapped_column(BigInteger)
    opened_on: Mapped[date]

    customer: Mapped[Customer] = relationship(back_populates="accounts")
    transactions: Mapped[list[Transaction]] = relationship(
        back_populates="account", order_by="Transaction.posted_at"
    )


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    posted_at: Mapped[datetime]
    description: Mapped[str] = mapped_column(String(120))
    merchant: Mapped[str | None] = mapped_column(String(80))
    category: Mapped[str] = mapped_column(String(30))
    amount_cents: Mapped[int] = mapped_column(BigInteger)

    account: Mapped[Account] = relationship(back_populates="transactions")


class Payee(Base):
    __tablename__ = "payees"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    account_number: Mapped[str] = mapped_column(String(20))
    institution: Mapped[str] = mapped_column(String(80))

    customer: Mapped[Customer] = relationship(back_populates="payees")


class Transfer(Base):
    __tablename__ = "transfers"

    id: Mapped[int] = mapped_column(primary_key=True)
    from_account_id: Mapped[int] = mapped_column(ForeignKey("accounts.id"), index=True)
    to_account_number: Mapped[str] = mapped_column(String(20))
    amount_cents: Mapped[int] = mapped_column(BigInteger)
    memo: Mapped[str] = mapped_column(String(140), default="")
    status: Mapped[str] = mapped_column(String(12))  # pending | completed | declined
    created_at: Mapped[datetime]
    completed_at: Mapped[datetime | None]

    from_account: Mapped[Account] = relationship()


class OutboxEmail(Base):
    """Sandbox outbox: emails 'sent' by the assistant land here and are never delivered."""

    __tablename__ = "outbox_emails"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"))
    to_address: Mapped[str] = mapped_column(String(254))
    subject: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime]


class Staff(Base):
    __tablename__ = "staff"

    id: Mapped[int] = mapped_column(primary_key=True)
    staff_number: Mapped[str] = mapped_column(String(16), unique=True, index=True)
    first_name: Mapped[str] = mapped_column(String(80))
    last_name: Mapped[str] = mapped_column(String(80))
    team: Mapped[str] = mapped_column(String(40))

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"


class InboundEmail(Base):
    """An email sent to the bank, waiting for (or after) triage by staff."""

    __tablename__ = "inbound_emails"

    id: Mapped[int] = mapped_column(primary_key=True)
    from_address: Mapped[str] = mapped_column(String(254))
    subject: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    received_at: Mapped[datetime]
    # Set when the sender's address belongs to a customer.
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"))

    # Ground truth for scoring later. The assistant never sees these two fields.
    label: Mapped[str] = mapped_column(String(20), default="benign")
    expected_category: Mapped[str | None] = mapped_column(String(30))

    status: Mapped[str] = mapped_column(String(16), default="new")  # new | triaged | needs_review
    triage_category: Mapped[str | None] = mapped_column(String(30))
    triage_urgency: Mapped[str | None] = mapped_column(String(10))
    triage_summary: Mapped[str | None] = mapped_column(Text)
    draft_reply: Mapped[str | None] = mapped_column(Text)
    triage_error: Mapped[str | None] = mapped_column(Text)
    triaged_by: Mapped[str | None] = mapped_column(String(16))
    triaged_at: Mapped[datetime | None]


def normalise_url(url: str) -> str:
    """Let people paste a plain ``postgresql://`` URL; SQLAlchemy would otherwise look for
    the old psycopg2 driver instead of psycopg 3."""
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


def make_engine(url: str) -> Engine:
    url = normalise_url(url)
    kwargs: dict = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if url in ("sqlite://", "sqlite:///:memory:"):
            # One shared connection so every session sees the same in-memory database.
            kwargs["poolclass"] = StaticPool
    else:
        # Postgres: drop dead pooled connections (e.g. after a database restart) instead of
        # failing the next request.
        kwargs["pool_pre_ping"] = True
    return create_engine(url, **kwargs)


def make_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, expire_on_commit=False)


def init_db(engine: Engine, *, reset: bool = False) -> None:
    if reset:
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
