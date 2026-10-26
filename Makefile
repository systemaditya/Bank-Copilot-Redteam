PY ?= python

.PHONY: setup seed run chat test lint format check

setup:
	$(PY) -m pip install -e ".[dev]"

seed:
	$(PY) -m app.seed --reset

run:
	$(PY) -m uvicorn --factory app.main:create_app --reload

chat:
	$(PY) -m app.cli_chat --customer C1000

test:
	$(PY) -m pytest

lint:
	$(PY) -m ruff check .
	$(PY) -m ruff format --check .

format:
	$(PY) -m ruff format .
	$(PY) -m ruff check --fix .

check: lint test
