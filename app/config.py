from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://archnexus:archnexus@localhost:5432/archnexus"

    @field_validator("database_url")
    @classmethod
    def _use_psycopg_driver(cls, v: str) -> str:
        """Hosting providers give 'postgres://...' or 'postgresql://...'; SQLAlchemy needs the driver named."""
        for prefix in ("postgres://", "postgresql://"):
            if v.startswith(prefix):
                return "postgresql+psycopg://" + v[len(prefix):]
        return v

    # LLM configuration (ollama or openai/groq)
    llm_provider: str = "ollama"  # "ollama" or "openai"
    llm_api_key: str = ""
    llm_model: str = "openai/gpt-oss-120b"
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

    # Failed sign-ins: after this many wrong passwords the caller must wait for the lockout to pass.
    login_max_failures: int = 5  # per account, from one client address
    login_ip_max_failures: int = 20  # per client address, across all accounts
    login_lockout_seconds: int = 15 * 60

    # Questions about a finished review (the "Ask" tab). The review is sent to the model with every
    # question, so the context is capped to stay inside small token-per-minute limits.
    chat_max_context_chars: int = 16000  # about 4,000 tokens of findings, report and debate
    chat_max_rfc_chars: int = 3500  # RFC excerpts that match the question
    chat_history_messages: int = 8  # earlier messages sent along, so follow-up questions work
    chat_max_question_chars: int = 1500
    chat_max_questions_per_hour: int = 30  # per person; 0 turns the limit off

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
