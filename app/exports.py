"""Export review reports to Markdown and PDF formats."""
import io
from xml.sax.saxutils import escape as _esc
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors


def _x(value) -> str:
    """Escape model-written text so characters like < and & cannot break the PDF layout."""
    return _esc(str(value if value is not None else ""))


def export_review_markdown(review) -> str:
    """Export review report and findings as GitHub-flavored Markdown."""
    lines = []
    proj_name = review.project.name if review.project else f"Project {review.project_id}"
    lines.append(f"# Review Report: {proj_name}")
    lines.append(f"**Review ID:** #{review.id}  ")
    lines.append(f"**Created:** {review.created_at.strftime('%Y-%m-%d %H:%M UTC')}  ")
    if review.completed_at:
        lines.append(f"**Completed:** {review.completed_at.strftime('%Y-%m-%d %H:%M UTC')}  ")
    lines.append("")

    report = getattr(review, "report", None)
    if report:
        lines.append("## Executive Decision")
        lines.append(f"- **Decision:** {report.decision.upper().replace('_', ' ')}")
        lines.append(f"- **Score:** {report.score}/100")
        lines.append("")
        lines.append("### Summary")
        lines.append(report.summary or "None provided.")
        lines.append("")

        if report.key_risks:
            lines.append("### Key Risks")
            for risk in report.key_risks:
                lines.append(f"- {risk}")
            lines.append("")

        if report.recommendations:
            lines.append("### Recommendations")
            for i, rec in enumerate(report.recommendations, 1):
                lines.append(f"{i}. {rec}")
            lines.append("")
    else:
        lines.append("## Status")
        lines.append(f"Review status: {review.status.upper()}")
        lines.append("")

    findings = getattr(review, "findings", [])
    lines.append(f"## Findings ({len(findings)})")
    if not findings:
        lines.append("_No findings reported._\n")
    else:
        for f in findings:
            status_tag = f" [{f.status.upper()}]" if getattr(f, "status", None) else ""
            lines.append(f"### {f.title}{status_tag}")
            lines.append(f"**Severity:** {f.severity.upper()} | **Agent:** {f.agent_name} | **Category:** {f.category}  ")
            if getattr(f, "status_reason", None):
                lines.append(f"**Status Reason:** _{f.status_reason}_  ")
            lines.append("")
            if getattr(f, "quote", None):
                lines.append(f"> RFC says: \"{f.quote}\"\n")
            lines.append(f"**Problem:**  \n{f.description}\n")
            lines.append(f"**Recommendation:**  \n{f.recommendation}\n")
            if f.tradeoffs:
                lines.append(f"**Trade-offs:**  \n{f.tradeoffs}\n")
            lines.append("---")
            lines.append("")

    return "\n".join(lines)


def export_review_pdf(review) -> bytes:
    """Generate a clean, styled PDF document for a review."""
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=40,
        leftMargin=40,
        topMargin=40,
        bottomMargin=40,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Heading1"],
        fontSize=22,
        leading=26,
        textColor=colors.HexColor("#1d1d1f"),
    )
    h2_style = ParagraphStyle(
        "ReportH2",
        parent=styles["Heading2"],
        fontSize=15,
        leading=18,
        textColor=colors.HexColor("#0071e3"),
        spaceBefore=14,
        spaceAfter=6,
    )
    body_style = ParagraphStyle(
        "ReportBody",
        parent=styles["Normal"],
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#333333"),
    )
    bold_style = ParagraphStyle(
        "ReportBold",
        parent=body_style,
        fontName="Helvetica-Bold",
    )

    elements = []

    proj_name = review.project.name if review.project else f"Project {review.project_id}"
    elements.append(Paragraph(f"ArchNexus Review: {_x(proj_name)}", title_style))
    elements.append(Spacer(1, 6))

    meta_text = f"Review #{review.id} | Date: {review.created_at.strftime('%Y-%m-%d %H:%M UTC')}"
    elements.append(Paragraph(meta_text, body_style))
    elements.append(Spacer(1, 14))

    report = getattr(review, "report", None)
    if report:
        elements.append(Paragraph("Executive Verdict", h2_style))
        score_data = [
            [
                Paragraph("<b>Verdict:</b> " + report.decision.upper().replace("_", " "), body_style),
                Paragraph(f"<b>Score:</b> {report.score} / 100", bold_style),
            ]
        ]
        score_table = Table(score_data, colWidths=[280, 240])
        score_table.setStyle(
            TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f5f5f7")),
                ("PADDING", (0, 0), (-1, -1), 8),
                ("BOX", (0, 0), (-1, -1), 0.5, colors.HexColor("#e0e0e0")),
            ])
        )
        elements.append(score_table)
        elements.append(Spacer(1, 10))

        elements.append(Paragraph("<b>Summary:</b> " + _x(report.summary), body_style))
        elements.append(Spacer(1, 10))

        if report.key_risks:
            elements.append(Paragraph("Key Risks", h2_style))
            for r in report.key_risks:
                elements.append(Paragraph("• " + _x(r), body_style))
            elements.append(Spacer(1, 8))

        if report.recommendations:
            elements.append(Paragraph("Recommendations", h2_style))
            for i, rec in enumerate(report.recommendations, 1):
                elements.append(Paragraph(f"{i}. {_x(rec)}", body_style))
            elements.append(Spacer(1, 8))

    findings = getattr(review, "findings", [])
    elements.append(Paragraph(f"Findings ({len(findings)})", h2_style))
    elements.append(Spacer(1, 6))

    for f in findings:
        status_str = f" [{f.status.upper()}]" if getattr(f, "status", None) else ""
        elements.append(
            Paragraph(f"<b>{_x(f.title)}{status_str}</b> ({_x(f.severity.upper())} · {_x(f.agent_name)})", bold_style)
        )
        if getattr(f, "quote", None):
            elements.append(Paragraph("<b>RFC says:</b> <i>\u201c" + _x(f.quote) + "\u201d</i>", body_style))
        elements.append(Paragraph("<b>Problem:</b> " + _x(f.description), body_style))
        elements.append(Paragraph("<b>Suggested Fix:</b> " + _x(f.recommendation), body_style))
        if f.tradeoffs:
            elements.append(Paragraph("<b>Trade-offs:</b> " + _x(f.tradeoffs), body_style))
        if getattr(f, "status_reason", None):
            elements.append(Paragraph("<b>Status Reason:</b> " + _x(f.status_reason), body_style))
        elements.append(Spacer(1, 8))

    doc.build(elements)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes
