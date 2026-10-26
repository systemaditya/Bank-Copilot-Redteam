FROM python:3.12-slim

WORKDIR /srv
COPY pyproject.toml README.md ./
COPY app ./app
COPY data ./data
RUN pip install --no-cache-dir . && mkdir -p /srv/state

ENV COPILOT_DATABASE_URL=sqlite:////srv/state/bank.db \
    COPILOT_POLICY_DOCS_DIR=/srv/data/policy_docs

EXPOSE 8000
# The lab database is rebuilt from the fixed seed on every start, so runs are reproducible.
CMD ["sh", "-c", "python -m app.seed --reset && uvicorn --factory app.main:create_app --host 0.0.0.0 --port 8000"]
