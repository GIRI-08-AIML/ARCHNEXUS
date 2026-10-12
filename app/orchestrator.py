"""Custom agent orchestrator.

Pipeline:  RFC -> Parser -> specialists (independent analysis) -> debate rounds
           -> Judge Agent -> Final Report -> PostgreSQL
"""
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.agents import ALL_SPECS, JUDGE_SPEC, SPECIALISTS
from app.agents.base import (
    AgentSpec,
    apply_guardrails,
    heuristic_verdict,
    run_analysis,
    run_debate,
    run_judge,
)
from app.config import Settings, get_settings
from app.llm import LLMClient, LLMError
from app.models import Agent, Debate, FinalReport, Finding, Project, Review
from app.parser import parse_rfc

logger = logging.getLogger(__name__)


def seed_agents(db: Session) -> dict[str, Agent]:
    """Upsert the agent definitions into the `agents` table."""
    existing = {a.name: a for a in db.scalars(select(Agent))}
    for spec in ALL_SPECS:
        agent = existing.get(spec.name)
        if agent is None:
            agent = Agent(name=spec.name)
            db.add(agent)
            existing[spec.name] = agent
        agent.role = spec.role
        agent.description = spec.description
        agent.system_prompt = spec.system_prompt
    db.commit()
    return existing


def fail_interrupted_reviews(db: Session) -> int:
    """Mark reviews left pending/running by a server restart as failed. Returns how many."""
    stale = db.scalars(select(Review).where(Review.status.in_(["pending", "running"]))).all()
    for review in stale:
        review.status = "failed"
        review.error = "Interrupted by a server restart. Start a new review."
        review.completed_at = datetime.now(timezone.utc)
    db.commit()
    return len(stale)


