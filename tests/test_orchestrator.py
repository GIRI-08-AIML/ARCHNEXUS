from sqlalchemy import select

from app.models import Agent, Debate, FinalReport, Finding, Project, Review
from app.orchestrator import ReviewOrchestrator, seed_agents
from tests.conftest import SAMPLE_RFC, FakeLLM


def _make_review(db) -> int:
    project = Project(name="Orders", rfc_text=SAMPLE_RFC)
    db.add(project)
    db.commit()
    review = Review(project_id=project.id, status="pending")
    db.add(review)
    db.commit()
    return review.id


def test_seed_agents_is_idempotent(db):
    seed_agents(db)
    seed_agents(db)
    assert len(db.scalars(select(Agent)).all()) == 6  # 5 specialists + judge


def test_full_pipeline(db):
    review_id = _make_review(db)
    llm = FakeLLM()
    review = ReviewOrchestrator(db, llm).run(review_id)

    assert review.status == "completed"
    assert review.parsed_sections["title"] == "Order Service RFC"

    findings = db.scalars(select(Finding)).all()
    assert len(findings) == 5  # one valid finding per specialist, malformed ones skipped
    assert any(f.severity == "critical" for f in findings)
    assert all(f.quote is not None and f.quote_valid is True for f in findings)

    debates = db.scalars(select(Debate)).all()
    assert len(debates) == 5
    assert all(d.stance == "disagree" for d in debates)
    assert all(d.target_agent_id is not None for d in debates)

    report = db.scalar(select(FinalReport))
    assert (report.decision, report.score) == ("reject", 35)
    assert report.recommendations == ["Fix auth", "high - Add indexes"]
    assert "Review Board Audit: 1 critical" in report.summary
    assert llm.calls.count("TASK: JUDGE") == 1


def test_findings_with_unquoted_or_hallucinated_quotes_are_filtered(db):
    class HallucinatingLLM(FakeLLM):
        def chat_json(self, messages):
            user = messages[-1]["content"]
            task = user.split("\n", 1)[0]
            if task.startswith("TASK: ANALYSIS"):
                return {
                    "findings": [
                        {
                            "category": "sec",
                            "severity": "critical",
                            "title": "fake issue",
                            "quote": "this text is completely made up and not in RFC",
                            "description": "d",
                            "recommendation": "r",
                        },
                        {
                            "category": "sec",
                            "severity": "high",
                            "title": "real issue",
                            "quote": "Orders must never be lost",
                            "description": "d",
                            "recommendation": "r",
                        }
                    ]
                }
            return super().chat_json(messages)

    review_id = _make_review(db)
    review = ReviewOrchestrator(db, HallucinatingLLM()).run(review_id)
    assert review.status == "completed"
    findings = db.scalars(select(Finding).where(Finding.review_id == review_id)).all()
    # The fake quote was filtered out; only the valid quote retained
    assert all(f.quote == "Orders must never be lost" for f in findings)


def test_judge_failure_falls_back_to_heuristic(db):
    review_id = _make_review(db)
    review = ReviewOrchestrator(db, FakeLLM(fail_judge=True)).run(review_id)
    assert review.status == "completed"
    report = db.scalar(select(FinalReport))
    assert report.decision == "reject"  # a critical finding exists
    assert "Judge Agent was unavailable" in report.summary


def test_all_agents_failing_marks_review_failed(db):
    review_id = _make_review(db)
    review = ReviewOrchestrator(db, FakeLLM(fail_all=True)).run(review_id)
    assert review.status == "failed"
    assert "All specialist agents failed" in review.error
