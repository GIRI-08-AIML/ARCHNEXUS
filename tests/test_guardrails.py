from sqlalchemy import select

from app.agents.base import apply_guardrails
from app.models import Project, Review
from app.orchestrator import fail_interrupted_reviews
from app.schemas import JudgeVerdict
from tests.conftest import SAMPLE_RFC


def _verdict(decision="approve", score=90):
    return JudgeVerdict(decision=decision, score=score, summary="ok")


def _findings(**counts):
    items = [{"severity": sev, "title": "t", "recommendation": "r"} for sev, n in counts.items() for _ in range(n)]
    return {"Some Agent": items}


def test_two_criticals_force_reject_and_cap_score():
    v = apply_guardrails(_verdict("approve_with_changes", 85), _findings(critical=2, high=1))
    assert v.decision.value == "reject"
    assert v.score == 40
    assert "Adjusted by review rules" in v.summary
    assert "Review Board Audit: 2 critical, 1 high" in v.summary


def test_three_criticals_force_reject_and_cap_score_at_25():
    v = apply_guardrails(_verdict("approve", 90), _findings(critical=3))
    assert v.decision.value == "reject"
    assert v.score == 25
    assert "Adjusted by review rules" in v.summary
    assert "Review Board Audit: 3 critical, 0 high" in v.summary


def test_three_highs_cap_score_at_70():
    v = apply_guardrails(_verdict("approve", 90), _findings(high=3))
    assert v.decision.value == "approve_with_changes"
    assert v.score == 70


def test_one_critical_blocks_plain_approval():
    v = apply_guardrails(_verdict("approve", 95), _findings(critical=1))
    assert v.decision.value == "approve_with_changes"
    assert v.score == 60


def test_high_blocks_plain_approval():
    v = apply_guardrails(_verdict("approve", 95), _findings(high=2))
    assert v.decision.value == "approve_with_changes"
    assert v.score == 85


def test_clean_review_left_untouched():
    original = _verdict("approve", 92)
    guarded = apply_guardrails(original, _findings(medium=3, low=2))
    assert guarded.decision == original.decision
    assert guarded.score == original.score
    assert "Review Board Audit: 0 critical, 0 high, 3 medium, and 2 low finding(s) identified." in guarded.summary


def test_strict_judge_is_not_softened():
    v = apply_guardrails(_verdict("reject", 20), _findings(critical=1))
    assert v.decision.value == "reject"
    assert v.score == 20


def test_interrupted_reviews_are_failed(db):
    project = Project(name="p", rfc_text=SAMPLE_RFC)
    db.add(project)
    db.commit()
    for status in ("pending", "running", "completed"):
        db.add(Review(project_id=project.id, status=status))
    db.commit()

    assert fail_interrupted_reviews(db) == 2
    statuses = sorted(r.status for r in db.scalars(select(Review)))
    assert statuses == ["completed", "failed", "failed"]
