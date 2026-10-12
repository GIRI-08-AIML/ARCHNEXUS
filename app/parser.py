"""RFC parser: turns raw Markdown/plain text into canonical, labelled sections."""
import re
from dataclasses import dataclass, field


class RFCParseError(ValueError):
    pass


HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$", re.MULTILINE)

# Order matters: the first category whose keyword appears in a heading wins.
SECTION_KEYWORDS: dict[str, tuple[str, ...]] = {
    "security": ("security", "auth", "privacy", "compliance", "threat", "encryption"),
    "scalability": ("scal", "performance", "capacity", "load", "throughput", "latency"),
    "reliability": (
        "reliab", "availability", "failure", "resilien", "disaster",
        "monitor", "observab", "slo", "backup",
    ),
    "data": ("data", "database", "storage", "schema", "persistence"),
    "api": ("api", "interface", "endpoint", "protocol", "integration"),
    "deployment": ("deploy", "infrastructure", "rollout", "ci/cd", "migration", "operations"),
    "risks": ("risk", "alternative", "trade-off", "tradeoff", "open question", "drawback"),
    "requirements": ("requirement", "goal", "scope", "constraint", "assumption"),
    "architecture": ("architecture", "design", "component", "system", "proposal", "solution"),
    "summary": ("summary", "overview", "abstract", "introduction", "background", "context", "motivation"),
}

EXPECTED_SECTIONS = ("requirements", "architecture", "data", "security", "scalability", "reliability")

LABELS = {
    "summary": "Summary / Overview",
    "requirements": "Requirements & Constraints",
    "architecture": "Architecture & Design",
    "data": "Data & Storage",
    "api": "APIs & Interfaces",
    "security": "Security",
    "scalability": "Scalability & Performance",
    "reliability": "Reliability & Operations",
    "deployment": "Deployment & Infrastructure",
    "risks": "Risks & Alternatives",
    "other": "Other",
    "general": "RFC Body",
}


@dataclass
class ParsedRFC:
    title: str
    sections: dict[str, str] = field(default_factory=dict)
    headings: list[tuple[str, str]] = field(default_factory=list)  # (heading, category)
    word_count: int = 0

    @property
    def missing_sections(self) -> list[str]:
        if "general" in self.sections:
            return []
        return [s for s in EXPECTED_SECTIONS if s not in self.sections]

    def to_prompt_text(self, max_chars: int = 12000) -> str:
        parts = [f"## {LABELS.get(key, key.title())}\n{text}" for key, text in self.sections.items()]
        body = "\n\n".join(parts)
        if len(body) > max_chars:
            body = body[:max_chars] + "\n\n[... RFC truncated for length ...]"
        return body

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "sections": self.sections,
            "headings": [{"heading": h, "category": c} for h, c in self.headings],
            "word_count": self.word_count,
            "missing_sections": self.missing_sections,
        }


def classify_heading(heading: str) -> str:
    lowered = heading.lower()
    for category, keywords in SECTION_KEYWORDS.items():
        if any(k in lowered for k in keywords):
            return category
    return "other"


def parse_rfc(project_name: str, text: str, min_words: int = 20) -> ParsedRFC:
    text = (text or "").strip()
    word_count = len(text.split())
    if word_count < min_words:
        raise RFCParseError(
            f"RFC is too short to review ({word_count} words, need at least {min_words})."
        )

    matches = list(HEADING_RE.finditer(text))
    if not matches:
        return ParsedRFC(
            title=project_name, sections={"general": text}, headings=[], word_count=word_count
        )

    title = project_name
    first_h1 = next((m for m in matches if len(m.group(1)) == 1), None)
    if first_h1:
        title = first_h1.group(2).strip()

    sections: dict[str, str] = {}
    headings: list[tuple[str, str]] = []

    preamble = text[: matches[0].start()].strip()
    if preamble:
        sections["summary"] = preamble

    for i, match in enumerate(matches):
        heading = match.group(2).strip()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[match.end():end].strip()
        category = classify_heading(heading)
        # A lone H1 is the document title, not a content section.
        if match is first_h1 and not body:
            continue
        headings.append((heading, category))
        if not body:
            continue
        chunk = f"### {heading}\n{body}"
        sections[category] = f"{sections[category]}\n\n{chunk}" if category in sections else chunk

    if not sections:
        sections["general"] = text

    return ParsedRFC(title=title, sections=sections, headings=headings, word_count=word_count)
