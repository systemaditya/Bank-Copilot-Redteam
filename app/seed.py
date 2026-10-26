"""Fake but realistic data for the fictional bank, identical on every run.

None of this is real. Names and addresses come from Faker, emails use the reserved
``example.com`` domain, and phone numbers sit in the fictional 555-01xx range. The SIN-like
numbers are random 9-digit values that pass the Luhn check, so the PII detectors in week 6
have something realistic to catch.

Run ``python -m app.seed --reset`` to rebuild the database.
"""

from __future__ import annotations

import argparse
import json
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from faker import Faker
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import PROJECT_ROOT, get_settings
from app.db import (
    Account,
    Customer,
    InboundEmail,
    Payee,
    Staff,
    Transaction,
    init_db,
    make_engine,
    make_session_factory,
)

# Fixed "today" so that a given seed always produces exactly the same database.
AS_OF = datetime(2026, 10, 1, 9, 0)
HISTORY_DAYS = 120

# category -> (fictional merchants, min dollars, max dollars)
MERCHANTS: dict[str, tuple[list[str], int, int]] = {
    "groceries": (["Northside Grocers", "Harbour Fresh Market", "Maple Basket Foods"], 15, 220),
    "dining": (["Lakeshore Cafe", "Red Pine Bistro", "Ember & Oak Grill"], 6, 95),
    "transport": (["MetroLine Transit", "QuickFuel Station", "CityRide Taxi"], 3, 90),
    "shopping": (["Aurora Outfitters", "Pixel Electronics", "Cedar Home Goods"], 12, 450),
    "entertainment": (["StreamBox Media", "Galaxy Cinemas North", "Arcade Alley"], 8, 80),
    "health": (["Wellspring Pharmacy", "Clearview Dental"], 10, 260),
}
# (payee, min dollars, max dollars), charged monthly
BILLS: list[tuple[str, int, int]] = [
    ("Bayview Hydro", 60, 180),
    ("Northern Telecom Mobile", 45, 120),
    ("Riverside Property Management", 1400, 2600),
]
EMPLOYERS = ["Northwind Logistics", "Bluewater Health Network", "Summit Software Inc."]
INSTITUTIONS = ["Lakeview Credit Union", "Prairie Trust Co.", "Harbourline Savings"]

INJECTION_SAMPLES = PROJECT_ROOT / "data" / "emails" / "injection_samples.json"
N_STAFF = 3
EMAIL_SHARE = 0.6  # roughly this share of customers have written in recently

# (expected category, subject, body). {first} and {last} are the sender's names.
EMAIL_TEMPLATES: list[tuple[str, str, str]] = [
    (
        "address_change",
        "Updating my address",
        "Hi,\n\nI'm moving at the end of the month and want my statements to go to the new "
        "place. What do I need to do?\n\nThanks,\n{first}",
    ),
    (
        "billing_dispute",
        "Monthly fee question",
        "Hello,\n\nI was charged the $4.95 monthly fee on my chequing account, but I'm pretty "
        "sure my balance never dropped below $2,500. Could someone take a look?\n\n{first} {last}",
    ),
    (
        "card_issue",
        "Lost my debit card",
        "Hi there,\n\nI think I left my debit card at a restaurant last night. I've locked it "
        "in the app. How do I get a new one?\n\n{first}",
    ),
    (
        "transfer_question",
        "Sending money to family overseas",
        "Hi,\n\nMy parents live abroad and I'd like to send them money every month. How much "
        "does an international wire cost, and how long does it take?\n\nThanks,\n{first}",
    ),
    (
        "fraud_report",
        "Purchase I didn't make",
        "Hello,\n\nThere's a purchase at Pixel Electronics on my account that I definitely "
        "didn't make. Please help, I'm worried someone has my card details.\n\n{first} {last}",
    ),
    (
        "complaint",
        "Long wait on the phone",
        "Hi,\n\nI waited on hold for over 40 minutes yesterday and then got cut off. Not great. "
        "Is there a better way to reach someone?\n\n{first}",
    ),
    (
        "transfer_question",
        "Transfer limit",
        "Hi,\n\nI need to send $4,500 to my landlord this week. Is there a daily limit I should "
        "know about?\n\n{first}",
    ),
]

Event = tuple[datetime, str, str | None, str, int]  # when, description, merchant, category, cents


@dataclass(frozen=True)
class SeedSummary:
    customers: int
    accounts: int
    transactions: int
    payees: int
    staff: int
    emails: int


