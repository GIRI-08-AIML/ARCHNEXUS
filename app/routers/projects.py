from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from app.documents import DocumentExtractError, extract_document_text
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.dependencies import get_current_user, get_db, get_llm, get_session_factory
from app.llm import LLMClient
from app.models import Project, ProjectRfcVersion, Review, User
from app.orchestrator import run_review_job
from app.parser import RFCParseError, parse_rfc
from app.schemas import ProjectCreate, ProjectDetail, ProjectRead, ProjectUpdate, ReviewRead

router = APIRouter(prefix="/projects", tags=["projects"])


from app.workspaces import (
    check_project_access,
    ensure_user_organization,
    get_user_org_ids,
)


def _get_project(db: Session, project_id: int, user: User, min_role: str = "viewer") -> Project:
    project = db.get(Project, project_id)
    check_project_access(db, project, user, min_role=min_role)
    return project


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
):
    """Extract and validate text from .pdf, .docx, .md, or .txt file."""
    try:
        content = await file.read()
        extracted = extract_document_text(file.filename or "document.txt", content)
        return {"filename": file.filename, "text": extracted}
    except DocumentExtractError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Upload processing error: {exc}") from exc


@router.post("", response_model=ProjectDetail, status_code=status.HTTP_201_CREATED)
def create_project(
    payload: ProjectCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        parse_rfc(payload.name, payload.rfc_text)  # fail fast on unreviewable RFCs
    except RFCParseError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    # Ensure user has an organization and assign project to it
    org = ensure_user_organization(db, user)
    project = Project(
        user_id=user.id,
        organization_id=org.id,
        name=payload.name,
        rfc_text=payload.rfc_text,
    )
    db.add(project)
    db.commit()
    db.refresh(project)

    # Initial version
    v1 = ProjectRfcVersion(project_id=project.id, version_number=1, rfc_text=payload.rfc_text)
    db.add(v1)
    db.commit()
    db.refresh(project)
    return project


@router.put("/{project_id}", response_model=ProjectDetail)
@router.patch("/{project_id}", response_model=ProjectDetail)
def update_project(
    project_id: int,
    payload: ProjectUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    # Reviewer or owner can edit RFC
    project = _get_project(db, project_id, user, min_role="reviewer")
    changed_rfc = False
    if payload.name is not None and payload.name.strip():
        project.name = payload.name.strip()
    if payload.rfc_text is not None and payload.rfc_text.strip() and payload.rfc_text != project.rfc_text:
        try:
            parse_rfc(project.name, payload.rfc_text)
        except RFCParseError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
        project.rfc_text = payload.rfc_text
        changed_rfc = True

    db.commit()

    if changed_rfc:
        latest_v = db.scalar(
            select(ProjectRfcVersion.version_number)
            .where(ProjectRfcVersion.project_id == project.id)
            .order_by(ProjectRfcVersion.version_number.desc())
        ) or 0
        new_v = ProjectRfcVersion(
            project_id=project.id,
            version_number=latest_v + 1,
            rfc_text=project.rfc_text,
        )
        db.add(new_v)
        db.commit()

    db.refresh(project)
    return project


@router.get("", response_model=list[ProjectRead])
def list_projects(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    org_ids = get_user_org_ids(db, user.id)
    # Return projects belonging to user's organizations, or owned by user directly
    stmt = (
        select(Project)
        .where(
            (Project.organization_id.in_(org_ids)) | (Project.user_id == user.id)
        )
        .order_by(Project.id.desc())
    )
    return db.scalars(stmt).all()


@router.get("/{project_id}", response_model=ProjectDetail)
def get_project(
    project_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    return _get_project(db, project_id, user, min_role="viewer")


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(
    project_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    # Only owner can delete project
    project = _get_project(db, project_id, user, min_role="owner")
    db.delete(project)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{project_id}/reviews", response_model=ReviewRead, status_code=status.HTTP_202_ACCEPTED
)
def start_review(
    project_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    llm: LLMClient = Depends(get_llm),
    session_factory: sessionmaker = Depends(get_session_factory),
):
    """Create a review and run the multi-agent pipeline in the background. Viewers cannot start reviews."""
    project = _get_project(db, project_id, user, min_role="reviewer")


    # Link to latest RFC version (or create one if legacy project)
    latest_v = db.scalars(
        select(ProjectRfcVersion)
        .where(ProjectRfcVersion.project_id == project.id)
        .order_by(ProjectRfcVersion.version_number.desc())
    ).first()
    if not latest_v:
        latest_v = ProjectRfcVersion(
            project_id=project.id, version_number=1, rfc_text=project.rfc_text
        )
        db.add(latest_v)
        db.commit()
        db.refresh(latest_v)

    # Link to previous completed review if any
    prev_review = db.scalars(
        select(Review)
        .where(Review.project_id == project.id, Review.status == "completed")
        .order_by(Review.id.desc())
    ).first()

    review = Review(
        project_id=project.id,
        rfc_version_id=latest_v.id,
        rfc_text=project.rfc_text,
        previous_review_id=prev_review.id if prev_review else None,
        status="pending",
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    background_tasks.add_task(run_review_job, review.id, session_factory, llm)
    return review


@router.get("/{project_id}/reviews", response_model=list[ReviewRead])
def list_reviews(
    project_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    _get_project(db, project_id, user)
    return db.scalars(
        select(Review).where(Review.project_id == project_id).order_by(Review.id.desc())
    ).all()
