# ArchNexus – Multi-Agent Software Architecture & RFC Review Board

Submit a project name and an RFC; a virtual review board of local LLM agents analyses it,
debates conflicting opinions, and a Judge Agent issues a final decision.

```
RFC → Parser → Agent Orchestrator → Specialized Agents → Debate → Judge Agent → Final Report → PostgreSQL → FastAPI API
```

**Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, PostgreSQL, Ollama (Qwen3), Uvicorn, Pytest.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env

docker compose up -d                 # PostgreSQL
ollama pull qwen3:8b                 # local model (change OLLAMA_MODEL to use another size)
alembic upgrade head                 # create tables
uvicorn app.main:app --reload        # http://localhost:8000/docs
pytest                               # tests use a fake LLM + SQLite, no services needed
```

## Using the API

```bash
# 1. create a project
curl -X POST localhost:8000/projects -H 'content-type: application/json' \
  -d '{"name":"Orders","rfc_text":"# Order Service\n## Architecture\n..."}'

# 2. start a review (runs in the background, returns 202 immediately)
curl -X POST localhost:8000/projects/1/reviews

# 3. poll, then read results
curl localhost:8000/reviews/1                       # status + findings + debates + report
curl 'localhost:8000/reviews/1/findings?severity=critical&agent=Security%20Agent'
curl localhost:8000/reviews/1/debates
curl localhost:8000/reviews/1/report
```

| Method | Path | Purpose |
|---|---|---|
| POST/GET | `/projects` | create / list projects |
| POST | `/projects/upload` | upload & extract text (.pdf, .docx, .md, .txt) |
| GET/PATCH/PUT/DELETE | `/projects/{id}` | fetch / edit RFC / delete |
| POST/GET | `/projects/{id}/reviews` | start / list reviews |
| GET | `/reviews/{id}` | full review (findings, debates, report, comparison) |
| GET | `/reviews/{id}/comparison` | compare findings with previous review |
| GET | `/reviews/{id}/export/markdown` | export review report as Markdown file |
| GET | `/reviews/{id}/export/pdf` | export review report as PDF document |
| GET | `/reviews/{id}/findings` | filter by `severity`, `agent` |
| PATCH/PUT | `/reviews/{id}/findings/{fid}` | update status (Open, Accepted, Rejected w/ reason, Fixed) |
| POST/GET | `/reviews/{id}/findings/{fid}/comments` | post / list comments on a finding |
| GET | `/organizations/me` | list user workspaces/organizations |
| GET | `/organizations/{id}/members` | list organization members and roles |
| POST | `/organizations/{id}/invites` | invite team member by email (owner, reviewer, viewer) |
| GET | `/reviews/{id}/debates` | debate transcript |
| GET | `/reviews/{id}/report` | final decision (409 until ready) |
| GET | `/agents` | the board members |

## How it works

1. **Parser** (`app/parser.py`) splits the RFC by Markdown headings into canonical sections
   (security, data, scalability, …) and flags sections the RFC never covers.
2. **Orchestrator** (`app/orchestrator.py`) – plain Python, no framework – runs the stages:
   - **Parallel Specialist Analysis:** Specialists (Architecture, Security, Database, Scalability, Reliability) run concurrently using a thread pool bounded by `MAX_SPECIALIST_CONCURRENCY` (default 5).
   - **Verbatim Quoted RFC Evidence:** Every specialist finding requires an exact quoted passage from the RFC. Findings with missing or hallucinated passages not present in the RFC are strictly discarded.
   - **Debate rounds** (`DEBATE_ROUNDS`): every agent sees the others' findings and agrees, disagrees or refines; the transcript is stored and fed to the next round.
   - the **Judge Agent & Guardrails:** weighs findings + debate and returns decision / score / summary / recommendations / key risks. Guardrails deterministically enforce score caps (3+ criticals <= 25, 2 criticals <= 40, 1 critical <= 60, 3+ highs <= 70, 1+ highs <= 85) and prepend a factual severity audit summary so verdicts never contradict evidence.
3. **Resilience & Providers:** malformed LLM JSON is retried; invalid individual findings are skipped; one agent failing does not abort the review; if the Judge fails a heuristic verdict is stored. Supports local Ollama models or hosted OpenAI-compatible APIs (e.g. Groq with `llama-3.3-70b-versatile`).

## Workspaces & Collaboration

- Users belong to organizations with role-based permissions (`owner`, `reviewer`, `viewer`).
- Invite team members by email with granular access control.
- Viewers have read-only access with interactive per-finding commenting.
- Reviewers and owners can edit RFCs, launch re-reviews, and update finding statuses.

## Database

`projects` 1─* `reviews` 1─* `findings`, `debates`; `reviews` 1─1 `final_reports`;
`agents` referenced by `findings` and `debates` (speaker + target). Schema is managed by Alembic
(`alembic/versions/0001_initial_schema.py`).

## Adding LangGraph later

Agents only talk to the `LLMClient` protocol (`app/llm.py`) and the stage functions in
`app/agents/base.py`. To move to LangGraph, make each stage (`_analysis_round`, `_debate_rounds`,
`_judge`) a graph node that calls the same `run_*` functions – persistence and API stay unchanged.

## Frontend

Start the server and open <http://127.0.0.1:8000/>. The UI lives in `frontend/` (plain HTML, CSS and JS, no build step) and is served by FastAPI under `/ui`. You can start a review, watch it progress live, and read the verdict, findings, debate and RFC. `GET /reviews` lists recent reviews. API docs stay at `/docs`.

## Accounts

Each person registers with a name, email, password and an optional company name. Projects and reviews belong to the account that created them, and other accounts get "not found" for them. Passwords are hashed with scrypt, and sign-in returns a signed token valid for `TOKEN_EXPIRE_MINUTES` (default 7 days).

Set `SECRET_KEY` in `.env` to a long random value before sharing the app. The default value lets anyone forge a login token.

After pulling this change:

    pip install -r requirements.txt
    alembic upgrade head

Projects created before accounts existed stay in the database but belong to nobody, so no one can see them.

API use: `POST /auth/register` or `POST /auth/login`, then send `Authorization: Bearer <access_token>` on every other call.