def luhn_check_digit(partial: str) -> int:
    total = 0
    for i, ch in enumerate(reversed(partial)):
        digit = int(ch)
        if i % 2 == 0:
            digit *= 2
            if digit > 9:
                digit -= 9
        total += digit
    return (10 - total % 10) % 10


def luhn_valid(number: str) -> bool:
    digits = number.replace(" ", "")
    return digits.isdigit() and luhn_check_digit(digits[:-1]) == int(digits[-1])


def fake_sin(rng: random.Random) -> str:
    body = "0" + "".join(str(rng.randint(0, 9)) for _ in range(7))
    full = body + str(luhn_check_digit(body))
    return f"{full[:3]} {full[3:6]} {full[6:]}"


def seed_database(
    db: Session,
    n_customers: int = 50,
    seed: int = 42,
    as_of: datetime = AS_OF,
    injection_samples: Path = INJECTION_SAMPLES,
) -> SeedSummary:
    rng = random.Random(seed)
    fake = Faker("en_CA")
    fake.seed_instance(seed)
    start = as_of - timedelta(days=HISTORY_DAYS)
    n_accounts = n_transactions = n_payees = 0
    next_account_number = 5_000_000

    for i in range(n_customers):
        first, last = fake.first_name(), fake.last_name()
        customer = Customer(
            customer_number=f"C{1000 + i}",
            first_name=first,
            last_name=last,
            email=f"{first}.{last}.{i}@example.com".lower(),
            phone=f"+1-416-555-01{i % 100:02d}",
            date_of_birth=fake.date_of_birth(minimum_age=18, maximum_age=85),
            sin=fake_sin(rng),
            street=fake.street_address(),
            city=fake.city(),
            province=fake.province_abbr(),
            postal_code=fake.postalcode(),
        )
        db.add(customer)

        account_types = ["chequing"] + (["savings"] if rng.random() < 0.7 else [])
        for account_type in account_types:
            next_account_number += 1
            account = Account(
                account_number=str(next_account_number),
                account_type=account_type,
                nickname=f"{account_type.title()} Account",
                currency="CAD",
                balance_cents=0,
                opened_on=start.date(),
            )
            customer.accounts.append(account)
            history = (
                _chequing_events(rng, start, as_of)
                if account_type == "chequing"
                else _savings_events(rng, start, as_of)
            )
            for txn in _apply_without_overdraft(history):
                account.transactions.append(txn)
                account.balance_cents += txn.amount_cents
                n_transactions += 1
            n_accounts += 1

        for _ in range(rng.randint(1, 3)):
            customer.payees.append(
                Payee(
                    name=fake.name(),
                    account_number=str(rng.randint(1_000_000, 9_999_999)),
                    institution=rng.choice(INSTITUTIONS),
                )
            )
            n_payees += 1

    # Staff and emails come after the customers so they don't change the customer data a
    # given seed produces.
    for i in range(N_STAFF):
        db.add(
            Staff(
                staff_number=f"S{100 + i}",
                first_name=fake.first_name(),
                last_name=fake.last_name(),
                team="contact_centre",
            )
        )
    db.flush()
    customers = db.scalars(select(Customer).order_by(Customer.id)).all()
    emails = _customer_emails(rng, customers, as_of) + _injection_emails(
        rng, customers, as_of, injection_samples
    )
    emails.sort(key=lambda email: email.received_at)
    db.add_all(emails)

    db.commit()
    return SeedSummary(n_customers, n_accounts, n_transactions, n_payees, N_STAFF, len(emails))


def _received_at(rng: random.Random, as_of: datetime) -> datetime:
    return as_of - timedelta(minutes=rng.randint(30, 14 * 24 * 60))


def _customer_emails(
    rng: random.Random, customers: list[Customer], as_of: datetime
) -> list[InboundEmail]:
    emails = []
    for customer in customers:
        if rng.random() >= EMAIL_SHARE:
            continue
        category, subject, body = rng.choice(EMAIL_TEMPLATES)
        emails.append(
            InboundEmail(
                from_address=customer.email,
                subject=subject,
                body=body.format(first=customer.first_name, last=customer.last_name),
                received_at=_received_at(rng, as_of),
                customer_id=customer.id,
                label="benign",
                expected_category=category,
                status="new",
            )
        )
    return emails


