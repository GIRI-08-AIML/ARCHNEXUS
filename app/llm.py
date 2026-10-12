"""LLM access layer. Agents only depend on the `LLMClient` protocol."""
import json
import logging
import random
import re
import time
from typing import Protocol

import httpx

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    pass


class RateLimitError(LLMError):
    """The provider answered 429. `retry_after` is the wait it asked for, in seconds, if any."""

    def __init__(self, message: str, retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


def _retry_after_seconds(resp: httpx.Response) -> float | None:
    try:
        value = float(resp.headers.get("retry-after", ""))
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


class LLMClient(Protocol):
    def chat_json(self, messages: list[dict]) -> dict: ...


_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def extract_json(content: str) -> dict:
    """Pull a JSON object out of a model reply (handles <think>, code fences, chatter)."""
    cleaned = _THINK_RE.sub("", content or "").strip()
    cleaned = _FENCE_RE.sub("", cleaned).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end <= start:
        raise ValueError("no JSON object found in model output")
    data = json.loads(cleaned[start : end + 1])
    if not isinstance(data, dict):
        raise ValueError("model output is not a JSON object")
    return data


class OllamaClient:
    RETRY_DELAY_SECONDS = 3

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def _chat(self, messages: list[dict]) -> str:
        s = self.settings
        payload = {
            "model": s.ollama_model,
            "messages": messages,
            "stream": False,
            "format": "json",
            "think": s.ollama_think,
            "options": {"temperature": 0.2, "num_ctx": s.ollama_num_ctx},
        }
        try:
            resp = httpx.post(
                f"{s.ollama_base_url.rstrip('/')}/api/chat",
                json=payload,
                timeout=s.ollama_timeout,
            )
            resp.raise_for_status()
            return resp.json()["message"]["content"]
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise LLMError(f"Ollama request failed: {exc}") from exc

    def chat_json(self, messages: list[dict]) -> dict:
        convo = list(messages)
        last_error: Exception | None = None

        for attempt in range(self.settings.llm_max_retries + 1):
            # 1) Call Ollama. A crash/500/timeout is retried after a short pause.
            try:
                content = self._chat(convo)
            except LLMError as exc:
                last_error = exc
                logger.warning("Ollama call failed (attempt %d): %s", attempt + 1, exc)
                time.sleep(self.RETRY_DELAY_SECONDS)
                continue

            # 2) Parse the reply. Bad JSON is retried with a correction message.
            try:
                return extract_json(content)
            except ValueError as exc:  # includes json.JSONDecodeError
                last_error = exc
                logger.warning("Invalid JSON from model (attempt %d): %s", attempt + 1, exc)
                convo = convo + [
                    {"role": "assistant", "content": content},
                    {
                        "role": "user",
                        "content": "Your reply was not valid JSON. Reply again with ONLY the JSON object.",
                    },
                ]

        raise LLMError(f"Model call failed after retries: {last_error}")


class OpenAICompatibleClient:
    RETRY_DELAY_SECONDS = 2

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def _chat(self, messages: list[dict]) -> str:
        s = self.settings
        headers = {
            "Authorization": f"Bearer {s.llm_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": s.llm_model,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
        }
        try:
            resp = httpx.post(
                f"{s.llm_base_url.rstrip('/')}/chat/completions",
                json=payload,
                headers=headers,
                timeout=s.ollama_timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as exc:
            # Include the provider's own message: a bare "404 Not Found" hides the real reason
            # (for example a retired model name).
            body = (exc.response.text or "").strip().replace("\n", " ")[:300]
            detail = f"{exc}" + (f" - provider said: {body}" if body else "")
            if exc.response.status_code == 429:
                raise RateLimitError(
                    f"Cloud LLM rate limit (429){' - provider said: ' + body if body else ''}",
                    _retry_after_seconds(exc.response),
                ) from exc
            raise LLMError(f"Cloud LLM request failed: {detail}") from exc
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise LLMError(f"Cloud LLM request failed: {exc}") from exc

    def _rate_limit_wait(self, exc: RateLimitError, waits_so_far: int) -> float:
        """Use the provider's Retry-After when given, otherwise back off 5, 10, 20, 40 ... seconds."""
        if exc.retry_after is not None:
            return exc.retry_after + 0.5
        return min(5 * (2**waits_so_far), self.settings.llm_rate_limit_max_wait) + random.uniform(0, 1)

    def chat_json(self, messages: list[dict]) -> dict:
        s = self.settings
        convo = list(messages)
        last_error: Exception | None = None
        attempt = 0  # ordinary failures (errors, bad JSON); rate-limit waits do not use these up
        rate_waits = 0

        while attempt <= s.llm_max_retries:
            try:
                content = self._chat(convo)
            except RateLimitError as exc:
                last_error = exc
                too_long = exc.retry_after is not None and exc.retry_after > s.llm_rate_limit_max_wait
                if too_long or rate_waits >= s.llm_rate_limit_retries:
                    break  # a long wait usually means a daily limit, so waiting would not help
                wait = self._rate_limit_wait(exc, rate_waits)
                rate_waits += 1
                logger.warning(
                    "Cloud LLM rate limit hit; waiting %.0fs before retrying (%d/%d)",
                    wait, rate_waits, s.llm_rate_limit_retries,
                )
                time.sleep(wait)
                continue
            except LLMError as exc:
                last_error = exc
                attempt += 1
                logger.warning("Cloud LLM call failed (attempt %d): %s", attempt, exc)
                time.sleep(self.RETRY_DELAY_SECONDS)
                continue

            try:
                return extract_json(content)
            except ValueError as exc:
                last_error = exc
                attempt += 1
                logger.warning("Invalid JSON from cloud model (attempt %d): %s", attempt, exc)
                convo = convo + [
                    {"role": "assistant", "content": content},
                    {
                        "role": "user",
                        "content": "Your reply was not valid JSON. Reply again with ONLY the JSON object.",
                    },
                ]

        if isinstance(last_error, RateLimitError):
            hint = (
                f" The provider asked for a {last_error.retry_after:.0f}s wait, which looks like a daily limit."
                if last_error.retry_after is not None and last_error.retry_after > s.llm_rate_limit_max_wait
                else " Lower MAX_SPECIALIST_CONCURRENCY or try again in a minute."
            )
            raise LLMError(f"Cloud model call failed: rate limit exceeded.{hint} ({last_error})")
        raise LLMError(f"Cloud model call failed after retries: {last_error}")


def get_llm() -> LLMClient:
    settings = get_settings()
    if settings.llm_provider in ("openai", "groq"):
        return OpenAICompatibleClient(settings)
    return OllamaClient(settings)
