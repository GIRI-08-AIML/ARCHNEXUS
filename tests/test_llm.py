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
