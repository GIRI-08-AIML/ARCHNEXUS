# ArchNexus: a review board for software architecture RFCs

Paste or upload an RFC. Five specialist AI agents (Architecture, Security, Database, Scalability, Reliability) read it, check each other's work, argue about conflicting advice, and a Judge issues a verdict, a score and a list of changes. Every finding quotes the sentence of the RFC it is about.

```
RFC -> Parser -> 5 specialists (in parallel) -> quote check -> evidence check -> merge duplicates
    -> debate -> Judge -> score rules -> report -> PostgreSQL -> FastAPI + web app + VS Code extension
```

**Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, Alembic, PostgreSQL, pytest. The model is a local one through Ollama, or a hosted one through any OpenAI-compatible API (for example Groq). The web app is plain HTML, CSS and JavaScript with no build step.

## What it does

- Reviews an RFC (pasted, or uploaded as .pdf, .docx, .md or .txt) and shows the verdict, findings by severity, the debate and the RFC itself.
- Drops findings the RFC already answers, and lowers severities the RFC does not justify.
- Accounts for people and companies, workspaces with owner, reviewer and viewer roles, comments and a status workflow on each finding, RFC versions with a comparison between reviews.
- **Ask tab:** a chat assistant answers questions about a finished review ("What should I fix first?", "Why was this rated high?", "Where did the agents disagree?"). Answers come from that review's report, findings, debate and RFC, and cite the findings they use as clickable chips.
- Exports a review as Markdown or PDF.
- A redesigned web app with a score summary, severity bar, colour-coded findings, light and dark mode.
- A VS Code extension reviews the open file and puts each finding on the line it is about.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env                 # then edit it, see "Configuration"

