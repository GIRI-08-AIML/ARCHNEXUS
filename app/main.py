import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.database import SessionLocal
from app.orchestrator import fail_interrupted_reviews, seed_agents
from app.config import get_settings
from app.routers import auth, chat, organizations, projects, reviews

logger = logging.getLogger(__name__)

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    if get_settings().secret_key == "change-me":
        logger.warning("SECRET_KEY is the default. Set a long random value in .env before sharing this app.")
    try:
        with SessionLocal() as db:
            seed_agents(db)
            cleaned = fail_interrupted_reviews(db)
            if cleaned:
                logger.warning("Marked %d interrupted review(s) as failed", cleaned)
    except Exception as exc:  # noqa: BLE001 - app should still boot; run `alembic upgrade head`
        logger.warning("Could not seed agents (did you run migrations?): %s", exc)
    yield


app = FastAPI(
    title="ArchNexus",
    description="Multi-Agent Software Architecture & RFC Review Board",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(auth.router)
app.include_router(organizations.router)
app.include_router(projects.router)
app.include_router(reviews.router)
app.include_router(chat.router)



@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok"}


if FRONTEND_DIR.is_dir():
    app.mount("/ui", StaticFiles(directory=FRONTEND_DIR), name="ui")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(FRONTEND_DIR / "index.html")
