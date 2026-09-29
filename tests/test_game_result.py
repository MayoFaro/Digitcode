import json

import pytest

from digitcode.game_state import GameState
from digitcode.game_archive import archive_directory


@pytest.fixture
def game(monkeypatch):
    game = GameState()
    monkeypatch.setattr(game, "payload", lambda: {"result": game.result})
    return game


@pytest.mark.parametrize("who", ["me", "opponent"])
def test_result_archived_even_without_clues_and_reset_clears_it(game, who):
    game.record_result({"who": who, "code": "064 147"})
    assert game.result["code"] == "064147"
    assert game.result["winner"] == who
    assert game.a_me == game.a_opp == 2
    game.reset()
    archive = json.loads(next(archive_directory().glob("*.json")).read_text())
    assert archive["result"]["code"] == "064147"
    assert archive["result"]["winner"] == who
    assert archive["result"]["recorded_at"]
    assert game.result is None


@pytest.mark.parametrize("body", [
    {"who": "other", "code": "064147"},
    {"who": "me", "code": "64147"},
    {"who": "opponent", "code": "0641478"},
    {"who": "opponent", "code": "06414x"},
    {"who": "me", "code": 64147},
    {"who": "me", "code": "１２３４５６"},
])
def test_invalid_result_preserves_previous_entry(game, body):
    game.record_result({"who": "opponent", "code": "064147"})
    before = game.result.copy()
    with pytest.raises(ValueError):
        game.record_result(body)
    assert game.result == before


def test_result_can_be_corrected_or_cleared(game):
    game.record_result({"who": "opponent", "code": "064147"})
    game.record_result({"who": "me", "code": "684147"})
    assert game.result["winner"] == "me"
    assert game.result["code"] == "684147"
    game.clear_result()
    assert game.result is None


def test_archive_failure_preserves_result(game, monkeypatch):
    from digitcode import game_archive
    game.record_result({"who": "opponent", "code": "064147"})
    def fail(*args):
        raise OSError("unavailable")
    monkeypatch.setattr(game_archive.os, "replace", fail)
    with pytest.raises(ValueError):
        game.reset()
    assert game.result["code"] == "064147"


def test_result_web_api_and_payload(monkeypatch):
    from digitcode.web.app import create_app
    monkeypatch.setattr(GameState, "build_payload_from", staticmethod(lambda *args: {}))
    client = create_app().test_client()
    response = client.post("/api/result", json={"who": "opponent", "code": "064 147"})
    assert response.status_code == 200
    assert response.json["result"]["code"] == "064147"
    assert client.get("/api/state").json["result"]["winner"] == "opponent"
    assert client.post("/api/result", json={"who": "me", "code": "bad"}).status_code == 400
    response = client.post("/api/result", data="null", content_type="application/json")
    assert response.json["result"] is None


def test_native_result_entry_and_reset(qapp, game):
    from digitcode.native.panels.solutions_panel import SolutionsPanel
    panel = SolutionsPanel(game, run=lambda fn: fn())
    panel.result_who.setCurrentIndex(1)
    panel.result_code.setText("064 147")
    panel.result_save_btn.click()
    payload = GameState.build_payload_from(game.clue, game.a_me, game.a_opp, game.my_excluded)
    panel.refresh(payload)
    assert "Adversaire — 064 147" in panel.result_label.text()
    assert panel.result_clear_btn.isEnabled()
    panel.reset_btn.click()
    panel.refresh(payload)
    assert panel.result_code.text() == ""
    assert "non renseigné" in panel.result_label.text()
    archive = json.loads(next(archive_directory().glob("*.json")).read_text())
    assert archive["result"]["winner"] == "opponent"
