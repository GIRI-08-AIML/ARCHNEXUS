from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(300))
    name: Mapped[str] = mapped_column(String(200))
    company: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    projects: Mapped[list["Project"]] = relationship(back_populates="owner")
    memberships: Mapped[list["Membership"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    memberships: Mapped[list["Membership"]] = relationship(back_populates="organization", cascade="all, delete-orphan")
    projects: Mapped[list["Project"]] = relationship(back_populates="organization", cascade="all, delete-orphan")


class Membership(Base):
    __tablename__ = "memberships"

    id: Mapped[int] = mapped_column(primary_key=True)
    organization_id: Mapped[int] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(30), default="viewer")  # "owner", "reviewer", "viewer"
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    organization: Mapped[Organization] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="memberships")

    @property
    def user_name(self) -> str:
        return self.user.name if self.user else ""

    @property
    def user_email(self) -> str:
        return self.user.email if self.user else ""



class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=True
    )
    organization_id: Mapped[int | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="CASCADE"), index=True, nullable=True
    )
    name: Mapped[str] = mapped_column(String(200), index=True)
    rfc_text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    owner: Mapped[User | None] = relationship(back_populates="projects")
    organization: Mapped[Organization | None] = relationship(back_populates="projects")
    reviews: Mapped[list["Review"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )
    rfc_versions: Mapped[list["ProjectRfcVersion"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", order_by="ProjectRfcVersion.version_number"
    )


class ProjectRfcVersion(Base):
    __tablename__ = "project_rfc_versions"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, default=1)
    rfc_text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    project: Mapped[Project] = relationship(back_populates="rfc_versions")


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    role: Mapped[str] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text)
    system_prompt: Mapped[str] = mapped_column(Text)


class Review(Base):
    __tablename__ = "reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), index=True
    )
    rfc_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("project_rfc_versions.id", ondelete="SET NULL"), nullable=True
    )
    previous_review_id: Mapped[int | None] = mapped_column(
        ForeignKey("reviews.id", ondelete="SET NULL"), nullable=True
    )
    rfc_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    parsed_sections: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    project: Mapped[Project] = relationship(back_populates="reviews")
    rfc_version: Mapped[ProjectRfcVersion | None] = relationship()
    previous_review: Mapped["Review | None"] = relationship(remote_side=[id])
    findings: Mapped[list["Finding"]] = relationship(
        back_populates="review", cascade="all, delete-orphan", order_by="Finding.id"
    )
    debates: Mapped[list["Debate"]] = relationship(
        back_populates="review", cascade="all, delete-orphan", order_by="Debate.id"
    )
    report: Mapped["FinalReport | None"] = relationship(
        back_populates="review", cascade="all, delete-orphan", uselist=False
    )


class Finding(Base):
    __tablename__ = "findings"

    id: Mapped[int] = mapped_column(primary_key=True)
    review_id: Mapped[int] = mapped_column(
        ForeignKey("reviews.id", ondelete="CASCADE"), index=True
    )
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"), index=True)
    round: Mapped[int] = mapped_column(Integer, default=1)
    category: Mapped[str] = mapped_column(String(100), default="general")
    severity: Mapped[str] = mapped_column(String(20), index=True)
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text)
    recommendation: Mapped[str] = mapped_column(Text)
    tradeoffs: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="open", index=True)
    status_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    quote_valid: Mapped[bool] = mapped_column(Boolean, default=True)

    review: Mapped[Review] = relationship(back_populates="findings")
    agent: Mapped[Agent] = relationship()
    comments: Mapped[list["FindingComment"]] = relationship(
        back_populates="finding", cascade="all, delete-orphan", order_by="FindingComment.id"
    )

    @property
    def agent_name(self) -> str:
        return self.agent.name


class FindingComment(Base):
    __tablename__ = "finding_comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    finding_id: Mapped[int] = mapped_column(
        ForeignKey("findings.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    comment: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    finding: Mapped[Finding] = relationship(back_populates="comments")
    author: Mapped[User] = relationship()

    @property
    def user_name(self) -> str:
        return self.author.name if self.author else "Member"



class Debate(Base):
    __tablename__ = "debates"

    id: Mapped[int] = mapped_column(primary_key=True)
    review_id: Mapped[int] = mapped_column(
        ForeignKey("reviews.id", ondelete="CASCADE"), index=True
    )
    agent_id: Mapped[int] = mapped_column(ForeignKey("agents.id"))
    target_agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id"), nullable=True)
    round: Mapped[int] = mapped_column(Integer, default=1)
    stance: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(Text)

    review: Mapped[Review] = relationship(back_populates="debates")
    agent: Mapped[Agent] = relationship(foreign_keys=[agent_id])
    target_agent: Mapped[Agent | None] = relationship(foreign_keys=[target_agent_id])

    @property
    def agent_name(self) -> str:
        return self.agent.name

    @property
    def target_agent_name(self) -> str | None:
        return self.target_agent.name if self.target_agent else None


class FinalReport(Base):
    __tablename__ = "final_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    review_id: Mapped[int] = mapped_column(
        ForeignKey("reviews.id", ondelete="CASCADE"), unique=True
    )
    decision: Mapped[str] = mapped_column(String(30))
    score: Mapped[int] = mapped_column(Integer)
    summary: Mapped[str] = mapped_column(Text)
    recommendations: Mapped[list] = mapped_column(JSON, default=list)
    key_risks: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    review: Mapped[Review] = relationship(back_populates="report")


class ChatMessage(Base):
    """One message in a person's conversation about a review. Each person has their own thread."""

    __tablename__ = "chat_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    review_id: Mapped[int] = mapped_column(ForeignKey("reviews.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20))  # "user" or "assistant"
    content: Mapped[str] = mapped_column(Text)
    cited_finding_ids: Mapped[list] = mapped_column(JSON, default=list)
    # Status changes the assistant suggested, e.g. {"finding_id": 12, "status": "rejected", "reason": "..."}
    actions: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
