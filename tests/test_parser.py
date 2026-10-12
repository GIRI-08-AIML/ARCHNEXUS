import pytest

from app.parser import RFCParseError, classify_heading, parse_rfc
from tests.conftest import SAMPLE_RFC


def test_classify_heading():
    assert classify_heading("Security Considerations") == "security"
    assert classify_heading("Data Model") == "data"
    assert classify_heading("Rollout plan") == "deployment"
    assert classify_heading("Proposed Architecture") == "architecture"
    assert classify_heading("Funny Cats") == "other"


def test_parse_sections_and_title():
    parsed = parse_rfc("fallback", SAMPLE_RFC)
    assert parsed.title == "Order Service RFC"
    assert {"requirements", "architecture", "security", "data"} <= set(parsed.sections)
    assert "JWT" in parsed.sections["security"]
    assert "scalability" in parsed.missing_sections
    assert "reliability" in parsed.missing_sections


def test_parse_without_headings():
    text = "word " * 40
    parsed = parse_rfc("Plain", text)
    assert parsed.sections == {"general": text.strip()}
    assert parsed.missing_sections == []


def test_too_short_rejected():
    with pytest.raises(RFCParseError):
        parse_rfc("x", "too short")


def test_prompt_text_truncates():
    parsed = parse_rfc("x", SAMPLE_RFC)
    assert "truncated" in parsed.to_prompt_text(max_chars=50)
