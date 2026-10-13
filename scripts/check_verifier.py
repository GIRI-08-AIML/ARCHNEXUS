"""Check the evidence verifier against YOUR configured model (Ollama or Groq).

Run from the project folder:   python scripts/check_verifier.py

It feeds a small RFC and eight findings to the same verifier the app uses. Four findings are
wrong (the RFC already answers them) and should be removed. Two are real gaps and should be kept.
One is rated "critical" but the RFC already partly covers it, so its severity should be lowered.
One is a real, serious gap and should keep its "high" rating. Nothing is written to the database.
"""
import sys
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.llm import get_llm  # noqa: E402
from app.orchestrator import ReviewOrchestrator  # noqa: E402
from app.schemas import Severity  # noqa: E402

RFC = """RFC-002: Notification Service
Callers send a request to the Notification API, which validates it, stores it in PostgreSQL, and puts a job on a durable queue.
Each request carries a caller-supplied idempotency key with a unique index, so a retry returns the original result instead of sending again.
User contact details are encrypted at rest.
Requests are stored in a single PostgreSQL instance with no standby.
Services authenticate to the API with short-lived tokens that expire after 15 minutes and are renewed automatically. The API enforces a per-caller rate limit.
Delivery calls use a 5 second timeout and up to five retries with exponential backoff. Messages that still fail go to a dead-letter queue, and an alert fires when it is not empty.
The database takes a nightly backup and continuous log archiving, and we test a restore every quarter.
Open question: how we handle time zones for quiet hours is not yet decided."""

# (title, description, recommendation, severity as given, what a good model does)
#   removed   -> the RFC answers it, so the finding is dropped
#   kept      -> a real gap, so the finding stays
#   lowered   -> kept, but with a lower severity than it was given
#   kept_high -> kept and still rated high or critical
CASES = [
    ("Contact details stored in plain text", "Contact details are not encrypted.", "Encrypt them.", "high", "removed"),
    ("Retries can send duplicates", "Retries are not checked for duplicates.", "Add a duplicate check.", "high", "removed"),
    ("Backup and restore not tested", "Restore is never tested.", "Test restores.", "medium", "removed"),
    ("No rate limiting for callers", "There is no rate limit.", "Add a per-caller rate limit.", "medium", "removed"),
    ("Quiet-hours time zone undecided", "The RFC does not decide how time zones work for quiet hours.", "Decide it.", "medium", "kept"),
    ("No cost estimate", "The RFC never estimates what delivery will cost.", "Add a cost estimate.", "medium", "kept"),
    (
        "No way to revoke a stolen service token",
        "If a service token is stolen it stays valid until it expires and nothing can revoke it.",
        "Add a token revocation endpoint.",
        "critical",
        "lowered",
    ),
    (
        "Database is a single point of failure",
        "Everything is stored in one PostgreSQL instance with no standby, so if it fails the service stops.",
        "Add a standby with automatic failover.",
        "high",
        "kept_high",
    ),
]


def main() -> int:
    s = get_settings()
    print(f"Provider: {s.llm_provider}   Model: {s.llm_model if s.llm_provider != 'ollama' else s.ollama_model}\n")
    orch = ReviewOrchestrator(None, get_llm(), s)
    correct = 0
    errors = 0
    for title, desc, rec, given, expected in CASES:
        d = NS(title=title, description=desc, recommendation=rec, severity=Severity(given))
        failed_before = len(orch.unverified)
        check = orch._verify_finding("check", RFC, d)
        if len(orch.unverified) > failed_before:
            # The model call failed, so the finding was kept by default. That proves nothing either way.
            errors += 1
            print(f"[ERROR] model call failed, not counted  {title}")
            continue
        removed = check.remove_reason is not None
        final = str(check.severity or given)
        if expected == "removed":
            ok = removed
        elif expected == "kept":
            ok = not removed
        elif expected == "lowered":
            ok = not removed and final != given
        else:  # kept_high
            ok = not removed and final in ("high", "critical")
        correct += ok
        outcome = "removed" if removed else f"kept, severity {given}" + (f" -> {final}" if final != given else "")
        print(f"[{'PASS' if ok else 'FAIL'}] {outcome:<28} {title}" + (f"\n         because: {check.remove_reason}" if removed else ""))
    print(f"\n{correct}/{len(CASES)} correct")
    if errors:
        print(f"{errors} case(s) could not be checked because the model did not answer. Wait a minute and run it again.")
    return 0 if correct == len(CASES) else 1


if __name__ == "__main__":
    raise SystemExit(main())
