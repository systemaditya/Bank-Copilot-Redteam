"""Database plumbing: URL handling, the seed CLI, and limits that Postgres enforces."""

import pytest
from sqlalchemy import func, select

from app.db import Customer, make_engine, make_session_factory, normalise_url
from app.seed import main as seed_main
from tests.conftest import chequing


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("postgresql://u:p@host:5432/bank", "postgresql+psycopg://u:p@host:5432/bank"),
        ("postgres://u:p@host/bank", "postgresql+psycopg://u:p@host/bank"),
        ("postgresql+psycopg://u:p@host/bank", "postgresql+psycopg://u:p@host/bank"),
        ("sqlite:///./bank.db", "sqlite:///./bank.db"),
    ],
)
def test_normalise_url(url, expected):
    assert normalise_url(url) == expected


def test_seed_cli_if_empty_leaves_existing_data_alone(tmp_path, capsys):
    url = f"sqlite:///{(tmp_path / 'bank.db').as_posix()}"
    seed_main(["--database-url", url, "--customers", "3", "--if-empty"])
    seed_main(["--database-url", url, "--customers", "9", "--if-empty"])
    assert "leaving it as it is" in capsys.readouterr().out

    engine = make_engine(url)
    with make_session_factory(engine)() as db:
        assert db.scalar(select(func.count()).select_from(Customer)) == 3
    engine.dispose()


def test_seed_cli_refuses_to_reseed_without_a_flag(tmp_path):
    url = f"sqlite:///{(tmp_path / 'bank.db').as_posix()}"
    seed_main(["--database-url", url, "--customers", "2"])
    with pytest.raises(SystemExit):
        seed_main(["--database-url", url, "--customers", "2"])


def test_reset_and_if_empty_cannot_be_combined(tmp_path):
    url = f"sqlite:///{(tmp_path / 'bank.db').as_posix()}"
    with pytest.raises(SystemExit):
        seed_main(["--database-url", url, "--reset", "--if-empty"])


def test_balances_beyond_32_bit_integers_are_stored(db, alice):
    # 50 million dollars in cents is past the 32-bit INTEGER limit; BIGINT columns hold it.
    account = chequing(alice)
    account.balance_cents = 5_000_000_000
    db.commit()
    db.expire_all()
    assert chequing(alice).balance_cents == 5_000_000_000


def test_overlong_destination_account_is_a_tool_error_not_a_crash(registry, alice_ctx, db, alice):
    source = chequing(alice)
    source.balance_cents = 10_000
    db.commit()
    result = registry.call(
        alice_ctx,
        "initiate_transfer",
        {
            "from_account_number": source.account_number,
            "to_account_number": "9" * 21,
            "amount": 1,
        },
    )
    assert "at most 20 characters" in result["error"]
