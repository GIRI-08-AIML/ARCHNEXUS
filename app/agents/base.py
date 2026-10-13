"""Agent specs and prompt builders shared by every agent."""
import json
import re
from dataclasses import dataclass

from app.parser import ParsedRFC
from app.schemas import DebateDraft, Decision, FindingDraft, JudgeVerdict, Severity, VerifyDraft
from pydantic import ValidationError

from app.llm import LLMClient


@dataclass(frozen=True)
class AgentSpec:
    name: str
    role: str
    description: str
    focus: str  # what this agent looks for

    @property
    def system_prompt(self) -> str:
        return (
            f"You are the {self.name} on a software architecture review board. "
            f"Your role: {self.role}. {self.description}\n"
            f"Focus areas: {self.focus}\n"
            "Be specific, evidence-based and concise. Cite the part of the RFC you are "
            "reacting to. Never invent facts about the system that the RFC does not state; "
            "if something important is missing, raise that as a finding. "
            "Always answer with a single valid JSON object and nothing else."
        )


SEVERITY_GUIDE = """Severity guide. Be strict: most findings are medium or low, and most RFCs have no critical finding.
- critical: as written, the design will lose data, expose data, be exploitable, or cannot meet a goal the RFC states, and the RFC describes no mitigation.
- high: likely to cause an outage or a serious defect in normal operation. The RFC describes no mitigation, or only a weak one.
- medium: worth fixing before launch, but the system still works without it. This includes detail that a normal design review would ask for.
- low: a minor gap or a nice-to-have.
Lower the severity by one level when the RFC already has a partial safeguard.
Never rate a problem high or critical if it only appears when you assume something the RFC does not say (for example the exact load, or how a component is configured)."""

ANALYSIS_FORMAT = """Return JSON in exactly this shape:
{"findings": [
  {"category": "short topic",
   "severity": "low|medium|high|critical",
   "title": "one-line issue",
   "quote": "verbatim quote from the RFC text that demonstrates this issue",
   "description": "what the problem/risk is and why it matters",
   "recommendation": "concrete fix",
   "tradeoffs": "cost or downside of the fix, or null"}
]}
Report 3 to 6 findings, most severe first. Stay within your focus areas.
Every finding must include a verbatim 'quote' directly from the RFC text: the sentence that shows the problem.
Read the whole RFC before you report something as missing. If the RFC already states a safeguard for a concern, do not report that concern.
Only report real weaknesses. Fewer, correct findings are better than many doubtful ones.

@@SEVERITY_GUIDE@@"""
ANALYSIS_FORMAT = ANALYSIS_FORMAT.replace("@@SEVERITY_GUIDE@@", SEVERITY_GUIDE)

VERIFY_FORMAT = """Return JSON in exactly this shape:
{"verdict": "valid|already_addressed|contradicted",
 "evidence": "the exact sentence copied from the RFC that proves your verdict, or an empty string for valid",
 "severity": "critical|high|medium|low",
 "reason": "one short sentence"}

Rules:
- "already_addressed": the RFC explicitly contains the safeguard, fix or mechanism that the finding says is missing.
- "contradicted": the finding claims something about the system that the RFC clearly states the opposite of.
- "valid": the RFC confirms the weakness, or says nothing about it. When in doubt, answer valid.
- Evidence must be copied word for word from the RFC. Never invent it.
- "severity": the severity this finding deserves, using the guide below. Keep the severity it was given, or lower it. Never raise it.
  Lower it when the RFC already partly covers the concern, or when the problem only appears if you assume something the RFC does not say.

@@SEVERITY_GUIDE@@

Examples:
RFC says "Tokens expire after 15 minutes." Finding (high): "Tokens never expire" -> {"verdict": "contradicted", "evidence": "Tokens expire after 15 minutes.", "severity": "high", "reason": "The RFC states the tokens expire."}
RFC says "We run one instance of each service." Finding (high): "Single point of failure" -> {"verdict": "valid", "evidence": "", "severity": "high", "reason": "The RFC confirms there is a single instance."}
RFC never mentions rate limits. Finding (medium): "No rate limiting" -> {"verdict": "valid", "evidence": "", "severity": "medium", "reason": "The RFC says nothing about rate limits."}
RFC says "Images are cached for 10 minutes." Finding (high): "No cache invalidation" -> {"verdict": "valid", "evidence": "", "severity": "low", "reason": "Images can be stale for at most 10 minutes, which is a small, bounded problem."}"""
VERIFY_FORMAT = VERIFY_FORMAT.replace("@@SEVERITY_GUIDE@@", SEVERITY_GUIDE)

