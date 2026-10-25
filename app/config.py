"""Runtime settings, read from environment variables prefixed with ``JM_``."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="JM_", env_file=".env", extra="ignore")

    db_path: Path = REPO_ROOT / "data" / "job_matcher.db"
    ollama_url: str = "http://127.0.0.1:11434"
    llm_model: str = "qwen2.5:14b"  # reads resumes and pasted postings: quality matters
    # Assesses each shortlisted job. Many short judgements, so a smaller, about twice as fast
    # model is the better trade.
    scoring_model: str = "qwen2.5:7b"
    embed_model: str = "bge-m3"
    # A long resume takes the 14B model about two minutes to read on a laptop, and the
    # first call after Ollama starts also loads the model into memory.
    llm_timeout_s: float = 600.0
    # Ollama's default context is 4,096 tokens and it silently drops the start of longer
    # prompts. A long resume plus a LinkedIn export, or a long posting plus the profile,
    # needs more.
    llm_num_ctx: int = 16384
    ui_origin: str = "http://localhost:3000"
    # Seconds between live requests to one source (random within the range).
    scrape_delay_min: float = 3.0
    scrape_delay_max: float = 8.0
    # Repeat requests within this window are served from data/cache (0 turns it off).
    http_cache_ttl_s: float = 3600
    # Off in tests; the UI's Settings page can also switch scheduled runs off.
    scheduler: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
