from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://archnexus:archnexus@localhost:5432/archnexus"

    # LLM configuration (ollama or openai/groq)
    llm_provider: str = "ollama"  # "ollama" or "openai"
    llm_api_key: str = ""
    llm_model: str = "llama-3.3-70b-versatile"
    llm_base_url: str = "https://api.groq.com/openai/v1"

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3:8b"
    ollama_timeout: float = 300.0
    ollama_think: bool = False
    ollama_num_ctx: int = 8192
    llm_max_retries: int = 2
    # Cloud providers answer "429 Too Many Requests" when a free plan's per-minute limit is hit.
    # The client then waits (using the provider's Retry-After when given) and tries again.
    llm_rate_limit_retries: int = 6
    llm_rate_limit_max_wait: float = 60.0  # seconds; a longer wait (e.g. a daily limit) is not waited out

    secret_key: str = "change-me"
    token_expire_minutes: int = 60 * 24 * 7

    debate_rounds: int = 1
    max_rfc_chars_in_prompt: int = 12000
    max_specialist_concurrency: int = 5
    # Second pass that drops findings the RFC already addresses or contradicts.
    verify_findings: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()