class ReviewOrchestrator:
    def __init__(self, db: Session, llm: LLMClient, settings: Settings | None = None):
        self.db = db
        self.llm = llm
        self.settings = settings or get_settings()

    # ------------------------------------------------------------------ public
    def run(self, review_id: int) -> Review:
        review = self.db.get(Review, review_id)
        if review is None:
            raise ValueError(f"Review {review_id} not found")
        review.status = "running"
        self.db.commit()

        try:
            self._execute(review)
            review.status = "completed"
            review.completed_at = datetime.now(timezone.utc)
            self.db.commit()
        except Exception as exc:  # noqa: BLE001 - persist any failure on the review
            logger.exception("Review %s failed", review_id)
            self.db.rollback()
            review = self.db.get(Review, review_id)
            review.status = "failed"
            review.error = str(exc)[:2000]
            review.completed_at = datetime.now(timezone.utc)
            self.db.commit()
        return review

    # ---------------------------------------------------------------- pipeline
    def _execute(self, review: Review) -> None:
        project: Project = review.project
        agents = seed_agents(self.db)

        # Snapshot RFC text on review if not already set
        if not review.rfc_text:
            review.rfc_text = project.rfc_text

        # Ensure previous_review_id is linked to the latest prior completed review
        if review.previous_review_id is None:
            prev = self.db.scalars(
                select(Review)
                .where(Review.project_id == project.id, Review.id < review.id, Review.status == "completed")
                .order_by(Review.id.desc())
            ).first()
            if prev:
                review.previous_review_id = prev.id

        parsed = parse_rfc(project.name, review.rfc_text)
        review.parsed_sections = parsed.to_dict()
        self.db.commit()

        findings = self._analysis_round(review, project.name, parsed, agents)
        transcript = self._debate_rounds(review, agents, findings)
        self._judge(review, project.name, agents, findings, transcript)

    def _analysis_round(self, review, project_name, parsed, agents) -> dict[str, list[dict]]:
        import concurrent.futures

        collected: dict[str, list[dict]] = {}
        failures: list[str] = []
        rfc_full_text = (review.rfc_text or "").lower()

        def analyze_spec(spec):
            try:
                res = run_analysis(
                    spec, self.llm, project_name, parsed, self.settings.max_rfc_chars_in_prompt
                )
                return spec.name, res, None
            except LLMError as exc:
                return spec.name, [], exc

        max_workers = min(len(SPECIALISTS), max(1, self.settings.max_specialist_concurrency))
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(analyze_spec, spec) for spec in SPECIALISTS]
            for future in concurrent.futures.as_completed(futures):
                name, drafts, err = future.result()
                if err:
                    logger.warning("%s failed: %s", name, err)
                    failures.append(name)
                    continue

                spec_findings = []
                for d in drafts:
                    q = (d.quote or "").strip()
                    # Validate quote presence in RFC: must have a quote and it must exist in RFC (case-insensitive)
                    q_clean = " ".join(q.split()).lower()
                    rfc_clean = " ".join(rfc_full_text.split())
                    is_valid = bool(q_clean and q_clean in rfc_clean)

                    # Only keep findings that have a valid RFC quote (hallucination guard)
                    if not is_valid and rfc_full_text:
                        logger.info("Discarding finding '%s' from %s: quote not found in RFC", d.title, name)
                        continue

                    self.db.add(
                        Finding(
                            review_id=review.id,
                            agent_id=agents[name].id,
                            round=1,
                            category=d.category[:100],
                            severity=d.severity.value,
                            title=d.title[:300],
                            description=d.description,
                            recommendation=d.recommendation,
                            tradeoffs=d.tradeoffs,
                            quote=d.quote[:1000] if d.quote else None,
                            quote_valid=is_valid,
                        )
                    )
                    spec_findings.append(
                        {
                            "severity": d.severity.value,
                            "title": d.title,
                            "recommendation": d.recommendation,
                            "tradeoffs": d.tradeoffs,
                            "quote": d.quote,
                        }
                    )
                if spec_findings:
                    collected[name] = spec_findings
                    self.db.commit()

        if not collected:
            raise RuntimeError(f"All specialist agents failed: {', '.join(failures)}")
        return collected

    def _debate_rounds(self, review, agents, findings) -> list[dict]:
        transcript: list[dict] = []
        names = {spec.name for spec in SPECIALISTS} & set(findings)

        for round_no in range(1, self.settings.debate_rounds + 1):
            round_entries: list[dict] = []
            for spec in SPECIALISTS:
                if spec.name not in names:
                    continue
                try:
                    drafts = run_debate(spec, self.llm, round_no, findings, transcript)
                except LLMError as exc:
                    logger.warning("%s debate failed: %s", spec.name, exc)
                    continue
                for d in drafts:
                    target = d.target_agent if d.target_agent in names and d.target_agent != spec.name else None
                    self.db.add(
                        Debate(
                            review_id=review.id,
                            agent_id=agents[spec.name].id,
                            target_agent_id=agents[target].id if target else None,
                            round=round_no,
                            stance=d.stance.value,
                            message=d.message,
                        )
                    )
                    round_entries.append(
                        {
                            "round": round_no,
                            "from": spec.name,
                            "to": target,
                            "stance": d.stance.value,
                            "message": d.message,
                        }
                    )
                self.db.commit()  # save each agent's debate turn so progress is visible live
            self.db.commit()
            transcript.extend(round_entries)
            if not round_entries:
                break  # nothing left to argue about
        return transcript

    def _judge(self, review, project_name, agents, findings, transcript) -> None:
        try:
            verdict = run_judge(self.llm, project_name, findings, transcript)
        except Exception as exc:  # LLMError or validation failure
            logger.warning("%s failed (%s); using heuristic verdict", JUDGE_SPEC.name, exc)
            verdict = heuristic_verdict(findings)

        verdict = apply_guardrails(verdict, findings)

        self.db.add(
            FinalReport(
                review_id=review.id,
                decision=verdict.decision.value,
                score=verdict.score,
                summary=verdict.summary,
                recommendations=verdict.recommendations,
                key_risks=verdict.key_risks,
            )
        )
        self.db.commit()


def run_review_job(review_id: int, session_factory: sessionmaker, llm: LLMClient) -> None:
    """Entry point for FastAPI background tasks: own session, own lifecycle."""
    with session_factory() as db:
        ReviewOrchestrator(db, llm).run(review_id)