docker compose up -d                 # PostgreSQL
alembic upgrade head                 # create the tables
uvicorn app.main:app --reload        # web app at http://localhost:8000, API docs at /docs
```

Choose a model in `.env`:

- **Local (free, private, slow on a laptop):** `ollama pull qwen3:8b`, then keep `LLM_PROVIDER=ollama`. Small models (for example `qwen3:1.7b`) give poor reviews.
- **Hosted (fast):** set `LLM_PROVIDER=groq`, `LLM_API_KEY`, `LLM_MODEL` and `LLM_BASE_URL`. Model names change, so check the provider's list. A free plan allows few calls per minute: use `MAX_SPECIALIST_CONCURRENCY=2` or `1`.

Before you share the app with anyone, set `SECRET_KEY` to a long random value:
`python -c "import secrets; print(secrets.token_urlsafe(48))"`

## Configuration

All settings are environment variables, or lines in `.env`. `.env.example` lists every one with comments.

| Setting | Default | What it does |
|---|---|---|
| `DATABASE_URL` | local PostgreSQL | Where reviews are stored |
| `SECRET_KEY` | `change-me` | Signs login tokens. Change it. |
| `LLM_PROVIDER` | `ollama` | `ollama`, or `groq` / `openai` for a hosted API |
| `LLM_API_KEY`, `LLM_MODEL`, `LLM_BASE_URL` | Groq | Hosted model settings |
| `OLLAMA_MODEL` | `qwen3:8b` | Local model |
| `MAX_SPECIALIST_CONCURRENCY` | `5` | Agents running at once. Lower it on free cloud plans. |
| `MAX_RFC_CHARS_IN_PROMPT` | `12000` | How much of the RFC the model reads (about 4 pages) |
| `DEBATE_ROUNDS` | `1` | Rounds of agents answering each other |
| `VERIFY_FINDINGS` | `true` | The evidence check below. One extra model call per finding. |
| `LLM_RATE_LIMIT_RETRIES`, `LLM_RATE_LIMIT_MAX_WAIT` | `6`, `60` | How the app waits when the provider says "429 Too Many Requests" |
| `CHAT_MAX_QUESTIONS_PER_HOUR`, `CHAT_MAX_CONTEXT_CHARS` | `30`, `16000` | Questions per person per hour (0 = no limit) and how much of the review is sent with each question |
| `LOGIN_MAX_FAILURES`, `LOGIN_IP_MAX_FAILURES`, `LOGIN_LOCKOUT_SECONDS` | `5`, `20`, `900` | Sign-in lockout, see "Security" |

## How a review works

1. **Parser** (`app/parser.py`) splits the RFC by Markdown headings into sections and notes the ones the RFC never covers.
2. **Specialists** (`app/orchestrator.py`) run in parallel threads. Each follows a strict severity guide: most findings are medium or low, and most RFCs have no critical finding. Each finding must quote the RFC.
3. **Quote check.** A finding whose quote is not in the RFC is discarded, so the models cannot invent evidence.
4. **Evidence check.** One short model call per finding asks: does the RFC already answer this, or say the opposite? If so, the verifier must copy the proving sentence word for word. If it cannot, or if the call fails, the finding is kept. The same call can lower a severity (when the RFC already partly covers the concern, or the problem only appears if you assume something the RFC does not say) but never raise one.
5. **Merge duplicates.** When two agents report the same problem, one finding is kept with the higher rating and a line "Also flagged by the ... Agent". Findings that only quote the same sentence for different problems are not merged. Only the Architecture Agent reports open questions the RFC states.
6. **Debate.** Each agent sees the others' findings and agrees, disagrees or refines. The transcript is stored.
7. **Judge and score rules.** The Judge gives a decision, score and summary, and is told to call only findings rated critical or high high-severity. Rules in code then cap the score (3 or more critical: 25 at most, 2: 40, 1: 60, 3 or more high: 70, any high: 85) and add exact severity counts to the summary, so a verdict cannot contradict its findings.

The summary says what the checks did: how many findings were removed, how many severities lowered, how many duplicates merged, and whether any finding could not be checked because the model did not answer ("Evidence check incomplete").

**Resilience.** Malformed model JSON is retried. One failing agent does not fail the review. If the Judge fails, a rule-based verdict is stored. Provider rate limits are waited out: the app uses the wait the provider asks for, or backs off 5, 10, 20 ... seconds. A wait longer than a minute usually means a daily limit, so the call then fails with a clear message. Error messages include what the provider said, so a retired model name shows as "model does not exist" instead of a bare 404.

## Using the API

Sign in first (`POST /auth/register` or `POST /auth/login`), then send `Authorization: Bearer <access_token>` on every other call.

```bash
curl -X POST localhost:8000/projects -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"name":"Orders","rfc_text":"# Order Service\n## Architecture\n..."}'
curl -X POST localhost:8000/projects/1/reviews -H "Authorization: Bearer $TOKEN"   # starts a review, returns 202
curl localhost:8000/reviews/1 -H "Authorization: Bearer $TOKEN"                    # poll: status, findings, debates, report
```

| Method | Path | Purpose |
|---|---|---|
| POST | `/auth/register`, `/auth/login` | Create an account / sign in |
| GET | `/auth/me` | The signed-in user |
| POST/GET | `/projects` | Create / list projects |
| POST | `/projects/upload` | Upload and extract text (.pdf, .docx, .md, .txt) |
| GET/PATCH/PUT/DELETE | `/projects/{id}` | Fetch / edit the RFC / delete |
| POST/GET | `/projects/{id}/reviews` | Start / list reviews |
| GET | `/reviews` | List your reviews |
| GET | `/reviews/{id}` | Full review: findings, debates, report, comparison |
| GET | `/reviews/{id}/comparison` | Compare findings with the previous review |
| GET | `/reviews/{id}/findings` | Filter by `severity`, `agent` |
| PATCH/PUT | `/reviews/{id}/findings/{fid}` | Set status: open, accepted, rejected (with a reason), fixed |
| POST/GET | `/reviews/{id}/findings/{fid}/comments` | Comment on a finding |
| GET | `/reviews/{id}/debates`, `/reviews/{id}/report` | Debate transcript / final decision |
| GET | `/reviews/{id}/export/markdown`, `/export/pdf` | Download the report |
| GET | `/organizations/me`, `/organizations/{id}/members` | Workspaces and members |
| POST | `/organizations/{id}/invites` | Invite a member as owner, reviewer or viewer |
| GET/POST/DELETE | `/reviews/{id}/chat` | Your conversation about a review / ask a question / clear it |
| POST | `/reviews/{id}/chat/stream` | Ask a question and receive the answer piece by piece (server-sent events) |
| GET | `/agents` | The board members |

## Asking questions about a review

Open a finished review and choose **Ask**. Each question sends the model the report, the findings (with the RFC sentence each quotes), the debate, the comparison with the previous review and the RFC sections that match the question, plus your last few messages so follow-ups work. The assistant is told to use only that data, to cite findings as `[#id]`, to label general engineering advice as such, and to say so when the review does not cover something. Citations of findings that do not exist are removed before you see the answer. Large reviews are shortened (least serious and least relevant findings first) to stay inside small token limits.

**Streaming.** The web app shows the answer as it is written. **Suggested changes.** If you ask the assistant to accept, reject or mark a finding as fixed, it explains its suggestion and shows an **Apply** button. Nothing changes until you click it, and your workspace role still decides whether you are allowed to change statuses.

Conversations are private to each person and can be cleared. They need a finished review and cost one model call per question, so on a free hosted plan a question can hit the per-minute limit; the app says so and you ask again.

## Accounts, workspaces and security

- A person registers with a name, email, password and an optional company. Passwords are hashed with scrypt, and sign-in returns a signed token valid for `TOKEN_EXPIRE_MINUTES` (default 7 days).
- Projects and reviews belong to the account that made them. Other accounts get "not found". Workspaces have owners (full control), reviewers (edit RFCs, start reviews, change statuses) and viewers (read and comment).
- **Sign-in lockout.** After 5 wrong passwords for one account from one address, further attempts get "429 Too many failed sign-in attempts" for 15 minutes, even with the right password. 20 failures from one address across any accounts also lock that address. A stranger cannot lock you out from another address. The counters live in the server's memory: they reset on a restart, and each server process counts separately. Behind a reverse proxy, make sure it passes the real client address.
- **Privacy.** The RFC text is sent to whichever model you configure. With a hosted provider, that is a third party. Use a local model for confidential RFCs.
- Not built yet: password reset, email verification, per-user usage limits.

After pulling changes that touch the database, run `pip install -r requirements.txt` and `alembic upgrade head`.

## VS Code extension

The `vscode-extension/` folder holds an extension that reviews the file you are editing. See its [README](vscode-extension/README.md). In short: start the server, install the `.vsix`, run **ArchNexus: Review this RFC**, and each finding appears in the Problems panel on the line of the RFC it quotes.

## Testing

```bash
pytest                         # about 85 tests; they use a fake model and SQLite, so no services are needed
python scripts/check_verifier.py   # runs the evidence check against YOUR model: 8 cases, a good model scores 8/8
cd vscode-extension && npm test    # the extension's helper tests (needs Node 20 or newer)
```

`check_verifier.py` matters: the evidence check is only as good as the model behind it. A tiny model may fail it. If the model does not answer (for example a rate limit), the script reports those cases as errors instead of passes.

## Project layout

```
app/              FastAPI app: routers/, orchestrator.py, agents/, llm.py, parser.py, exports.py, security, login_limiter.py
alembic/          database migrations
frontend/         the web app (served by FastAPI)
scripts/          check_verifier.py
tests/            pytest suite (tests/fixtures holds findings from two real reviews)
vscode-extension/ the VS Code extension
```

Database: `projects` 1-* `reviews` 1-* `findings`, `debates`; `reviews` 1-1 `final_reports`; `agents` referenced by findings and debates. Schema changes are Alembic migrations.

## Known limits

- Only the first `MAX_RFC_CHARS_IN_PROMPT` characters of an RFC are read (about 4 pages by default).
- Reviews run inside the web server process. A restart marks running reviews as failed, and there is no job queue.
- The model is an AI reviewer: scores vary a few points between runs of the same RFC, and some findings are judgment calls. Treat it as a second opinion.
- The assistant can be wrong, like the reviewers: it only sees a trimmed copy of the review, and the question limit lives in server memory.
- Free hosted plans limit tokens per minute and per day, so a review can take several minutes and only a few fit in a day.
