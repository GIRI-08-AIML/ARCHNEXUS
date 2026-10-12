"""Comparison algorithm between reviews."""
from difflib import SequenceMatcher
import re


def _normalize(text: str) -> str:
    cleaned = re.sub(r"[^\w\s]", " ", text.lower())
    return " ".join(cleaned.split())


def similarity_score(title_a: str, title_b: str) -> float:
    norm_a = _normalize(title_a)
    norm_b = _normalize(title_b)
    if not norm_a or not norm_b:
        return 0.0
    if norm_a == norm_b:
        return 1.0

    # Token overlap (Jaccard)
    words_a = set(norm_a.split())
    words_b = set(norm_b.split())
    jaccard = len(words_a & words_b) / len(words_a | words_b) if (words_a | words_b) else 0.0

    # Character sequence ratio
    seq = SequenceMatcher(None, norm_a, norm_b).ratio()

    # Blended score
    return max(jaccard, seq)


def compare_reviews(prev_review, curr_review) -> dict:
    """Compare findings between a previous review and the current review.
    
    Returns:
      {
        "previous_review_id": int | None,
        "score_diff": int | None,
        "previous_score": int | None,
        "current_score": int | None,
        "counts": {"fixed": int, "still_open": int, "new": int},
        "findings": [
           {"status": "fixed"|"still_open"|"new", "finding": dict, "matched_finding": dict|None}
        ]
      }
    """
    prev_report = getattr(prev_review, "report", None)
    curr_report = getattr(curr_review, "report", None)

    prev_score = prev_report.score if prev_report else None
    curr_score = curr_report.score if curr_report else None
    score_diff = (curr_score - prev_score) if (curr_score is not None and prev_score is not None) else None

    prev_findings = list(getattr(prev_review, "findings", []))
    curr_findings = list(getattr(curr_review, "findings", []))

    matched_prev_ids = set()
    matched_curr_ids = set()
    matches = []

    # Match each curr finding against the best available prev finding
    for c in curr_findings:
        best_match = None
        best_sim = 0.0
        for p in prev_findings:
            if p.id in matched_prev_ids:
                continue
            # Match condition: same agent & same category
            if c.agent_id == p.agent_id and (c.category or "").strip().lower() == (p.category or "").strip().lower():
                sim = similarity_score(c.title, p.title)
                if sim >= 0.55 and sim > best_sim:
                    best_match = p
                    best_sim = sim

        if best_match is not None:
            matched_prev_ids.add(best_match.id)
            matched_curr_ids.add(c.id)
            matches.append({
                "status": "still_open",
                "finding": c,
                "matched_finding": best_match,
            })

    # Findings in curr that were not matched are NEW
    for c in curr_findings:
        if c.id not in matched_curr_ids:
            matches.append({
                "status": "new",
                "finding": c,
                "matched_finding": None,
            })

    # Findings in prev that were not matched are FIXED
    for p in prev_findings:
        if p.id not in matched_prev_ids:
            matches.append({
                "status": "fixed",
                "finding": p,
                "matched_finding": None,
            })

    counts = {
        "fixed": sum(1 for m in matches if m["status"] == "fixed"),
        "still_open": sum(1 for m in matches if m["status"] == "still_open"),
        "new": sum(1 for m in matches if m["status"] == "new"),
    }

    return {
        "previous_review_id": prev_review.id if prev_review else None,
        "score_diff": score_diff,
        "previous_score": prev_score,
        "current_score": curr_score,
        "counts": counts,
        "matches": matches,
    }