DEBATE_FORMAT = """Return JSON in exactly this shape:
{"responses": [
  {"target_agent": "exact name of another agent",
   "stance": "agree|disagree|refine",
   "message": "your argument in 1-3 sentences"}
]}
Respond to at most 3 findings from OTHER agents where your expertise leads you to agree,
disagree (e.g. their fix would harm your area) or refine. If nothing warrants a response
return {"responses": []}."""

JUDGE_FORMAT = """Return JSON in exactly this shape:
{"decision": "approve|approve_with_changes|reject",
 "score": 0-100 (overall architecture quality),
 "summary": "3-5 sentence executive summary",
 "recommendations": ["prioritised, actionable items"],
 "key_risks": ["the most important remaining risks"]}
Decision guide: reject if any unresolved critical issue exists; approve_with_changes if
there are high-severity issues that can be fixed; approve otherwise.

Writing the summary:
- Use only what the findings and the debate say. Use each finding's severity exactly as given: only findings
  listed as rated critical or high may be called high-severity or critical.
- Do not state as fact something a finding only suggests. Write "may" or "could" for risks the RFC does not confirm.
- Do not repeat the finding counts. They are added automatically."""


JUDGE_SPEC = AgentSpec(
    name="Judge Agent",
    role="impartial final decision maker",
    description=(
        "You weigh the specialists' findings and the debate between them, resolve conflicts "
        "explicitly, and issue the final verdict."
    ),
    focus="severity, evidence, trade-offs between competing recommendations",
)


def _findings_block(findings: list[dict]) -> str:
    return json.dumps(findings, indent=1)


OPEN_QUESTION_NOTE = (
    "If the RFC itself says something is undecided or still an open question, report that as a finding.\n"
)


def build_analysis_messages(spec: AgentSpec, project: str, parsed: ParsedRFC, max_chars: int) -> list[dict]:
    missing = parsed.missing_sections
    gap_note = (
        f"Sections not found in the RFC: {', '.join(missing)}.\n" if missing else ""
    )
    user = (
        "TASK: ANALYSIS\n"
        f"Project: {project}\nRFC title: {parsed.title}\n{gap_note}\n"
        f"--- RFC START ---\n{parsed.to_prompt_text(max_chars)}\n--- RFC END ---\n\n"
        f"{ANALYSIS_FORMAT}"
        # One agent reports open questions, so that five agents do not each report the same one.
        + (f"\n{OPEN_QUESTION_NOTE}" if spec.name == "Architecture Agent" else "")
    )
    return [{"role": "system", "content": spec.system_prompt}, {"role": "user", "content": user}]


VERIFIER_SYSTEM = (
    "You are a strict fact-checker for software architecture review findings. "
    "You are given an RFC and one finding about it. Check the finding against the RFC text only. "
    "Always answer with a single valid JSON object and nothing else."
)


def build_verify_messages(project: str, rfc_text: str, finding: dict, max_chars: int) -> list[dict]:
    rfc = rfc_text if len(rfc_text) <= max_chars else rfc_text[:max_chars] + "\n[... RFC truncated for length ...]"
    user = (
        "TASK: VERIFY\n"
        f"Project: {project}\n\n"
        f"--- RFC START ---\n{rfc}\n--- RFC END ---\n\n"
        f"Finding title: {finding.get('title', '')}\n"
        f"Finding severity as given: {finding.get('severity', 'medium')}\n"
        f"Finding description: {finding.get('description', '')}\n"
        f"Finding recommendation: {finding.get('recommendation', '')}\n\n"
        "Does the RFC already address this concern, or contradict what the finding claims?\n"
        f"{VERIFY_FORMAT}"
    )
    return [{"role": "system", "content": VERIFIER_SYSTEM}, {"role": "user", "content": user}]


def build_debate_messages(
    spec: AgentSpec,
    round_no: int,
    all_findings: dict[str, list[dict]],
    transcript: list[dict],
) -> list[dict]:
    own = all_findings.get(spec.name, [])
    others = {name: items for name, items in all_findings.items() if name != spec.name}
    user = (
        f"TASK: DEBATE (round {round_no})\n"
        f"Your own findings:\n{_findings_block(own)}\n\n"
        f"Findings from the other agents:\n{json.dumps(others, indent=1)}\n\n"
        f"Debate so far:\n{json.dumps(transcript, indent=1) if transcript else '(none)'}\n\n"
        f"{DEBATE_FORMAT}"
    )
    return [{"role": "system", "content": spec.system_prompt}, {"role": "user", "content": user}]


