"""Central settings. Every value can be overridden with an environment variable
(or a .env file in the backend folder), e.g. MIZAN_LLM_MODEL=gemini-3.5-flash-lite."""
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


_BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MIZAN_",
        env_file=(_BACKEND_DIR / ".env", ".env"),
        extra="ignore",
    )

    # --- Storage -----------------------------------------------------------
    # "memory" keeps everything in RAM (tests, eval, quick demo).
    # A postgres URL (with pgvector) is used in the deployed system.
    database_url: str = "memory"
    data_dir: Path = Path("data")  # downloaded PDFs + parsed pages

    # --- LLM (any OpenAI-compatible endpoint: Gemini, Groq, OpenAI, Ollama) --
    llm_base_url: str = "https://generativelanguage.googleapis.com/v1beta/openai/"
    llm_api_key: str = ""
    llm_model: str = "gemini-3.5-flash-lite"   # 2.5 Flash is closed to new API users
    # second model used for the "API vs local" extraction comparison
    local_llm_base_url: str = "http://localhost:11434/v1"
    local_llm_model: str = "qwen2.5:7b"
    llm_timeout_s: float = 60.0
    llm_max_retries: int = 2
    # USD per 1M tokens (input, output) -- used only for cost reporting
    # gemini-3.5-flash list price (ai.google.dev/pricing, checked 22 Nov 2026);
    # gemini-3.5-flash-lite is 0.30 / 2.50
    price_in_per_m: float = 0.30
    price_out_per_m: float = 2.50

    # --- Retrieval ---------------------------------------------------------
    embed_model: str = "BAAI/bge-small-en-v1.5"
    rerank_model: str = "BAAI/bge-reranker-base"
    use_reranker: bool = False
    chunk_chars: int = 1500
    chunk_overlap: int = 200
    top_k: int = 6

    # --- Agent -------------------------------------------------------------
    agent_max_steps: int = 8

    # --- Integrations --------------------------------------------------------
    telegram_bot_token: str = ""
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""  # Gmail app password
    redis_url: str = "redis://localhost:6379/0"
    psx_base_url: str = "https://dps.psx.com.pk"
    poll_minutes: int = 30


@lru_cache
def get_settings() -> Settings:
    return Settings()
