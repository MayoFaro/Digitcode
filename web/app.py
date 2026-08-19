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

    app.config["_digitcode_state"] = state
    app.config["_digitcode_current_state_payload"] = current_state_payload
    app.config["_digitcode_clone_clue"] = clone_clue
    return app
