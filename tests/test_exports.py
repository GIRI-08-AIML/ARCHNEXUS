from datetime import datetime, timezone
from types import SimpleNamespace as NS

from pypdf import PdfReader
import io

from app.exports import export_review_markdown, export_review_pdf


def _review():
    now = datetime(2026, 10, 12, 9, 0, tzinfo=timezone.utc)
    finding = NS(
        title="Tokens <never> expire & more", severity="high", agent_name="Security Agent",
        category="auth", status="open", status_reason=None,
        description="Leaked tokens work forever <b>unclosed", recommendation="Expire tokens & rotate",
        tradeoffs=None, quote="Users sign in with tokens that never expire",
    )
    report = NS(decision="reject", score=40, summary="Bad & <risky>", key_risks=["a < b"], recommendations=["fix & go"])
    return NS(id=7, project=NS(name="Orders & <Co>"), project_id=1, created_at=now, completed_at=now,
              status="completed", report=report, findings=[finding])


def test_markdown_export_includes_the_quoted_rfc_passage():
    md = export_review_markdown(_review())
    assert '> RFC says: "Users sign in with tokens that never expire"' in md


def test_pdf_export_survives_special_characters_and_shows_the_quote():
    pdf = export_review_pdf(_review())
    text = "".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(pdf)).pages)
    assert "Tokens <never> expire & more" in text
    assert "RFC says" in text and "never expire" in text
