from app.agents.base import build_verify_messages, text_in_rfc
from app.schemas import VerifyDraft

RFC = "Tokens expire after 15 minutes.  Contact details are\nencrypted at rest."


def test_text_in_rfc_ignores_case_spacing_and_quotes():
    assert text_in_rfc('"tokens EXPIRE after 15 minutes."', RFC, min_len=10)
    assert text_in_rfc("Contact details are encrypted at rest", RFC, min_len=10)
    assert not text_in_rfc("Tokens never expire", RFC, min_len=10)
    assert not text_in_rfc("", RFC)
    assert not text_in_rfc("encrypted", RFC, min_len=15)  # too short to count as evidence


def test_verify_draft_is_lenient_and_defaults_to_valid():
    assert VerifyDraft.model_validate({"verdict": "Already Addressed"}).verdict == "already_addressed"
    assert VerifyDraft.model_validate({"verdict": "WRONG"}).verdict == "contradicted"
    assert VerifyDraft.model_validate({"verdict": "no idea"}).verdict == "valid"
    assert VerifyDraft.model_validate({}).verdict == "valid"
    assert VerifyDraft.model_validate({"verdict": "valid", "evidence": ["a", "b"]}).evidence == "a; b"


def test_verify_prompt_contains_rfc_and_finding_and_truncates():
    msgs = build_verify_messages("P", "R" * 500, {"title": "T", "description": "D", "recommendation": "X"}, 100)
    user = msgs[-1]["content"]
    assert user.startswith("TASK: VERIFY\n")
    assert "Finding title: T\n" in user
    assert "RFC truncated" in user
    assert len(msgs) == 2
