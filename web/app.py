from __future__ import annotations

from flask import Flask, jsonify, request

# _question_solution_counts and _display_domains are re-exported here (not
# used directly below) because tests/test_web.py imports them from
# digitcode.web.app -- keep that import path working.
from ..game_state import GameState, _question_solution_counts, _display_domains  # noqa: F401


def create_app() -> Flask:
    app = Flask(__name__, static_folder="static", static_url_path="")
    game_state = GameState()

    @app.get("/api/state")
    def get_state():
        try:
            return jsonify(game_state.payload())
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.post("/api/clue")
    def post_clue():
        body = request.get_json(force=True)
        t = body.get("type")
        fields = {k: v for k, v in body.items() if k != "type"}
        try:
            return jsonify(game_state.apply_clue(t, **fields))
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.post("/api/guess-failed")
    def post_guess_failed():
        body = request.get_json(force=True)
        try:
            return jsonify(game_state.guess_failed(body))
        except ValueError as e:
            return jsonify({"error": str(e)}), 400

    @app.post("/api/undo")
    def post_undo():
        return jsonify(game_state.undo())

    @app.post("/api/reset")
    def post_reset():
        return jsonify(game_state.reset())

    @app.get("/")
    def index():
        return app.send_static_file("index.html")

    return app
