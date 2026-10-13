import json
from pathlib import Path

from app.agents.base import (
    ANALYSIS_FORMAT,
    SEVERITY_GUIDE,
    build_verify_messages,
    find_duplicate,
    lowered_severity,
)
from app.schemas import FindingDraft, Severity, VerifyDraft

# The 19 findings from a real review of a sample RFC. Findings 12 and 16 repeat findings 5 and 1.
REAL = json.loads((Path(__file__).parent / "fixtures" / "review6_findings.json").read_text(encoding="utf-8"))


def _drafts():
    return [FindingDraft.model_validate(x) for x in REAL]


def test_real_review_has_exactly_two_duplicates():
    drafts = _drafts()
    kept: list[FindingDraft] = []
    merged: dict[int, int] = {}
    for i, d in enumerate(drafts):
        hit = find_duplicate(d, kept)
        if hit is None:
            kept.append(d)
        else:
            merged[i] = hit
    # 16 (circuit breaker, Reliability) folds into 1 (circuit breaker, Architecture); 12 (key rotation, Database) into 5.
    assert set(merged) == {12, 16}
    assert len(kept) == 17
    assert kept[merged[12]].title == drafts[5].title
    assert kept[merged[16]].title == drafts[1].title


def test_different_problems_that_quote_the_same_sentence_are_not_merged():
    d = _drafts()
    # Atomicity and write-bottleneck both quote the "Callers send a request ..." sentence.
    assert find_duplicate(d[13], [d[9]]) is None
    # Token renewal and token revocation both quote the token sentence.
    assert find_duplicate(d[4], [d[2]]) is None


def test_findings_with_no_quote_and_different_titles_are_not_merged():
    a = FindingDraft(title="Slow queries", description="d", recommendation="Add an index", quote=None)
    b = FindingDraft(title="No audit trail", description="d", recommendation="Log changes", quote=None)
    assert find_duplicate(a, [b]) is None


def test_near_identical_titles_merge_even_with_different_quotes():
    a = FindingDraft(title="No circuit breaker on the payment provider", description="d", recommendation="x", quote="one")
    b = FindingDraft(title="No circuit breaker for payment provider", description="d", recommendation="y", quote="two")
    assert find_duplicate(b, [a]) == 0


def test_lowered_severity_never_raises_and_ignores_garbage():
    assert lowered_severity(Severity.critical, "medium") == Severity.medium
    assert lowered_severity(Severity.high, "low") == Severity.low
    assert lowered_severity(Severity.medium, "critical") == Severity.medium  # never raised
    assert lowered_severity(Severity.medium, "medium") == Severity.medium
    assert lowered_severity(Severity.high, None) == Severity.high
    assert lowered_severity(Severity.high, "banana") == Severity.high


def test_verify_draft_normalises_severity():
    assert VerifyDraft.model_validate({"severity": " HIGH "}).severity == "high"
    assert VerifyDraft.model_validate({"severity": "urgent"}).severity is None
    assert VerifyDraft.model_validate({"severity": None}).severity is None
    assert VerifyDraft.model_validate({}).severity is None


def test_prompts_carry_the_severity_guide_and_the_given_severity():
    assert SEVERITY_GUIDE in ANALYSIS_FORMAT
    assert "most RFCs have no critical finding" in ANALYSIS_FORMAT
    msgs = build_verify_messages(
        "P", "RFC text", {"title": "T", "description": "D", "recommendation": "X", "severity": "critical"}, 1000
    )
    user = msgs[-1]["content"]
    assert "Finding severity as given: critical\n" in user
    assert "Never raise it" in user
    assert SEVERITY_GUIDE in user
