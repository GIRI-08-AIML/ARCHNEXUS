"""LLM access layer. Agents only depend on the `LLMClient` protocol."""
import json
import logging
import re
import time
from typing import Protocol

import httpx

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    pass


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
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise LLMError(f"Cloud LLM request failed: {exc}") from exc

    def chat_json(self, messages: list[dict]) -> dict:
        convo = list(messages)
        last_error: Exception | None = None

        for attempt in range(self.settings.llm_max_retries + 1):
            try:
                content = self._chat(convo)
            except LLMError as exc:
                last_error = exc
                logger.warning("Cloud LLM call failed (attempt %d): %s", attempt + 1, exc)
                time.sleep(self.RETRY_DELAY_SECONDS)
                continue

            try:
                return extract_json(content)
            except ValueError as exc:
                last_error = exc
                logger.warning("Invalid JSON from cloud model (attempt %d): %s", attempt + 1, exc)
                convo = convo + [
                    {"role": "assistant", "content": content},
                    {
                        "role": "user",
                        "content": "Your reply was not valid JSON. Reply again with ONLY the JSON object.",
                    },
                ]

        raise LLMError(f"Cloud model call failed after retries: {last_error}")


def get_llm() -> LLMClient:
    settings = get_settings()
    if settings.llm_provider in ("openai", "groq"):
        return OpenAICompatibleClient(settings)
    return OllamaClient(settings)
