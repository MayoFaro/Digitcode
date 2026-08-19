from __future__ import annotations

from flask import Flask, jsonify, request

from ..solver import DigitcodeSolver, Clue
from ..strategy import evaluate_race_strategy


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
        race = evaluate_race_strategy(solver, state["clue"], state["a_me"], state["a_opp"], state["my_excluded"])
        return {
            "domains": snap,
            "solutions": [solver.solution_to_string(s) for s in sols],
            "trace": solver.trace,
            "a_me": state["a_me"],
            "a_opp": state["a_opp"],
            "race": race,
            "row_totals": state["clue"].row_totals,
            "col_totals": state["clue"].col_totals,
            "parity": state["clue"].parity,
            "comparisons": state["clue"].comparisons,
            "segment_state": {f"{p}{s}": v for (p, s), v in state["clue"].segment_state.items()},
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

        state["history"].append(clone_clue(state["clue"]))
        clue = state["clue"]
        if t == "row_total":
            if body.get("value") is None:
                clue.row_totals.pop(body["row"], None)
            else:
                clue.row_totals[body["row"]] = int(body["value"])
        elif t == "col_total":
            if body.get("value") is None:
                clue.col_totals.pop(body["col"], None)
            else:
                clue.col_totals[body["col"]] = int(body["value"])
        elif t == "parity":
            if body.get("value") is None:
                clue.parity.pop(body["pos"], None)
            else:
                clue.parity[body["pos"]] = body["value"]
        elif t == "comparison":
            pair = (body["left"], body["rel"], body["right"])
            if body.get("remove"):
                if pair in clue.comparisons:
                    clue.comparisons.remove(pair)
            else:
                clue.comparisons.append(pair)
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