def _titles_rated(all_findings: dict[str, list[dict]], levels: tuple[str, ...]) -> list[str]:
    return [
        f"- {f.get('title', '')} ({name}, {f.get('severity')})"
        for name, fs in all_findings.items()
        for f in fs
        if f.get("severity") in levels
    ]


def build_judge_messages(
    project: str, all_findings: dict[str, list[dict]], transcript: list[dict]
) -> list[dict]:
    top = _titles_rated(all_findings, ("critical", "high"))
    user = (
        "TASK: JUDGE\n"
        f"Project: {project}\n\n"
        f"All specialist findings:\n{json.dumps(all_findings, indent=1)}\n\n"
        "Findings rated critical or high (the only ones you may call high-severity or critical):\n"
        f"{chr(10).join(top) if top else '(none)'}\n\n"
        f"Debate transcript:\n{json.dumps(transcript, indent=1) if transcript else '(none)'}\n\n"
        f"{JUDGE_FORMAT}"
    )
    return [{"role": "system", "content": JUDGE_SPEC.system_prompt}, {"role": "user", "content": user}]


# ---------------------------------------------------------------- run helpers
def run_analysis(
    spec: AgentSpec, llm: LLMClient, project: str, parsed: ParsedRFC, max_chars: int
) -> list[FindingDraft]:
    data = llm.chat_json(build_analysis_messages(spec, project, parsed, max_chars))
    drafts: list[FindingDraft] = []
    for item in data.get("findings", []) or []:
        try:
            drafts.append(FindingDraft.model_validate(item))
        except ValidationError:
            continue  # skip malformed finding, keep the rest
    return drafts


def run_debate(
    spec: AgentSpec,
    llm: LLMClient,
    round_no: int,
    all_findings: dict[str, list[dict]],
    transcript: list[dict],
) -> list[DebateDraft]:
    data = llm.chat_json(build_debate_messages(spec, round_no, all_findings, transcript))
    drafts: list[DebateDraft] = []
    for item in (data.get("responses", []) or [])[:3]:
        try:
            drafts.append(DebateDraft.model_validate(item))
        except ValidationError:
            continue
    return drafts


def normalize_text(text: str | None) -> str:
    return " ".join((text or "").split()).lower()


def text_in_rfc(snippet: str | None, rfc_text: str | None, min_len: int = 1) -> bool:
    """True if the snippet appears word for word (ignoring case and spacing) in the RFC."""
    s = normalize_text(snippet).strip(" .\"'\u201c\u201d")
    return len(s) >= min_len and s in normalize_text(rfc_text)


_SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def lowered_severity(current: Severity, suggested: str | None) -> Severity:
    """The verifier may lower a severity, never raise it. Unknown answers change nothing."""
    if suggested in _SEVERITY_RANK and _SEVERITY_RANK[suggested] < _SEVERITY_RANK[str(current)]:
        return Severity(suggested)
    return current


# ------------------------------------------------------------- duplicate findings
_STOPWORDS = frozenset(
    "a an the of to for and or in on at by with without is are be as it its this that from not no into than then "
    "so can may might must should will would could per via across between over under both each any all lacks lack "
    "missing insufficient limited potential unclear explicit explicitly define defined add use using implement adopt".split()
)


def _tokens(text: str) -> set[str]:
    out = set()
    for w in re.findall(r"[a-z0-9]+", (text or "").lower()):
        if len(w) < 3 or w in _STOPWORDS:
            continue
        if w.endswith("ies") and len(w) > 4:
            w = w[:-3] + "y"
        elif w.endswith("s") and not w.endswith("ss") and len(w) > 3:
            w = w[:-1]
        out.add(w)
    return out


def _jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if (a | b) else 0.0


def _topic(f) -> set[str]:
    return _tokens(f"{f.title} {f.description} {f.recommendation}")


def find_duplicate(new, existing: list) -> int | None:
    """Index of the finding in `existing` that says the same thing as `new`, or None.

    Two findings are the same when they share one RFC quote and describe the same problem and fix (many
    different problems quote the same sentence, so the quote alone is not enough), or when their titles are
    nearly identical. Tuned on 33 real findings from two reviews: the pairs of true duplicates that shared a
    quote scored 0.19 to 0.23 on the topic test, the closest pair of different problems that shared a quote
    scored 0.09, and no pair of different problems scored above 0.25 on titles alone.
    """
    new_quote = " ".join(re.sub(r"[^a-z0-9 ]", " ", (new.quote or "").lower()).split())
    new_title = _tokens(new.title)
    new_topic = _topic(new)
    for i, other in enumerate(existing):
        if _jaccard(new_title, _tokens(other.title)) >= 0.6:
            return i
        other_quote = " ".join(re.sub(r"[^a-z0-9 ]", " ", (other.quote or "").lower()).split())
        if new_quote and new_quote == other_quote and _jaccard(new_topic, _topic(other)) >= 0.14:
            return i
    return None


