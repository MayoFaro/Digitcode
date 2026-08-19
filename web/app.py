from __future__ import annotations

from flask import Flask, jsonify, request

from ..mapping import ROW_TOP, ROW_BOTTOM, COLS, row_contributors, col_contributors
from ..solver import DigitcodeSolver, Clue
from ..strategy import evaluate_race_strategy


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
        sols = solver.enumerate_solutions(state["clue"], limit=5)
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
        return {
            "domains": snap,
            "solutions": [solver.solution_to_string(s) for s in sols],
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
