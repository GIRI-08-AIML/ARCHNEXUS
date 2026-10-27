"""LLM access layer. Agents only depend on the `LLMClient` protocol."""
import json
import logging
import random
import re
import time
from typing import Iterator, Protocol

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

    def chat_text(self, messages: list[dict]) -> str: ...

    def stream_text(self, messages: list[dict]) -> Iterator[str]: ...


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


def clean_text(content: str) -> str:
    """A plain-text reply with any <think> block removed. An empty reply counts as a failure."""
    text = _THINK_RE.sub("", content or "").strip()
    if not text:
        raise ValueError("the model returned an empty reply")
    return text


def strip_think_stream(chunks: Iterator[str]) -> Iterator[str]:
    """Pass a stream of text through, dropping a leading <think>...</think> block if the model writes one."""
    buf, state = "", "start"  # start -> (think | pass)
    for chunk in chunks:
        if state == "pass":
            yield chunk
            continue
        buf += chunk
        if state == "start":
            head = buf.lstrip()
            if len(head) < 7 and "<think>"[: len(head)] == head.lower():
                continue  # could still turn out to be "<think>"
            if head.lower().startswith("<think>"):
                state = "think"
            else:
                state, out, buf = "pass", buf, ""
                yield out
                continue
        if state == "think":
            end = buf.lower().find("</think>")
            if end >= 0:
                rest = buf[end + len("</think>"):].lstrip()
                state, buf = "pass", ""
                if rest:
                    yield rest
    if state == "start" and buf:
        yield buf


class OllamaClient:
    RETRY_DELAY_SECONDS = 3

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def _chat(self, messages: list[dict], json_mode: bool = True) -> str:
        s = self.settings
        payload = {
            "model": s.ollama_model,
            "messages": messages,
            "stream": False,
            "think": s.ollama_think,
            "options": {"temperature": 0.2, "num_ctx": s.ollama_num_ctx},
        }
        if json_mode:
            payload["format"] = "json"
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

    def _complete(self, messages: list[dict], *, json_mode: bool, parse, correction: str | None):
        convo = list(messages)
        last_error: Exception | None = None

        for attempt in range(self.settings.llm_max_retries + 1):
            # 1) Call Ollama. A crash/500/timeout is retried after a short pause.
            try:
                content = self._chat(convo, json_mode)
            except LLMError as exc:
                last_error = exc
                logger.warning("Ollama call failed (attempt %d): %s", attempt + 1, exc)
                time.sleep(self.RETRY_DELAY_SECONDS)
                continue

            # 2) Parse the reply. A bad reply is retried (JSON replies get a correction message).
            try:
                return parse(content)
            except ValueError as exc:  # includes json.JSONDecodeError
                last_error = exc
                logger.warning("Unusable reply from model (attempt %d): %s", attempt + 1, exc)
                if correction:
                    convo = convo + [
                        {"role": "assistant", "content": content},
                        {"role": "user", "content": correction},
                    ]

        raise LLMError(f"Model call failed after retries: {last_error}")

    def chat_json(self, messages: list[dict]) -> dict:
        return self._complete(
            messages, json_mode=True, parse=extract_json,
            correction="Your reply was not valid JSON. Reply again with ONLY the JSON object.",
        )

    def chat_text(self, messages: list[dict]) -> str:
        return self._complete(messages, json_mode=False, parse=clean_text, correction=None)

    def stream_text(self, messages: list[dict]) -> Iterator[str]:
        s = self.settings
        payload = {
            "model": s.ollama_model, "messages": messages, "stream": True, "think": s.ollama_think,
            "options": {"temperature": 0.2, "num_ctx": s.ollama_num_ctx},
        }

        def raw() -> Iterator[str]:
            try:
                with httpx.stream("POST", f"{s.ollama_base_url.rstrip('/')}/api/chat", json=payload, timeout=s.ollama_timeout) as resp:
                    resp.raise_for_status()
                    for line in resp.iter_lines():
                        if not line:
                            continue
                        piece = json.loads(line).get("message", {}).get("content")
                        if piece:
                            yield piece
            except (httpx.HTTPError, ValueError) as exc:
                raise LLMError(f"Ollama request failed: {exc}") from exc

        return strip_think_stream(raw())


