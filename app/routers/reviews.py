from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.dependencies import get_current_user, get_db
from app.comparison import compare_reviews
from app.workspaces import check_project_access, get_user_org_ids
from app.models import (
    Agent,
    Debate,
    FinalReport,
    Finding,
    FindingComment,
    Project,
    Review,
    User,
)
from app.schemas import (
    AgentRead,
    ComparisonResult,
    DebateRead,
    FinalReportRead,
    FindingCommentCreate,
    FindingCommentRead,
    FindingRead,
    FindingStatus,
    FindingStatusUpdate,
    ReviewDetail,
    ReviewSummary,
    Severity,
)

router = APIRouter(tags=["reviews"])


def _get_review(db: Session, review_id: int, user: User, min_role: str = "viewer") -> Review:
    review = db.get(Review, review_id)
    if review is None or review.project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Review not found")
    check_project_access(db, review.project, user, min_role=min_role)
    return review


def _build_comparison(db: Session, review: Review) -> ComparisonResult | None:
    prev_review = None
    if review.previous_review_id:
        prev_review = db.get(Review, review.previous_review_id)
    if not prev_review:
        prev_review = db.scalars(
            select(Review)
            .where(Review.project_id == review.project_id, Review.id < review.id, Review.status == "completed")
            .order_by(Review.id.desc())
        ).first()

    if not prev_review or prev_review.status != "completed":
        return None

    res = compare_reviews(prev_review, review)
    return ComparisonResult.model_validate(res)



@router.get("/reviews", response_model=list[ReviewSummary])
def list_reviews(
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Most recent reviews across projects visible to the user's organization."""
    org_ids = get_user_org_ids(db, user.id)
    rows = db.execute(
        select(Review, Project.name, FinalReport.decision, FinalReport.score)
        .join(Project, Project.id == Review.project_id)
        .outerjoin(FinalReport, FinalReport.review_id == Review.id)
        .where(
            (Project.organization_id.in_(org_ids)) | (Project.user_id == user.id)
        )
        .order_by(Review.id.desc())
        .limit(limit)
    ).all()


    summaries = []
    for r, name, decision, score in rows:
        total = len(r.findings)
        resolved = sum(1 for f in r.findings if f.status in ("accepted", "rejected", "fixed"))
        summaries.append(
            ReviewSummary(
                id=r.id,
                project_id=r.project_id,
                status=r.status,
                error=r.error,
                created_at=r.created_at,
                completed_at=r.completed_at,
                project_name=name,
                decision=decision,
                score=score,
                total_findings=total,
                resolved_findings=resolved,
            )
        )
    return summaries


@router.get("/reviews/{review_id}", response_model=ReviewDetail)
def get_review(
    review_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    review = _get_review(db, review_id, user)
    comp = _build_comparison(db, review)
    detail = ReviewDetail.model_validate(review)
    detail.comparison = comp
    detail.total_findings = len(review.findings)
    detail.resolved_findings = sum(1 for f in review.findings if f.status in ("accepted", "rejected", "fixed"))
    return detail


@router.get("/reviews/{review_id}/comparison", response_model=ComparisonResult)
def get_review_comparison(
    review_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    review = _get_review(db, review_id, user)
    comp = _build_comparison(db, review)
    if not comp:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "No previous review available to compare against"
        )
    return comp


@router.get("/reviews/{review_id}/findings", response_model=list[FindingRead])
def list_findings(
    review_id: int,
    severity: Severity | None = None,
    agent: str | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    _get_review(db, review_id, user)
    stmt = select(Finding).where(Finding.review_id == review_id)
    if severity:
        stmt = stmt.where(Finding.severity == severity.value)
    if agent:
        stmt = stmt.join(Agent, Agent.id == Finding.agent_id).where(Agent.name.ilike(agent))
    return db.scalars(stmt.order_by(Finding.id)).all()


@router.patch("/reviews/{review_id}/findings/{finding_id}", response_model=FindingRead)
@router.put("/reviews/{review_id}/findings/{finding_id}", response_model=FindingRead)
def update_finding_status(
    review_id: int,
    finding_id: int,
    payload: FindingStatusUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Update status of a finding. Viewers cannot change status (requires reviewer or owner role)."""
    review = _get_review(db, review_id, user, min_role="reviewer")
    finding = db.get(Finding, finding_id)
    if finding is None or finding.review_id != review.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Finding not found")

    if payload.status == FindingStatus.rejected and not payload.reason:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "A reason is required when rejecting a finding"
        )

    finding.status = payload.status.value
    finding.status_reason = payload.reason
    db.commit()
    db.refresh(finding)
    return finding


@router.post("/reviews/{review_id}/findings/{finding_id}/comments", response_model=FindingCommentRead)
def add_finding_comment(
    review_id: int,
    finding_id: int,
    payload: FindingCommentCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Add a member comment on a finding (viewers, reviewers, and owners can comment)."""
    review = _get_review(db, review_id, user, min_role="viewer")
    finding = db.get(Finding, finding_id)
    if finding is None or finding.review_id != review.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Finding not found")

    comment = FindingComment(
        finding_id=finding.id,
        user_id=user.id,
        comment=payload.comment,
    )
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return comment


@router.get("/reviews/{review_id}/findings/{finding_id}/comments", response_model=list[FindingCommentRead])
def list_finding_comments(
    review_id: int,
    finding_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """List comments on a finding."""
    review = _get_review(db, review_id, user, min_role="viewer")
    finding = db.get(Finding, finding_id)
    if finding is None or finding.review_id != review.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Finding not found")
    return finding.comments



@router.get("/reviews/{review_id}/debates", response_model=list[DebateRead])
def list_debates(
    review_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    _get_review(db, review_id, user)
    return db.scalars(select(Debate).where(Debate.review_id == review_id).order_by(Debate.id)).all()


@router.get("/reviews/{review_id}/report", response_model=FinalReportRead)
def get_report(
    review_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    review = _get_review(db, review_id, user)
    report = db.scalar(select(FinalReport).where(FinalReport.review_id == review_id))
    if report is None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Report not available (review status: {review.status})"
        )
    return report


from fastapi.responses import PlainTextResponse
from app.exports import export_review_markdown, export_review_pdf


@router.get("/reviews/{review_id}/export/markdown", response_class=PlainTextResponse)
def export_markdown(
    review_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    """Export review report and findings as GitHub-flavored Markdown."""
    review = _get_review(db, review_id, user)
    md_content = export_review_markdown(review)
    return PlainTextResponse(
        content=md_content,
        media_type="text/markdown",
        headers={"Content-Disposition": f'attachment; filename="archnexus-review-{review_id}.md"'},
    )


@router.get("/reviews/{review_id}/export/pdf")
def export_pdf(
    review_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    """Export review report and findings as a styled PDF document."""
    review = _get_review(db, review_id, user)
    pdf_bytes = export_review_pdf(review)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="archnexus-review-{review_id}.pdf"'},
    )


@router.get("/agents", response_model=list[AgentRead])
def list_agents(db: Session = Depends(get_db)):
    return db.scalars(select(Agent).order_by(Agent.id)).all()


