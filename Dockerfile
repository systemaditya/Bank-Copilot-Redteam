FROM python:3.12-slim

WORKDIR /srv
COPY pyproject.toml README.md ./
COPY app ./app
COPY data ./data
RUN pip install --no-cache-dir ".[postgres]" && mkdir -p /srv/state

# SQLite by default so the image runs on its own. docker-compose.yml points it at Postgres.
ENV COPILOT_DATABASE_URL=sqlite:////srv/state/bank.db \
    COPILOT_POLICY_DOCS_DIR=/srv/data/policy_docs \
    COPILOT_AUDIT_LOG_PATH=/srv/state/audit.jsonl

EXPOSE 8000
# Seed the fixed synthetic data on first start; later starts keep whatever is in the database.
CMD ["sh", "-c", "python -m app.seed --if-empty && uvicorn --factory app.main:create_app --host 0.0.0.0 --port 8000"]
