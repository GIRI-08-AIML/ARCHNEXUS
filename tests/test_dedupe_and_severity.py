import json
from pathlib import Path

from app.agents.base import (
    ANALYSIS_FORMAT,
    SEVERITY_GUIDE,
    OPEN_QUESTION_NOTE,
    build_analysis_messages,
    build_verify_messages,
    find_duplicate,
    lowered_severity,
)
from app.schemas import FindingDraft, Severity, VerifyDraft

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name):
    return [FindingDraft.model_validate(x) for x in json.loads((FIXTURES / name).read_text(encoding="utf-8"))]


# Real findings from two reviews of a sample RFC. REAL (19 findings) has two duplicates; REAL7 (14) has two more.
REAL_DRAFTS = _load("review6_findings.json")
REAL7_DRAFTS = _load("review7_findings.json")


def _drafts():
    return REAL_DRAFTS


def _merge_all(drafts):
    kept: list[FindingDraft] = []
    merged: dict[int, int] = {}
    for i, d in enumerate(drafts):
        hit = find_duplicate(d, kept)
        if hit is None:
            kept.append(d)
        else:
            merged[i] = hit
    return kept, merged


def test_real_review_6_has_exactly_two_duplicates():
    drafts = REAL_DRAFTS
    kept, merged = _merge_all(drafts)
    # 16 (circuit breaker, Reliability) folds into 1 (circuit breaker, Architecture); 12 (key rotation, Database) into 5.
    assert set(merged) == {12, 16}
    assert len(kept) == 17
    assert kept[merged[12]].title == drafts[5].title
    assert kept[merged[16]].title == drafts[1].title


def test_real_review_7_merges_the_three_provider_failover_findings_and_nothing_else():
    drafts = REAL7_DRAFTS
    kept, merged = _merge_all(drafts)
    # 0 (Architecture), 9 (Scalability) and 12 (Reliability) all say: switching providers after two minutes is too slow.
    assert set(merged) == {9, 12}
    assert {kept[i].title for i in merged.values()} == {drafts[0].title}
    assert len(kept) == 12
    # The idempotency-scoping finding and the worker-retry finding quote the same sentence but are different problems.
    assert drafts[5].title in {k.title for k in kept} and drafts[11].title in {k.title for k in kept}


def test_different_problems_that_quote_the_same_sentence_are_not_merged():
    d = REAL_DRAFTS
    # Atomicity and write-bottleneck both quote the "Callers send a request ..." sentence.
    assert find_duplicate(d[13], [d[9]]) is None
    # Token renewal and token revocation both quote the token sentence.
    assert find_duplicate(d[4], [d[2]]) is None
    # Idempotency scoping and worker-retry duplicates quote the same sentence (review 7).
    e = REAL7_DRAFTS
    assert find_duplicate(e[11], [e[5]]) is None


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


def test_only_the_architecture_agent_is_asked_to_report_open_questions():
    from app.agents import SPECIALISTS
    from app.parser import parse_rfc

    parsed = parse_rfc("P", "# RFC\n\n" + "We propose a small service that sends notifications to users. " * 4)
    for spec in SPECIALISTS:
        user = build_analysis_messages(spec, "P", parsed, 5000)[-1]["content"]
        assert (OPEN_QUESTION_NOTE in user) == (spec.name == "Architecture Agent"), spec.name
