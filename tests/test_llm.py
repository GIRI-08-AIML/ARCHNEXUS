import pytest

from app.llm import extract_json


def test_extract_plain():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_strips_think_and_fences():
    raw = '<think>hmm {not json}</think>\n```json\n{"a": [1, 2]}\n```'
    assert extract_json(raw) == {"a": [1, 2]}


def test_extract_with_chatter():
    assert extract_json('Sure! Here you go: {"ok": true} Hope that helps') == {"ok": True}


def test_extract_failure():
    with pytest.raises(ValueError):
        extract_json("no json here")


def test_get_llm_provider_selection(monkeypatch):
    from app.config import get_settings
    from app.llm import OllamaClient, OpenAICompatibleClient, get_llm

    get_settings.cache_clear()
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    client = get_llm()
    assert isinstance(client, OllamaClient)

    get_settings.cache_clear()
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_API_KEY", "dummy-key")
    client = get_llm()
    assert isinstance(client, OpenAICompatibleClient)

    get_settings.cache_clear()


# ------------------------------------------------------------ rate limits (cloud provider)
import httpx

from app.config import Settings
from app.llm import LLMError, OpenAICompatibleClient


class _Resp:
    def __init__(self, status, body="", headers=None, content='{"ok": true}'):
        self.status_code = status
        self.text = body
        self.headers = headers or {}
        self._content = content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=httpx.Request("POST", "http://x"), response=self)

    def json(self):
        return {"choices": [{"message": {"content": self._content}}]}


def _client(monkeypatch, responses, **settings):
    """A client whose HTTP calls return `responses` in order; returns (client, sleeps, call_count)."""
    sleeps, calls = [], []

    def fake_post(*args, **kwargs):
        calls.append(1)
        return responses[min(len(calls) - 1, len(responses) - 1)]

    monkeypatch.setattr("app.llm.httpx.post", fake_post)
    monkeypatch.setattr("app.llm.time.sleep", lambda s: sleeps.append(s))
    cfg = Settings(_env_file=None, llm_api_key="k", llm_provider="groq", **settings)
    return OpenAICompatibleClient(cfg), sleeps, calls


def test_rate_limit_waits_for_retry_after_then_succeeds(monkeypatch):
    limited = _Resp(429, "slow down", {"retry-after": "7"})
    client, sleeps, calls = _client(monkeypatch, [limited, limited, _Resp(200)])
    assert client.chat_json([{"role": "user", "content": "hi"}]) == {"ok": True}
    assert len(calls) == 3
    assert sleeps == [7.5, 7.5]  # waited exactly what the provider asked, plus half a second


def test_rate_limit_without_retry_after_backs_off(monkeypatch):
    limited = _Resp(429)
    client, sleeps, _ = _client(monkeypatch, [limited, limited, limited, _Resp(200)])
    assert client.chat_json([{"role": "user", "content": "hi"}]) == {"ok": True}
    assert len(sleeps) == 3
    assert 5 <= sleeps[0] < 6 and 10 <= sleeps[1] < 11 and 20 <= sleeps[2] < 21


def test_rate_limit_backoff_is_capped(monkeypatch):
    client, sleeps, _ = _client(
        monkeypatch, [_Resp(429)], llm_rate_limit_retries=5, llm_rate_limit_max_wait=12
    )
    with pytest.raises(LLMError):
        client.chat_json([{"role": "user", "content": "hi"}])
    assert max(sleeps) < 13


def test_rate_limit_gives_up_after_the_retry_budget(monkeypatch):
    client, sleeps, calls = _client(monkeypatch, [_Resp(429, "too many")], llm_rate_limit_retries=3)
    with pytest.raises(LLMError, match="rate limit exceeded"):
        client.chat_json([{"role": "user", "content": "hi"}])
    assert len(sleeps) == 3 and len(calls) == 4


def test_very_long_retry_after_is_not_waited_out(monkeypatch):
    """A one-hour Retry-After means a daily limit. Fail fast instead of freezing the review."""
    client, sleeps, calls = _client(monkeypatch, [_Resp(429, "daily limit", {"retry-after": "3600"})])
    with pytest.raises(LLMError, match="daily limit"):
        client.chat_json([{"role": "user", "content": "hi"}])
    assert sleeps == [] and len(calls) == 1


def test_error_message_includes_what_the_provider_said(monkeypatch):
    gone = _Resp(404, '{"error": {"message": "The model `llama-3.3-70b-versatile` does not exist"}}')
    client, _, _ = _client(monkeypatch, [gone])
    with pytest.raises(LLMError, match="does not exist"):
        client.chat_json([{"role": "user", "content": "hi"}])


def test_other_errors_still_use_the_normal_retry_count(monkeypatch):
    client, sleeps, calls = _client(monkeypatch, [_Resp(500, "oops")], llm_max_retries=2)
    with pytest.raises(LLMError):
        client.chat_json([{"role": "user", "content": "hi"}])
    assert len(calls) == 3  # 1 try + 2 retries, like before
    assert sleeps == [OpenAICompatibleClient.RETRY_DELAY_SECONDS] * 3


def test_hosted_postgres_urls_get_the_driver_added():
    for given in ("postgres://u:p@host/db?sslmode=require", "postgresql://u:p@host/db?sslmode=require"):
        assert Settings(_env_file=None, database_url=given).database_url == "postgresql+psycopg://u:p@host/db?sslmode=require"
    assert Settings(_env_file=None, database_url="sqlite://").database_url == "sqlite://"
    already = "postgresql+psycopg://u:p@host/db"
    assert Settings(_env_file=None, database_url=already).database_url == already