class OpenAICompatibleClient:
    RETRY_DELAY_SECONDS = 2

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def _chat(self, messages: list[dict], json_mode: bool = True) -> str:
        s = self.settings
        headers = {
            "Authorization": f"Bearer {s.llm_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": s.llm_model,
            "messages": messages,
            "temperature": 0.2,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
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
        return self._complete(
            messages, json_mode=True, parse=extract_json,
            correction="Your reply was not valid JSON. Reply again with ONLY the JSON object.",
        )

    def chat_text(self, messages: list[dict]) -> str:
        return self._complete(messages, json_mode=False, parse=clean_text, correction=None)

    def stream_text(self, messages: list[dict]) -> Iterator[str]:
        """Yield the reply piece by piece. A rate limit before the first piece is waited out like elsewhere."""
        s = self.settings
        headers = {"Authorization": f"Bearer {s.llm_api_key}", "Content-Type": "application/json"}
        payload = {"model": s.llm_model, "messages": messages, "temperature": 0.2, "stream": True}

        def raw() -> Iterator[str]:
            waits = 0
            while True:
                started = False
                try:
                    with httpx.stream(
                        "POST", f"{s.llm_base_url.rstrip('/')}/chat/completions",
                        json=payload, headers=headers, timeout=s.ollama_timeout,
                    ) as resp:
                        if resp.status_code >= 400:
                            resp.read()
                        resp.raise_for_status()
                        for line in resp.iter_lines():
                            if not line.startswith("data:"):
                                continue
                            data = line[5:].strip()
                            if data == "[DONE]":
                                return
                            choices = json.loads(data).get("choices") or [{}]
                            piece = (choices[0].get("delta") or {}).get("content")
                            if piece:
                                started = True
                                yield piece
                        return
                except httpx.HTTPStatusError as exc:
                    body = (exc.response.text or "").strip().replace("\n", " ")[:300]
                    if exc.response.status_code == 429:
                        err = RateLimitError(
                            f"Cloud LLM rate limit (429){' - provider said: ' + body if body else ''}",
                            _retry_after_seconds(exc.response),
                        )
                        too_long = err.retry_after is not None and err.retry_after > s.llm_rate_limit_max_wait
                        if started or too_long or waits >= s.llm_rate_limit_retries:
                            raise LLMError(f"Cloud model call failed: rate limit exceeded. ({err})") from exc
                        wait = self._rate_limit_wait(err, waits)
                        waits += 1
                        logger.warning("Cloud LLM rate limit hit while streaming; waiting %.0fs (%d/%d)", wait, waits, s.llm_rate_limit_retries)
                        time.sleep(wait)
                        continue
                    raise LLMError(f"Cloud LLM request failed: {exc}" + (f" - provider said: {body}" if body else "")) from exc
                except (httpx.HTTPError, ValueError, KeyError) as exc:
                    raise LLMError(f"Cloud LLM request failed: {exc}") from exc

        return strip_think_stream(raw())

    def _complete(self, messages: list[dict], *, json_mode: bool, parse, correction: str | None):
        s = self.settings
        convo = list(messages)
        last_error: Exception | None = None
        attempt = 0  # ordinary failures (errors, bad replies); rate-limit waits do not use these up
        rate_waits = 0

        while attempt <= s.llm_max_retries:
            try:
                content = self._chat(convo, json_mode)
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
                return parse(content)
            except ValueError as exc:
                last_error = exc
                attempt += 1
                logger.warning("Unusable reply from cloud model (attempt %d): %s", attempt, exc)
                if correction:
                    convo = convo + [
                        {"role": "assistant", "content": content},
                        {"role": "user", "content": correction},
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
