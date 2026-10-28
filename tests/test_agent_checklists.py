from app.agents import SPECIALISTS
from app.agents.base import ANALYSIS_FORMAT


def test_every_specialist_has_an_always_check_list():
    for spec in SPECIALISTS:
        assert "Always check:" in spec.system_prompt, spec.name


def test_checklist_covers_the_basics_reviewers_must_not_skip():
    prompts = {s.name: s.system_prompt.lower() for s in SPECIALISTS}
    assert "single point of failure" in prompts["Reliability Agent"]
    assert "backups" in prompts["Reliability Agent"] and "backed up" in prompts["Database Agent"]
    assert "administrators" in prompts["Security Agent"] and "revoked" in prompts["Security Agent"]
    assert "all-or-nothing" in prompts["Architecture Agent"]
    assert "scans or loops over all records" in prompts["Scalability Agent"]


def test_analysis_prompt_tells_agents_to_work_through_the_checklist():
    assert 'every "Always check" item' in ANALYSIS_FORMAT
    assert "same topic as the finding" in ANALYSIS_FORMAT