def run_verification(
    llm: LLMClient, project: str, rfc_text: str, finding: dict, max_chars: int
) -> VerifyDraft:
    data = llm.chat_json(build_verify_messages(project, rfc_text, finding, max_chars))
    return VerifyDraft.model_validate(data)


def run_judge(
    llm: LLMClient, project: str, all_findings: dict[str, list[dict]], transcript: list[dict]
) -> JudgeVerdict:
    data = llm.chat_json(build_judge_messages(project, all_findings, transcript))
    return JudgeVerdict.model_validate(data)


def apply_guardrails(verdict: JudgeVerdict, all_findings: dict[str, list[dict]]) -> JudgeVerdict:
    """Rules the Judge model cannot override, so the verdict never contradicts the evidence.

    - 3+ critical findings           -> reject, score capped at 25
    - 2 critical findings            -> reject, score capped at 40
    - 1 critical finding             -> cannot be approve, score capped at 60
    - 3+ high findings               -> reject/approve_with_changes, score capped at 70
    - any high finding + "approve"   -> approve_with_changes, score capped at 85
    - Prepend exact severity counts statement to summary to eliminate LLM contradictions.
    """
    items = [f for fs in all_findings.values() for f in fs]
    counts = {s: sum(1 for f in items if f.get("severity") == s) for s in ("critical", "high", "medium", "low")}
    critical = counts["critical"]
    high = counts["high"]
    medium = counts["medium"]
    low = counts["low"]

    decision, score = verdict.decision.value, verdict.score
    reasons: list[str] = []

    # Progressive severity caps
    if critical >= 3:
        if decision != "reject":
            reasons.append(f"{critical} critical findings require rejection")
            decision = "reject"
        score = min(score, 25)
    elif critical == 2:
        if decision != "reject":
            reasons.append(f"{critical} critical findings require rejection")
            decision = "reject"
        score = min(score, 40)
    elif critical == 1:
        if decision == "approve":
            reasons.append("a critical finding prevents plain approval")
            decision = "approve_with_changes"
        score = min(score, 60)

    if high >= 3:
        score = min(score, 70)
        if decision == "approve":
            reasons.append(f"{high} high-severity findings require changes or rejection")
            decision = "approve_with_changes"
    elif high >= 1:
        if decision == "approve":
            reasons.append("high-severity findings require changes before approval")
            decision = "approve_with_changes"
        score = min(score, 85)

    prefix = f"Review Board Audit: {critical} critical, {high} high, {medium} medium, and {low} low finding(s) identified."
    clean_summary = verdict.summary.strip()
    if clean_summary.startswith("Review Board Audit:"):
        # Replace existing prefix if already present
        clean_summary = clean_summary.split(".", 1)[-1].strip()

    note = f" [Adjusted by review rules: {'; '.join(reasons) or 'score capped by finding severity'}.]" if (decision != verdict.decision.value or score != verdict.score) else ""
    final_summary = f"{prefix} {clean_summary}{note}".strip()

    return verdict.model_copy(
        update={"decision": Decision(decision), "score": score, "summary": final_summary}
    )


def heuristic_verdict(all_findings: dict[str, list[dict]]) -> JudgeVerdict:
    """Fallback used only when the Judge LLM call fails."""
    items = [f for fs in all_findings.values() for f in fs]
    counts = {s: sum(1 for f in items if f["severity"] == s) for s in ("critical", "high", "medium", "low")}
    score = max(0, 100 - counts["critical"] * 30 - counts["high"] * 12 - counts["medium"] * 4 - counts["low"])
    if counts["critical"]:
        decision = "reject"
    elif counts["high"]:
        decision = "approve_with_changes"
    else:
        decision = "approve"
    top = sorted(items, key=lambda f: ["critical", "high", "medium", "low"].index(f["severity"]))[:5]
    return JudgeVerdict(
        decision=decision,
        score=score,
        summary=(
            "Automatic verdict (the Judge Agent was unavailable): "
            f"{counts['critical']} critical, {counts['high']} high, "
            f"{counts['medium']} medium and {counts['low']} low findings."
        ),
        recommendations=[f["recommendation"] for f in top],
        key_risks=[f["title"] for f in top],
    )
