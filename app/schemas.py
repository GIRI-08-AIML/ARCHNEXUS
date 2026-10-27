import re
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Severity(StrEnum):
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class Stance(StrEnum):
    agree = "agree"
    disagree = "disagree"
    refine = "refine"


class Decision(StrEnum):
    approve = "approve"
    approve_with_changes = "approve_with_changes"
    reject = "reject"


class ReviewStatus(StrEnum):
    pending = "pending"
    running = "running"
    completed = "completed"
    failed = "failed"


def _to_text(value: Any) -> Any:
    if value is None or isinstance(value, str):
        return value
    if isinstance(value, list):
        return "; ".join(str(v) for v in value)
    return str(value)


# ----------------------------------------------------------------- LLM outputs
class FindingDraft(BaseModel):
    """A finding as produced by an agent (validated LLM output)."""

    category: str = "general"
    severity: Severity = Severity.medium
    title: str
    description: str
    recommendation: str
    tradeoffs: str | None = None
    quote: str | None = None

    @field_validator("severity", mode="before")
    @classmethod
    def _severity(cls, v: Any) -> Any:
        v = str(v).strip().lower()
        return v if v in Severity._value2member_map_ else "medium"

    @field_validator("title", "description", "recommendation", "tradeoffs", "category", "quote", mode="before")
    @classmethod
    def _text(cls, v: Any) -> Any:
        return _to_text(v)


class DebateDraft(BaseModel):
    target_agent: str | None = None
    stance: Stance = Stance.refine
    message: str

    @field_validator("stance", mode="before")
    @classmethod
    def _stance(cls, v: Any) -> Any:
        v = str(v).strip().lower()
        return v if v in Stance._value2member_map_ else "refine"

    @field_validator("message", mode="before")
    @classmethod
    def _text(cls, v: Any) -> Any:
        return _to_text(v)


class JudgeVerdict(BaseModel):
    decision: Decision
    score: int = Field(ge=0, le=100)
    summary: str
    recommendations: list[str] = Field(default_factory=list)
    key_risks: list[str] = Field(default_factory=list)

    @field_validator("decision", mode="before")
    @classmethod
    def _decision(cls, v: Any) -> Any:
        v = str(v).strip().lower().replace(" ", "_").replace("-", "_")
        return v if v in Decision._value2member_map_ else "approve_with_changes"

    @field_validator("score", mode="before")
    @classmethod
    def _score(cls, v: Any) -> Any:
        try:
            return max(0, min(100, int(float(v))))
        except (TypeError, ValueError):
            return 50

    @field_validator("recommendations", "key_risks", mode="before")
    @classmethod
    def _items(cls, v: Any) -> Any:
        if v is None:
            return []
        if isinstance(v, str):
            return [v]
        out = []
        for item in v:
            if isinstance(item, dict):
                out.append(" - ".join(str(x) for x in item.values()))
            else:
                out.append(str(item))
        return out


class VerifyDraft(BaseModel):
    """A fact-check of one finding against the RFC (validated LLM output)."""

    verdict: str = "valid"  # valid | already_addressed | contradicted
    evidence: str | None = None
    reason: str | None = None
    severity: str | None = None  # the severity the finding deserves; None when the model gave none or garbage

    @field_validator("severity", mode="before")
    @classmethod
    def _severity(cls, v: Any) -> str | None:
        v = str(v).strip().lower() if v is not None else ""
        return v if v in Severity._value2member_map_ else None

    @field_validator("verdict", mode="before")
    @classmethod
    def _verdict(cls, v: Any) -> str:
        v = str(v).strip().lower().replace(" ", "_").replace("-", "_")
        if v in ("already_addressed", "addressed", "covered", "already_covered"):
            return "already_addressed"
        if v in ("contradicted", "contradicts", "false", "wrong", "incorrect"):
            return "contradicted"
        return "valid"  # anything unclear keeps the finding

    @field_validator("evidence", "reason", mode="before")
    @classmethod
    def _text(cls, v: Any) -> Any:
        return _to_text(v)


# ------------------------------------------------------------------ API schemas
class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class RegisterRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    company: str | None = Field(default=None, max_length=200)
    email: str = Field(max_length=320)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL_RE.match(v):
            raise ValueError("Enter a valid email address")
        return v

    @field_validator("name", "company")
    @classmethod
    def _strip(cls, v: str | None) -> str | None:
        v = v.strip() if v else v
        return v or None


class LoginRequest(BaseModel):
    email: str = Field(max_length=320)
    password: str = Field(max_length=128)


class UserRead(ORMModel):
    id: int
    email: str
    name: str
    company: str | None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserRead


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    rfc_text: str = Field(min_length=50, description="The RFC / architecture proposal (Markdown or text)")


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    rfc_text: str | None = Field(default=None, min_length=50, description="Updated RFC content")


