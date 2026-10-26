from sqlalchemy import select

from app.db import Account, Customer, init_db, make_engine, make_session_factory
from app.seed import fake_sin, luhn_valid, seed_database


def _snapshot(seed: int) -> list[tuple]:
    engine = make_engine("sqlite://")
    init_db(engine)
    with make_session_factory(engine)() as db:
        seed_database(db, n_customers=5, seed=seed)
        rows = db.execute(
            select(
                Customer.customer_number,
                Customer.first_name,
                Customer.sin,
                Account.account_number,
                Account.balance_cents,
            )
            .join(Account)
            .order_by(Account.account_number)
        ).all()
    engine.dispose()
    return [tuple(row) for row in rows]


def test_same_seed_gives_identical_data():
    assert _snapshot(7) == _snapshot(7)


def test_different_seed_gives_different_data():
    assert _snapshot(7) != _snapshot(8)


def test_every_customer_has_a_chequing_account(customers):
    assert len(customers) == 5
    for customer in customers:
        assert any(a.account_type == "chequing" for a in customer.accounts)


def test_balances_match_transaction_history_and_never_go_negative(db):
    for account in db.scalars(select(Account)):
        running = 0
        for txn in account.transactions:  # ordered by posted_at
            running += txn.amount_cents
            assert running >= 0, f"{account.account_number} overdrew at {txn.posted_at}"
        assert running == account.balance_cents


def test_contact_details_use_reserved_fictional_ranges(customers):
    for customer in customers:
        assert customer.email.endswith("@example.com")
        assert "-555-01" in customer.phone


def test_synthetic_sins_are_luhn_valid(customers):
    for customer in customers:
        assert len(customer.sin) == 11
        assert luhn_valid(customer.sin)


def test_staff_are_seeded(db):
    from app.db import Staff

    numbers = db.scalars(select(Staff.staff_number).order_by(Staff.id)).all()
    assert numbers == ["S100", "S101", "S102"]


def test_customer_emails_come_from_customer_addresses(db):
    from app.db import InboundEmail

    benign = db.scalars(select(InboundEmail).where(InboundEmail.label == "benign")).all()
    assert benign
    for email in benign:
        assert email.customer_id is not None
        assert db.get(Customer, email.customer_id).email == email.from_address
        assert email.expected_category
        assert email.status == "new"


def test_injection_samples_are_loaded_and_labelled(db):
    from app.db import InboundEmail

    attacks = db.scalars(select(InboundEmail).where(InboundEmail.label != "benign")).all()
    assert {email.label for email in attacks} == {"injection", "social_engineering"}
    assert len(attacks) == 4
    external = [email for email in attacks if email.customer_id is None]
    assert [email.from_address for email in external] == ["offers@example.org"]


def test_luhn_helpers():
    import random

    rng = random.Random(0)
    for _ in range(100):
        assert luhn_valid(fake_sin(rng))
    assert not luhn_valid("046 454 287")  # known-bad check digit
