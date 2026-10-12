"""Check the evidence verifier against YOUR configured model (Ollama or Groq).

Run from the project folder:   python scripts/check_verifier.py

It feeds a small RFC and six findings to the same verifier the app uses. Four findings are
wrong (the RFC already answers them) and two are real gaps. A good model removes the four and
keeps the two. Nothing is written to the database.
"""
import sys
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.llm import get_llm  # noqa: E402
from app.orchestrator import ReviewOrchestrator  # noqa: E402

RFC = """RFC-002: Notification Service
Callers send a request to the Notification API, which validates it, stores it in PostgreSQL, and puts a job on a durable queue.
Each request carries a caller-supplied idempotency key with a unique index, so a retry returns the original result instead of sending again.
User contact details are encrypted at rest.
Services authenticate to the API with short-lived tokens that expire after 15 minutes and are renewed automatically. The API enforces a per-caller rate limit.
Delivery calls use a 5 second timeout and up to five retries with exponential backoff. Messages that still fail go to a dead-letter queue, and an alert fires when it is not empty.
The database takes a nightly backup and continuous log archiving, and we test a restore every quarter.
Open question: how we handle time zones for quiet hours is not yet decided."""

CASES = [
    ("Contact details stored in plain text", "Contact details are not encrypted.", "Encrypt them.", False),
    ("Retries can send duplicates", "Retries are not checked for duplicates.", "Add a duplicate check.", False),
    ("Backup and restore not tested", "Restore is never tested.", "Test restores.", False),
    ("No rate limiting for callers", "There is no rate limit.", "Add a per-caller rate limit.", False),
    ("Quiet-hours time zone undecided", "The RFC does not decide how time zones work for quiet hours.", "Decide it.", True),
    ("No cost estimate", "The RFC never estimates what delivery will cost.", "Add a cost estimate.", True),
]


def main() -> int:
    s = get_settings()
    print(f"Provider: {s.llm_provider}   Model: {s.llm_model if s.llm_provider != 'ollama' else s.ollama_model}\n")
    orch = ReviewOrchestrator(None, get_llm(), s)
    correct = 0
    errors = 0
    for title, desc, rec, should_keep in CASES:
        d = NS(title=title, description=desc, recommendation=rec)
        failed_before = len(orch.unverified)
        reason = orch._verify_finding("check", RFC, d)
        if len(orch.unverified) > failed_before:
            # The model call failed, so the finding was kept by default. That proves nothing either way.
            errors += 1
            print(f"[ERROR] model call failed, not counted  {title}")
            continue
        kept = reason is None
        ok = kept == should_keep
        correct += ok
        print(f"[{'PASS' if ok else 'FAIL'}] {'kept   ' if kept else 'removed'}  {title}" + (f"\n         because: {reason}" if reason else ""))
    print(f"\n{correct}/{len(CASES)} correct")
    if errors:
        print(f"{errors} case(s) could not be checked because the model did not answer. Wait a minute and run it again.")
    return 0 if correct == len(CASES) else 1


if __name__ == "__main__":
    raise SystemExit(main())
