from app.agents.base import JUDGE_FORMAT, build_judge_messages

FINDINGS = {
    "Database Agent": [
        {"severity": "high", "title": "Non-atomic write and enqueue", "recommendation": "outbox", "tradeoffs": None, "quote": "q"},
        {"severity": "low", "title": "Archive access unclear", "recommendation": "x", "tradeoffs": None, "quote": "q"},
    ],
    "Security Agent": [
        {"severity": "medium", "title": "Tenant isolation", "recommendation": "rls", "tradeoffs": None, "quote": "q"},
        {"severity": "critical", "title": "Open admin endpoint", "recommendation": "lock it", "tradeoffs": None, "quote": "q"},
    ],
}


def _user(findings):
    return build_judge_messages("P", findings, [])[-1]["content"]


def test_judge_prompt_lists_only_high_and_critical_findings_as_top_severity():
    user = _user(FINDINGS)
    block = user.split("Findings rated critical or high", 1)[1].split("Debate transcript", 1)[0]
    assert "Non-atomic write and enqueue (Database Agent, high)" in block
    assert "Open admin endpoint (Security Agent, critical)" in block
    assert "Tenant isolation" not in block  # medium
    assert "Archive access unclear" not in block  # low


def test_judge_prompt_says_none_when_nothing_is_high():
    low_only = {"Database Agent": [FINDINGS["Database Agent"][1]]}
    block = _user(low_only).split("Findings rated critical or high", 1)[1].split("Debate transcript", 1)[0]
    assert "(none)" in block


def test_judge_prompt_keeps_its_task_marker_and_grounding_rules():
    assert _user(FINDINGS).startswith("TASK: JUDGE\n")
    assert "Do not state as fact something a finding only suggests" in JUDGE_FORMAT
    assert "Do not repeat the finding counts" in JUDGE_FORMAT
