"""Ask questions about a finished review. Each person has their own conversation per review."""
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.chat import build_messages, clean_answer
from app.config import get_settings
from app.dependencies import get_current_user, get_db, get_llm, get_session_factory
from app.llm import LLMClient, LLMError
from app.models import ChatMessage, User
from app.rate_window import chat_limiter
from app.routers.reviews import _build_comparison, _get_review
from app.schemas import ChatExchange, ChatMessageRead, ChatRequest

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])


def _history(db: Session, review_id: int, user_id: int, limit: int | None = None) -> list[ChatMessage]:
    stmt = select(ChatMessage).where(ChatMessage.review_id == review_id, ChatMessage.user_id == user_id)
    if limit:
        rows = db.scalars(stmt.order_by(ChatMessage.id.desc()).limit(limit)).all()
        return list(reversed(rows))
    return list(db.scalars(stmt.order_by(ChatMessage.id)).all())


@router.get("/reviews/{review_id}/chat", response_model=list[ChatMessageRead])
def get_chat(review_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _get_review(db, review_id, user)
    return _history(db, review_id, user.id)


def _prepare(db: Session, review_id: int, payload: ChatRequest, user: User):
    """Checks shared by both ways of asking. Returns (messages for the model, valid finding ids, limiter key)."""
    review = _get_review(db, review_id, user)
    if review.status != "completed":
        raise HTTPException(status.HTTP_409_CONFLICT, "You can ask questions once the review has finished.")
    s = get_settings()
    if len(payload.message) > s.chat_max_question_chars:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Please keep the question under {s.chat_max_question_chars} characters.",
        )

    key = f"chat|{user.id}"
    wait = chat_limiter.try_hit(key, s.chat_max_questions_per_hour, 3600)
    if wait:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"You have asked a lot of questions this hour. Try again in {max(1, wait // 60)} minute(s).",
            headers={"Retry-After": str(wait)},
        )

    history = _history(db, review_id, user.id, limit=s.chat_history_messages)
    messages = build_messages(
        review, review.project.name, history, payload.message, _build_comparison(db, review), s
    )
    return messages, {f.id for f in review.findings}, key


def _friendly(exc: Exception) -> str:
    if "rate limit" in str(exc).lower():
        return "The AI provider's rate limit was reached. Wait a minute and ask again."
    return "The AI model didn't answer. Check that it is running, then try again."


def _save_exchange(db: Session, review_id: int, user_id: int, question: str, raw: str, valid_ids: set[int]) -> ChatExchange:
    text, cited, actions = clean_answer(raw, valid_ids)
    q = ChatMessage(review_id=review_id, user_id=user_id, role="user", content=question)
    a = ChatMessage(
        review_id=review_id, user_id=user_id, role="assistant", content=text,
        cited_finding_ids=cited, actions=actions,
    )
    db.add_all([q, a])
    db.commit()
    db.refresh(q)
    db.refresh(a)
    return ChatExchange(question=ChatMessageRead.model_validate(q), answer=ChatMessageRead.model_validate(a))


@router.post("/reviews/{review_id}/chat", response_model=ChatExchange)
def ask(
    review_id: int,
    payload: ChatRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    llm: LLMClient = Depends(get_llm),
):
    messages, valid_ids, key = _prepare(db, review_id, payload, user)
    try:
        raw = llm.chat_text(messages)
    except LLMError as exc:
        chat_limiter.undo(key)  # a failed answer should not use up the person's allowance
        logger.warning("Chat answer failed for review %s: %s", review_id, exc)
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, _friendly(exc)) from exc
    return _save_exchange(db, review_id, user.id, payload.message, raw, valid_ids)


def _event(obj: dict) -> str:
    return "data: " + json.dumps(obj) + "\n\n"


@router.post("/reviews/{review_id}/chat/stream")
def ask_stream(
    review_id: int,
    payload: ChatRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    llm: LLMClient = Depends(get_llm),
    session_factory: sessionmaker = Depends(get_session_factory),
):
    """Same as POST /chat, but the answer arrives piece by piece as server-sent events.

    Events: {"type":"delta","text":...} repeatedly, then {"type":"done","question":...,"answer":...},
    or {"type":"error","message":...}. Problems found before the answer starts are normal HTTP errors.
    """
    messages, valid_ids, key = _prepare(db, review_id, payload, user)
    user_id, question = user.id, payload.message

    def generate():
        parts: list[str] = []
        try:
            pieces = llm.stream_text(messages) if hasattr(llm, "stream_text") else iter([llm.chat_text(messages)])
            for piece in pieces:
                parts.append(piece)
                yield _event({"type": "delta", "text": piece})
            raw = "".join(parts).strip()
            if not raw:
                raise LLMError("the model returned an empty reply")
        except LLMError as exc:
            chat_limiter.undo(key)
            logger.warning("Chat answer failed for review %s: %s", review_id, exc)
            yield _event({"type": "error", "message": _friendly(exc)})
            return
        with session_factory() as s:
            exchange = _save_exchange(s, review_id, user_id, question, raw, valid_ids)
        yield _event({"type": "done", **exchange.model_dump(mode="json")})

    return StreamingResponse(
        generate(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.delete("/reviews/{review_id}/chat", status_code=status.HTTP_204_NO_CONTENT)
def clear_chat(review_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _get_review(db, review_id, user)
    db.execute(delete(ChatMessage).where(ChatMessage.review_id == review_id, ChatMessage.user_id == user.id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
