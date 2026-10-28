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
    # Small enough to run on a laptop CPU. On a GPU, llama3.1:8b is a closer match to what a
    # bank would actually deploy.
    model: str = "llama3.2:3b"
    temperature: float = 0.0
    request_timeout_s: float = 120.0

    # "ollama" for real retrieval; "hashing" is a lexical fallback that needs no model.
    embedding_backend: str = "ollama"
    embedding_model: str = "nomic-embed-text"
    rag_top_k: int = 3
    rag_min_score: float = 0.0

    max_tool_rounds: int = 5
    daily_transfer_limit_cad: int = 3000
    # Return the tool-call trace in API responses. The attack scoring needs it; a real
    # assistant wouldn't show it to customers.
    return_trace: bool = True

    audit_enabled: bool = True
    audit_log_path: Path = Path("logs") / "audit.jsonl"
    audit_redact_pii: bool = True

    # The security controls. On by default; set COPILOT_DEFENSES_ENABLED=false to run the
    # undefended baseline for comparison.
    defenses_enabled: bool = True
    # Secret marker planted in the system prompt; if it ever shows up in a reply, the output
    # scrub blocks the reply. Override in a real deployment.
    system_prompt_canary: str = "MLB-CANARY-7Q2X9F"


@lru_cache
def get_settings() -> Settings:
    return Settings()