class ProjectRfcVersionRead(ORMModel):
    id: int
    project_id: int
    version_number: int
    rfc_text: str
    created_at: datetime


class ProjectRead(ORMModel):
    id: int
    name: str
    created_at: datetime


class ProjectDetail(ProjectRead):
    rfc_text: str
    rfc_versions: list[ProjectRfcVersionRead] = Field(default_factory=list)


class AgentRead(ORMModel):
    id: int
    name: str
    role: str
    description: str


class FindingStatus(StrEnum):
    open = "open"
    accepted = "accepted"
    rejected = "rejected"
    fixed = "fixed"


class FindingStatusUpdate(BaseModel):
    status: FindingStatus
    reason: str | None = Field(default=None, max_length=1000)

    @field_validator("reason")
    @classmethod
    def _validate_reason(cls, v: str | None, info) -> str | None:
        return v.strip() if v else None


class MemberRole(StrEnum):
    owner = "owner"
    reviewer = "reviewer"
    viewer = "viewer"


class OrganizationRead(ORMModel):
    id: int
    name: str
    created_at: datetime


class MembershipRead(ORMModel):
    id: int
    organization_id: int
    user_id: int
    role: str
    user_name: str
    user_email: str
    created_at: datetime


class InviteMemberRequest(BaseModel):
    email: str = Field(max_length=320)
    role: MemberRole = MemberRole.reviewer

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip().lower()
        if not _EMAIL_RE.match(v):
            raise ValueError("Enter a valid email address")
        return v


class FindingCommentCreate(BaseModel):
    comment: str = Field(min_length=1, max_length=2000)

    @field_validator("comment")
    @classmethod
    def _comment(cls, v: str) -> str:
        clean = v.strip()
        if not clean:
            raise ValueError("Comment cannot be empty")
        return clean


class FindingCommentRead(ORMModel):
    id: int
    finding_id: int
    user_id: int
    user_name: str
    comment: str
    created_at: datetime


class FindingRead(ORMModel):
    id: int
    review_id: int
    agent_id: int
    agent_name: str
    round: int
    category: str
    severity: str
    title: str
    description: str
    recommendation: str
    tradeoffs: str | None
    status: str = "open"
    status_reason: str | None = None
    quote: str | None = None
    quote_valid: bool = True
    comments: list[FindingCommentRead] = Field(default_factory=list)



class DebateRead(ORMModel):
    id: int
    review_id: int
    agent_id: int
    agent_name: str
    target_agent_id: int | None
    target_agent_name: str | None
    round: int
    stance: str
    message: str


class FinalReportRead(ORMModel):
    id: int
    review_id: int
    decision: str
    score: int
    summary: str
    recommendations: list[str]
    key_risks: list[str]
    created_at: datetime


class ReviewRead(ORMModel):
    id: int
    project_id: int
    rfc_version_id: int | None = None
    previous_review_id: int | None = None
    rfc_text: str | None = None
    status: str
    error: str | None
    created_at: datetime
    completed_at: datetime | None


class ReviewSummary(ReviewRead):
    project_name: str
    decision: str | None = None
    score: int | None = None
    total_findings: int = 0
    resolved_findings: int = 0



class ComparisonItem(BaseModel):
    status: str  # "fixed", "still_open", "new"
    finding: FindingRead
    matched_finding: FindingRead | None = None


class ComparisonCounts(BaseModel):
    fixed: int = 0
    still_open: int = 0
    new: int = 0


class ComparisonResult(BaseModel):
    previous_review_id: int | None
    score_diff: int | None
    previous_score: int | None
    current_score: int | None
    counts: ComparisonCounts
    matches: list[ComparisonItem]


class ReviewDetail(ReviewRead):
    parsed_sections: dict | None
    findings: list[FindingRead]
    debates: list[DebateRead]
    report: FinalReportRead | None
    comparison: ComparisonResult | None = None
    total_findings: int = 0
    resolved_findings: int = 0


# ----------------------------------------------------------------- chat about a review
class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)

    @field_validator("message")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Type a question first.")
        return v


class ChatAction(BaseModel):
    finding_id: int
    status: str
    reason: str | None = None


class ChatMessageRead(ORMModel):
    id: int
    role: str
    content: str
    cited_finding_ids: list[int] = Field(default_factory=list)
    actions: list[ChatAction] = Field(default_factory=list)
    created_at: datetime

    @field_validator("cited_finding_ids", "actions", mode="before")
    @classmethod
    def _none_is_empty(cls, v):
        return v or []


class ChatExchange(BaseModel):
    question: ChatMessageRead
    answer: ChatMessageRead