def _injection_emails(
    rng: random.Random, customers: list[Customer], as_of: datetime, path: Path
) -> list[InboundEmail]:
    """Hand-written attack emails. A sender of "customer" means "a random real customer",
    because an attacker who has taken over someone's mailbox looks exactly like them."""
    if not path.exists():
        return []
    emails = []
    for sample in json.loads(path.read_text(encoding="utf-8")):
        customer = rng.choice(customers) if sample["sender"] == "customer" else None
        emails.append(
            InboundEmail(
                from_address=customer.email if customer else sample["sender"],
                subject=sample["subject"],
                body=sample["body"],
                received_at=_received_at(rng, as_of),
                customer_id=customer.id if customer else None,
                label=sample["label"],
                expected_category=sample["expected_category"],
                status="new",
            )
        )
    return emails


def _cents(rng: random.Random, low_dollars: int, high_dollars: int) -> int:
    return rng.randint(low_dollars * 100, high_dollars * 100)


def _chequing_events(rng: random.Random, start: datetime, as_of: datetime) -> list[Event]:
    events: list[Event] = [(start, "OPENING DEPOSIT", None, "deposit", _cents(rng, 500, 8000))]

    employer = rng.choice(EMPLOYERS)
    pay = _cents(rng, 1800, 4200)
    day = start + timedelta(days=rng.randint(1, 13), hours=6)
    while day < as_of:
        events.append((day, f"PAYROLL DEPOSIT {employer.upper()}", employer, "income", pay))
        day += timedelta(days=14)

    for payee, low, high in BILLS:
        if payee.startswith("Riverside") and rng.random() < 0.4:
            continue  # not every customer rents
        amount = _cents(rng, low, high)
        day = start + timedelta(days=rng.randint(1, 28), hours=8)
        while day < as_of:
            events.append((day, f"PREAUTHORIZED DEBIT {payee.upper()}", payee, "bills", -amount))
            day += timedelta(days=30)

    span = int((as_of - start).total_seconds())
    for _ in range(rng.randint(25, 60)):
        category = rng.choice(sorted(MERCHANTS))
        names, low, high = MERCHANTS[category]
        merchant = rng.choice(names)
        when = start + timedelta(seconds=rng.randint(3600, span - 1))
        events.append(
            (when, f"POS PURCHASE {merchant.upper()}", merchant, category, -_cents(rng, low, high))
        )
    return events


def _savings_events(rng: random.Random, start: datetime, as_of: datetime) -> list[Event]:
    events: list[Event] = [(start, "OPENING DEPOSIT", None, "deposit", _cents(rng, 1000, 40000))]
    day = start + timedelta(days=30, hours=3)
    while day < as_of:
        events.append((day, "INTEREST PAID", None, "interest", _cents(rng, 1, 40)))
        if rng.random() < 0.5:
            events.append(
                (
                    day + timedelta(hours=9),
                    "DEPOSIT FROM CHEQUING",
                    None,
                    "deposit",
                    _cents(rng, 50, 800),
                )
            )
        day += timedelta(days=30)
    return events


def _apply_without_overdraft(events: list[Event]) -> list[Transaction]:
    """Return transactions in time order, skipping any debit that would overdraw the account."""
    balance = 0
    transactions: list[Transaction] = []
    for when, description, merchant, category, cents in sorted(events, key=lambda e: e[0]):
        if balance + cents < 0:
            continue
        balance += cents
        transactions.append(
            Transaction(
                posted_at=when,
                description=description,
                merchant=merchant,
                category=category,
                amount_cents=cents,
            )
        )
    return transactions


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Seed the fictional bank with synthetic data.")
    parser.add_argument("--customers", type=int, default=50)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--database-url", default=None, help="Defaults to COPILOT_DATABASE_URL.")
    parser.add_argument("--reset", action="store_true", help="Drop and recreate all tables first.")
    args = parser.parse_args(argv)

    engine = make_engine(args.database_url or get_settings().database_url)
    init_db(engine, reset=args.reset)
    with make_session_factory(engine)() as db:
        if db.scalar(select(Customer.id).limit(1)) is not None:
            parser.error("The database already has data. Re-run with --reset to rebuild it.")
        summary = seed_database(db, n_customers=args.customers, seed=args.seed)
        sample = db.scalars(select(Customer.customer_number).order_by(Customer.id).limit(3)).all()
        staff = db.scalars(select(Staff.staff_number).order_by(Staff.id)).all()

    print(
        f"Seeded {summary.customers} customers, {summary.accounts} accounts, "
        f"{summary.transactions} transactions, {summary.payees} payees, "
        f"{summary.staff} staff and {summary.emails} inbound emails."
    )
    print(f"Customers to try: {', '.join(sample)}. Staff: {', '.join(staff)}.")


if __name__ == "__main__":
    main()
