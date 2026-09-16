from __future__ import annotations

# Below the threshold, every distinct reachable solution count is listed
# exactly -- that's precisely the zone where it matters whether a question
# can leave 2-4 solutions versus jumping straight to 1. Mirrors
# web/static/app.js's SOLUTION_COUNT_EXACT_THRESHOLD.
SOLUTION_COUNT_EXACT_THRESHOLD = 4


def format_solution_counts(entry: dict) -> str:
    counts = entry.get("solution_counts")
    if not counts:
        return "?"
    small = [c["n"] for c in counts if c["n"] <= SOLUTION_COUNT_EXACT_THRESHOLD]
    has_large = any(c["n"] > SOLUTION_COUNT_EXACT_THRESHOLD for c in counts)
    parts = [str(n) for n in small]
    if has_large:
        parts.append(f">{SOLUTION_COUNT_EXACT_THRESHOLD}")
    if len(parts) == 1:
        singular = len(small) == 1 and small[0] == 1
        return f"{parts[0]} solution" + ("" if singular else "s")
    return f"{', '.join(parts[:-1])} ou {parts[-1]} solutions"


def format_question_label(entry: dict) -> str:
    prefix = ""
    if entry.get("near_finish"):
        prefix += "\U0001f534 "  # mirrors the web's red .near-finish styling
    if entry.get("lookahead_risk"):
        prefix += "⚠️ "  # mirrors the web's amber .lookahead-risk styling
    return f"{prefix}{entry['label']} — {format_solution_counts(entry)}"
