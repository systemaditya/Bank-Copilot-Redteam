"""Database models for the fictional bank. Every row is synthetic (see ``app.seed``)."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Engine, ForeignKey, String, Text, create_engine
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
    balance_cents: Mapped[int]
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
    amount_cents: Mapped[int]

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
    amount_cents: Mapped[int]
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


def make_engine(url: str) -> Engine:
    kwargs: dict = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if url in ("sqlite://", "sqlite:///:memory:"):
            # One shared connection so every session sees the same in-memory database.
            kwargs["poolclass"] = StaticPool
    return create_engine(url, **kwargs)


def make_session_factory(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, expire_on_commit=False)


def init_db(engine: Engine, *, reset: bool = False) -> None:
    if reset:
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
