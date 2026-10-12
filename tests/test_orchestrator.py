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


# ------------------------------------------------------------ evidence check (verifier)
def _findings(db, review_id):
    return db.scalars(select(Finding).where(Finding.review_id == review_id)).all()


def test_verifier_drops_findings_the_rfc_contradicts(db):
    rules = {
        "Database Agent finding": {
            "verdict": "contradicted",
            "evidence": "Orders must never be lost.",
            "reason": "The RFC already says so.",
        }
    }
    review_id = _make_review(db)
    llm = FakeLLM(verify_rules=rules)
    review = ReviewOrchestrator(db, llm).run(review_id)

    assert review.status == "completed"
    titles = {f.title for f in _findings(db, review_id)}
    assert "Database Agent finding" not in titles
    assert len(titles) == 4  # the other four specialists keep theirs
    assert llm.calls.count("TASK: VERIFY") == 5  # one check per finding
    report = db.scalar(select(FinalReport))
    assert "Evidence check: 1 finding removed" in report.summary


def test_verifier_evidence_must_exist_in_the_rfc(db):
    """If the verifier invents its evidence, the finding is kept."""
    rules = {
        "Database Agent finding": {
            "verdict": "already_addressed",
            "evidence": "We use sharded databases with automatic failover everywhere.",
            "reason": "made up",
        }
    }
    review_id = _make_review(db)
    ReviewOrchestrator(db, FakeLLM(verify_rules=rules)).run(review_id)
    assert "Database Agent finding" in {f.title for f in _findings(db, review_id)}
    assert "Evidence check" not in db.scalar(select(FinalReport)).summary


def test_verifier_failure_keeps_every_finding(db):
    review_id = _make_review(db)
    review = ReviewOrchestrator(db, FakeLLM(fail_verify=True)).run(review_id)
    assert review.status == "completed"
    assert len(_findings(db, review_id)) == 5
    # The report must say the check did not run, so nobody mistakes "kept" for "verified".
    summary = db.scalar(select(FinalReport)).summary
    assert "Evidence check incomplete: 5 findings could not be checked" in summary
    assert "removed" not in summary


def test_verifier_can_be_switched_off(db):
    from app.config import Settings

    review_id = _make_review(db)
    llm = FakeLLM(verify_rules={"Database Agent finding": {
        "verdict": "contradicted", "evidence": "Orders must never be lost.", "reason": "x"}})
    ReviewOrchestrator(db, llm, Settings(verify_findings=False)).run(review_id)
    assert "TASK: VERIFY" not in llm.calls
    assert len(_findings(db, review_id)) == 5


def test_review_completes_when_the_rfc_answers_every_finding(db):
    """A strong RFC: every finding is removed, and the review still finishes."""
    answer = {"verdict": "contradicted", "evidence": "Orders must never be lost.", "reason": "covered"}
    names = ["Architecture", "Security", "Database", "Scalability", "Reliability"]
    rules = {f"{n} Agent finding": answer for n in names}
    review_id = _make_review(db)
    review = ReviewOrchestrator(db, FakeLLM(verify_rules=rules)).run(review_id)
    assert review.status == "completed"
    assert _findings(db, review_id) == []
    report = db.scalar(select(FinalReport))
    assert "0 critical, 0 high" in report.summary
    assert "5 findings removed" in report.summary


def test_no_usable_findings_is_a_failure_not_an_approval(db):
    """If the model returns nothing usable (and nothing was removed by the verifier), do not approve."""
    class EmptyLLM(FakeLLM):
        def chat_json(self, messages):
            if messages[-1]["content"].startswith("TASK: ANALYSIS"):
                return {"findings": []}
            return super().chat_json(messages)

    review_id = _make_review(db)
    review = ReviewOrchestrator(db, EmptyLLM()).run(review_id)
    assert review.status == "failed"
    assert "no usable findings" in review.error
