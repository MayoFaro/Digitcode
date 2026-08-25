from __future__ import annotations

from flask import Flask, jsonify, request

from ..mapping import POSITIONS, ROW_TOP, ROW_BOTTOM, COLS, row_contributors, col_contributors
from ..solver import DigitcodeSolver, Clue
from ..strategy import evaluate_race_strategy

# Cap for the per-question solution-count display (how many solutions each
# reachable answer could leave). Must stay a lower bound, never a fabricated
# exact number -- see _question_solution_counts. Independent of strategy.py's
# own fallback_cap: this one is tuned for UI latency on the handful of
# questions actually rendered, not for scoring the full question set. Must
# match app.js's MAX_ALTERNATIVES_SHOWN (how many alternatives get counts
# computed at all).
RANGE_DISPLAY_CAP = 2000
MAX_ALTERNATIVES_WITH_RANGE = 10


def _display_domains(snap: dict, sols: list, n_solutions_total: int) -> dict:
    """Domains to show in the "Chiffres" panel.

    `snap` (raw per-position propagation) can be strictly wider than what's
    actually reachable: `solver.py`'s `apply_no_equal_adjacent` /
    `apply_max_two` only prune a domain once the OTHER side of the
    constraint is already a singleton, so a value can survive local
    propagation without appearing in any globally valid solution (same
    root cause as the count-mismatch documented on strategy.py's
    `_clue_signature`). When the candidate list is exhaustive (its count
    matches `n_solutions_total`, not just capped at the display limit),
    the true per-position possibilities are exactly the values observed
    across those solutions -- free to compute, and always correct, unlike
    `snap`. Falls back to `snap` when the list is a truncated view (more
    solutions exist than are listed): observed-but-incomplete values would
    be too narrow, not too wide, which is a worse failure mode than the
    status quo."""
    if len(sols) != n_solutions_total:
        return snap
    tight = {p: set() for p in POSITIONS}
    for sol in sols:
        for p, v in sol.items():
            tight[p].add(v)
    return {p: sorted(tight[p]) for p in POSITIONS}


def _existing_comparison(comparisons, left, right):
    """Return the stored tuple describing the current relation between
    `left` and `right`, in either storage order, or None if unset."""
    for entry in comparisons:
        a, rel, b = entry
        if (a, b) == (left, right) or (a, b) == (right, left):
            return entry
    return None


def clone_clue(c: Clue) -> Clue:
    nc = Clue()
    nc.row_totals = dict(c.row_totals)
    nc.col_totals = dict(c.col_totals)
    nc.parity = dict(c.parity)
    nc.comparisons = list(c.comparisons)
    nc.segment_state = dict(c.segment_state)
    nc.max_two = c.max_two
    nc.forbid_equal_adjacent = c.forbid_equal_adjacent
    return nc


def _child_solver(base: DigitcodeSolver, clue: Clue):
    child = DigitcodeSolver()
    child.domains = {p: set(v) for p, v in base.domains.items()}
    try:
        child.propagate(clue)
    except ValueError:
        return None
    return child


def _question_solution_counts(solver: DigitcodeSolver, clue: Clue, q: dict, cap: int, excluded: frozenset = frozenset()) -> list[dict]:
    """Sorted, deduplicated list of {"n", "capped"} for every reachable
    answer's resulting solution count. A min/max range can't tell apart a
    question whose branches are exactly {1, 6} from one that spans every
    value 1..6 -- those play very differently (the former never risks
    leaving the opponent at 2-4), so every distinct reachable count is
    reported. `capped` means the true count was >= `cap` but unknown beyond
    that -- never presented as an exact value."""
    counts: dict[int, bool] = {}
    for out in q["outcomes"]:
        child_clue = solver._apply_answer_to_clue(clue, q, out["answer"], 0)
        child = _child_solver(solver, child_clue)
        if child is None:
            continue
        n = child.count_solutions_capped(child_clue, cap=cap, excluded=excluded)
        if n == 0:
            continue
        counts[n] = counts.get(n, False) or (n >= cap)
    return [{"n": n, "capped": capped} for n, capped in sorted(counts.items())]


