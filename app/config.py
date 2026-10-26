"""Runtime settings, read from environment variables prefixed ``COPILOT_`` or a ``.env`` file."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="COPILOT_", env_file=".env", extra="ignore")

    bank_name: str = "Maple Ledger Bank"
    database_url: str = "sqlite:///./bank.db"
    policy_docs_dir: Path = PROJECT_ROOT / "data" / "policy_docs"

    llm_backend: str = "ollama"
    ollama_url: str = "http://localhost:11434"
    model: str = "llama3.1:8b"
    temperature: float = 0.0
    request_timeout_s: float = 120.0

    max_tool_rounds: int = 5
    daily_transfer_limit_cad: int = 3000
    # Return the tool-call trace in /chat responses. Useful in the lab for scoring attacks;
    # a production assistant would not expose it to customers.
    return_trace: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
