import os

# Must be set before `app` is imported so no Postgres driver/connection is needed.
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["SECRET_KEY"] = "test-secret-key-that-is-long-enough-for-hs256"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.dependencies import get_db, get_llm, get_session_factory
from app.llm import LLMError
from app.main import app

SAMPLE_RFC = """# Order Service RFC

We propose a new order service to replace the legacy monolith checkout flow.

## Requirements
Handle 500 orders per second at peak. Orders must never be lost. Support card payments.

## Architecture
A single FastAPI service writes orders to PostgreSQL and publishes events to Kafka.
The payment provider is called synchronously from the order endpoint.

## Security
Users authenticate with JWT tokens that do not expire. Card numbers are stored in the orders table.

## Data
One orders table with a JSON column for line items. No indexes beyond the primary key.
"""


# One distinct sentence per agent, so the five fake findings are five different problems (not duplicates).
FAKE_QUOTES = {
    "Architecture Agent": "A single FastAPI service writes orders",
    "Security Agent": "JWT tokens that do not expire",
    "Database Agent": "One orders table with a JSON column for line items",
    "Scalability Agent": "Handle 500 orders per second at peak",
    "Reliability Agent": "The payment provider is called synchronously",
}


class FakeLLM:
    """Deterministic stand-in for Ollama. Dispatches on the TASK marker in the prompt."""

    def __init__(self, fail_judge: bool = False, fail_all: bool = False, verify_rules: dict | None = None,
                 fail_verify: bool = False):
        self.fail_judge = fail_judge
        self.fail_all = fail_all
        self.fail_verify = fail_verify
        # finding title -> verifier answer; any finding not listed is judged valid
        self.verify_rules = verify_rules or {}
        self.calls: list[str] = []

    def chat_json(self, messages):
        user = messages[-1]["content"]
        task = user.split("\n", 1)[0]
        self.calls.append(task)
        if self.fail_all:
            raise LLMError("boom")
        if task.startswith("TASK: ANALYSIS"):
            who = messages[0]["content"].split(" on a software")[0].replace("You are the ", "")
            return {
                "findings": [
                    {
                        "category": "demo",
                        "severity": "critical" if who == "Security Agent" else "medium",
                        "title": f"{who} finding",
                        "quote": FAKE_QUOTES[who],
                        "description": "d",
                        "recommendation": "r",
                        "tradeoffs": None,
                    },
                    {"title": "missing fields"},  # malformed -> skipped
                ]
            }
        if task.startswith("TASK: VERIFY"):
            if self.fail_verify:
                raise LLMError("verifier down")
            for title, answer in self.verify_rules.items():
                if f"Finding title: {title}\n" in user:
                    return answer
            return {"verdict": "valid", "evidence": "", "reason": "ok"}
        if task.startswith("TASK: DEBATE"):
            who = messages[0]["content"].split(" on a software")[0].replace("You are the ", "")
            target = "Security Agent" if who != "Security Agent" else "Database Agent"
            return {"responses": [{"target_agent": target, "stance": "Disagree", "message": "m"}]}
        if task.startswith("TASK: JUDGE"):
            if self.fail_judge:
                raise LLMError("judge down")
            return {
                "decision": "Reject",
                "score": "35",
                "summary": "Not ready.",
                "recommendations": ["Fix auth", {"priority": "high", "action": "Add indexes"}],
                "key_risks": ["Token theft"],
            }
        raise AssertionError(f"unexpected task {task}")


@pytest.fixture(autouse=True)
def _fresh_login_limiter():
    """Failed-login counters live in memory, so start every test with a clean slate."""
    from app.login_limiter import login_limiter

    login_limiter.clear()
    yield
    login_limiter.clear()


@pytest.fixture
def session_factory():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@pytest.fixture
def db(session_factory):
    with session_factory() as session:
        yield session


@pytest.fixture
def fake_llm():
    return FakeLLM()


@pytest.fixture
def client(session_factory, fake_llm):
    def _db():
        with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_session_factory] = lambda: session_factory
    app.dependency_overrides[get_llm] = lambda: fake_llm
    c = TestClient(app)
    c.headers.update(register_user(c, "alice@example.com"))
    yield c
    app.dependency_overrides.clear()


def register_user(client, email, name="Alice", company="Acme", password="correct-horse-1"):
    """Create an account and return the Authorization header for it."""
    r = client.post(
        "/auth/register",
        json={"name": name, "company": company, "email": email, "password": password},
    )
    assert r.status_code == 201, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}