def create_app() -> Flask:
    app = Flask(__name__, static_folder="static", static_url_path="")

    state = {
        "clue": Clue(),
        "history": [],
        "a_me": 2,
        "a_opp": 2,
        "my_excluded": frozenset(),
    }

    def current_state_payload() -> dict:
        solver = DigitcodeSolver()
        solver.propagate(state["clue"])  # may raise ValueError; callers must catch it
        snap = solver.snapshot()
        # Exact total (never capped -- fast enough even on an empty board,
        # ~0.3s worst case; see count_solutions_capped). The candidate list
        # itself stays capped at 6: it's also used to populate the "j'ai
        # tenté celle-ci, raté" dropdown below regardless of the total, and
        # the frontend only displays it inline when n_solutions_total <= 6.
        n_solutions_total = solver.count_solutions_capped(state["clue"], cap=None, excluded=state["my_excluded"])
        sols = solver.enumerate_solutions(state["clue"], limit=6, excluded=state["my_excluded"])
        # Shorter deadline than strategy.py's CLI-tuned default (3.0s): a web
        # request must not stall for seconds on the exact engine before falling
        # back. Passed explicitly here rather than changing the library default.
        race = evaluate_race_strategy(
            solver,
            state["clue"],
            state["a_me"],
            state["a_opp"],
            state["my_excluded"],
            time_budget_s=1.5,
        )
        all_questions_by_label = {
            q["label"]: q for q in solver.enumerate_all_questions(state["clue"])
            if len(q["outcomes"]) > 1
        }

        def _annotate(entry: dict) -> None:
            q = all_questions_by_label.get(entry["label"])
            if q is None:
                return
            counts = _question_solution_counts(solver, state["clue"], q, RANGE_DISPLAY_CAP, excluded=state["my_excluded"])
            if counts:
                entry["solution_counts"] = counts

        if race["best_question"] is not None:
            _annotate(race["best_question"])
        for alt in race["ranked_alternatives"][:MAX_ALTERNATIVES_WITH_RANGE]:
            _annotate(alt)
        return {
            "domains": _display_domains(snap, sols, n_solutions_total),
            "solutions": [solver.solution_to_string(s) for s in sols],
            "n_solutions_total": n_solutions_total,
            "trace": solver.trace,
            "a_me": state["a_me"],
            "a_opp": state["a_opp"],
            # Same "TUV WXY" shape as solution_to_string, so the frontend can
            # compare these against entries of "solutions" directly.
            "my_excluded": [f"{c[0]}{c[1]}{c[2]} {c[3]}{c[4]}{c[5]}" for c in state["my_excluded"]],
            "race": race,
            "row_totals": state["clue"].row_totals,
            "col_totals": state["clue"].col_totals,
            "parity": state["clue"].parity,
            "comparisons": state["clue"].comparisons,
            "segment_state": {f"{p}{s}": v for (p, s), v in state["clue"].segment_state.items()},
            # Only for rows/cols not yet fixed -- lets the frontend show only
            # the sums that are actually achievable given the current board,
            # instead of a fixed 0-9 range that could be rejected server-side.
            "reachable_row_sums": {
                row: solver._reachable_sums(row_contributors(row))
                for row in ROW_TOP + ROW_BOTTOM
                if row not in state["clue"].row_totals
            },
            "reachable_col_sums": {
                col: solver._reachable_sums(col_contributors(col))
                for col in COLS
                if col not in state["clue"].col_totals
            },
        }

    @app.get("/api/state")
    def get_state():
        try:
            return jsonify(current_state_payload())
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    required_fields_by_type = {
        "row_total": ("row",),
        "col_total": ("col",),
        "parity": ("pos",),
        "comparison": ("left", "rel", "right"),
        "segment": ("pos", "seg"),
    }

    @app.post("/api/clue")
    def post_clue():
        body = request.get_json(force=True)
        t = body.get("type")

        if t not in required_fields_by_type:
            return jsonify({"error": f"unknown clue type: {t}"}), 400

        missing = [f for f in required_fields_by_type[t] if f not in body]
        if missing:
            return jsonify({"error": f"missing required field(s) for {t}: {', '.join(missing)}"}), 400

        # Validate the numeric payload BEFORE touching history: a non-numeric
        # value must be rejected without pushing an undo entry, otherwise the
        # undo stack silently desyncs by one step.
        total_value = None
        if t in ("row_total", "col_total") and body.get("value") is not None:
            try:
                total_value = int(body["value"])
            except (TypeError, ValueError):
                return jsonify({"error": f"value for {t} must be an integer, got: {body['value']!r}"}), 400

        state["history"].append(clone_clue(state["clue"]))
        clue = state["clue"]
        if t == "row_total":
            if body.get("value") is None:
                clue.row_totals.pop(body["row"], None)
            else:
                clue.row_totals[body["row"]] = total_value
        elif t == "col_total":
            if body.get("value") is None:
                clue.col_totals.pop(body["col"], None)
            else:
                clue.col_totals[body["col"]] = total_value
        elif t == "parity":
            if body.get("value") is None:
                clue.parity.pop(body["pos"], None)
            else:
                clue.parity[body["pos"]] = body["value"]
        elif t == "comparison":
            left, rel, right = body["left"], body["rel"], body["right"]
            if body.get("remove"):
                pair = (left, rel, right)
                if pair in clue.comparisons:
                    clue.comparisons.remove(pair)
            else:
                existing = _existing_comparison(clue.comparisons, left, right)
                if existing is not None:
                    clue.comparisons.remove(existing)
                clue.comparisons.append((left, rel, right))
        elif t == "segment":
            key = (body["pos"], body["seg"])
            if body.get("value") is None:
                clue.segment_state.pop(key, None)
            else:
                clue.segment_state[key] = bool(body["value"])

        try:
            return jsonify(current_state_payload())
        except ValueError as e:
            state["clue"] = state["history"].pop()
            return jsonify({"error": str(e)}), 400

    @app.post("/api/guess-failed")
    def post_guess_failed():
        body = request.get_json(force=True)
        who = body.get("who")
        if who == "opponent":
            if state["a_opp"] > 0:
                state["a_opp"] -= 1
        elif who == "me":
            if "candidate" not in body:
                return jsonify({"error": "candidate field required when who='me'"}), 400
            if state["a_me"] > 0:
                candidate = tuple(body["candidate"])
                state["my_excluded"] = state["my_excluded"] | {candidate}
                state["a_me"] -= 1
        else:
            return jsonify({"error": "who must be 'me' or 'opponent'"}), 400
        return jsonify(current_state_payload())

    @app.post("/api/undo")
    def post_undo():
        if state["history"]:
            state["clue"] = state["history"].pop()
        return jsonify(current_state_payload())

    @app.post("/api/reset")
    def post_reset():
        state["clue"] = Clue()
        state["history"] = []
        state["a_me"] = 2
        state["a_opp"] = 2
        state["my_excluded"] = frozenset()
        return jsonify(current_state_payload())

    @app.get("/")
    def index():
        return app.send_static_file("index.html")

    return app
