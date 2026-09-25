import copy
import json
from pathlib import Path

import pytest

from digitcode import game_archive
from digitcode.game_state import GameState
from digitcode.solver import Clue


@pytest.fixture
def game(monkeypatch):
    state = GameState()
    monkeypatch.setattr(state, "payload", lambda: {})
    return state


def files():
    return sorted(game_archive.archive_directory().glob("*.json"))


def test_reset_archives_clues_history_and_attempts_before_clearing(game):
    game.apply_clue_fast("parity", pos="T", value="Pair")
    game.apply_clue_fast("segment", pos="T", seg="b", value=True)
    game.set_opp_starts(True)
    game.guess_failed({"who": "me", "candidate": [2, 1, 3, 4, 5, 6]})
    started = game.started_at.isoformat()
    game.reset()
    assert len(files()) == 1
    archive = json.loads(files()[0].read_text())
    assert archive["schema_version"] == 1
    assert archive["reason"] == "reset"
    assert archive["started_at"] == started
    assert archive["saved_at"] >= archive["started_at"]
    state = archive["state"]
    assert state["clue"]["parity"] == {"T": "Pair"}
    assert state["clue"]["segment_state"] == [{"pos": "T", "segment": "b", "on": True}]
    assert state["a_me"] == 1 and state["a_opp"] == 2
    assert state["my_excluded"] == [[2, 1, 3, 4, 5, 6]]
    assert state["opp_starts"] is True
    assert state["failed_guesses"] == [["me", 2]]
    assert len(archive["history"]) == len(archive["state_history"]) == 2
    assert archive["history"][0]["parity"] == {}
    assert archive["history"][1]["parity"] == {"T": "Pair"}
    assert game.clue == Clue() and not game.history
    assert game.a_me == game.a_opp == 2
    assert game.last_archive_path == str(files()[0])
    assert not list(files()[0].parent.glob("*.tmp"))


def test_endgame_corrections_and_private_history_survive_json_serialization(game):
    game.clue = Clue(row_totals={"K": 6, "S": 1}, col_totals={"H": 3, "C": 3, "E": 1},
                      parity={"T": "Pair", "W": "Pair", "Y": "Pair", "X": "Impair"})
    game.set_endgame_phase("my_post_question")
    game.guess_failed({"who": "me", "candidate": [0, 4, 0, 2, 1, 4]})
    game.guess_failed({"who": "opponent"})
    game.set_endgame_phase("my_turn")
    game.reset()
    archive = json.loads(files()[0].read_text())
    assert archive["state"]["endgame_phase"] == "my_turn"
    assert archive["state"]["endgame_manual"] is True
    assert archive["state"]["opp_fail_pool_size"] == 4
    assert archive["state"]["a_opp"] == 1
    assert archive["state_history"][-1]["excluded"] == [[0, 4, 0, 2, 1, 4]]


def test_empty_reset_does_not_create_files_but_failure_without_question_does(game):
    game.set_opp_starts(True)
    game.reset()
    assert files() == []
    game.guess_failed({"who": "me", "candidate": [1, 2, 3, 4, 5, 6]})
    game.reset()
    assert len(files()) == 1
    last_path = game.last_archive_path
    game.reset()
    assert len(files()) == 1 and game.last_archive_path == last_path


def test_successive_games_do_not_overwrite_each_other(game):
    game.apply_clue_fast("parity", pos="T", value="Pair")
    game.reset()
    first = files()[0].read_bytes()
    game.apply_clue_fast("parity", pos="T", value="Impair")
    game.reset()
    assert len(files()) == 2
    assert files()[0].read_bytes() == first
    assert json.loads(files()[1].read_text())["state"]["clue"]["parity"] == {"T": "Impair"}


@pytest.mark.parametrize("operation", ["fsync", "replace"])
def test_write_failure_keeps_entire_live_game_and_removes_partial_file(game, monkeypatch, operation):
    game.apply_clue_fast("parity", pos="T", value="Pair")
    before = copy.deepcopy({k: v for k, v in vars(game).items() if k != "payload"})
    def fail(*args):
        raise OSError("disk unavailable")
    monkeypatch.setattr(game_archive.os, operation, fail)
    with pytest.raises(ValueError, match="Réinitialisation annulée"):
        game.reset()
    assert {k: v for k, v in vars(game).items() if k != "payload"} == before
    assert files() == []
    assert not list(game_archive.archive_directory().iterdir())


def test_unwritable_destination_keeps_the_live_game(game, tmp_path, monkeypatch):
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("existing file")
    monkeypatch.setenv("DIGITCODE_ARCHIVE_DIR", str(blocked / "parties"))
    game.apply_clue_fast("parity", pos="T", value="Pair")
    with pytest.raises(ValueError, match="Sauvegarde impossible"):
        game.reset()
    assert game.clue.parity == {"T": "Pair"}
    assert len(game.history) == 1
    assert blocked.read_text() == "existing file"


def test_default_path_and_xdg_override(monkeypatch, tmp_path):
    monkeypatch.delenv("DIGITCODE_ARCHIVE_DIR")
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    assert game_archive.archive_directory() == Path.home() / ".local/share/digitcode/parties"
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    assert game_archive.archive_directory() == tmp_path / "data/digitcode/parties"


def test_web_reset_reports_failure_and_preserves_state(monkeypatch):
    from digitcode.web.app import create_app
    client = create_app().test_client()
    assert client.post("/api/clue", json={"type": "parity", "pos": "T", "value": "Pair"}).status_code == 200
    def fail(*args):
        raise OSError("disk unavailable")
    monkeypatch.setattr(game_archive.os, "replace", fail)
    response = client.post("/api/reset")
    assert response.status_code == 400
    assert "partie en cours est conservée" in response.json["error"]
    assert client.get("/api/state").json["parity"] == {"T": "Pair"}


def test_native_reset_displays_archive_location(qapp, game):
    from digitcode.native.panels.solutions_panel import SolutionsPanel
    # A real payload is needed to render; mutations themselves stay cheap.
    panel = SolutionsPanel(game, run=lambda fn: fn())
    game.apply_clue_fast("parity", pos="T", value="Pair")
    panel.reset_btn.click()
    payload = GameState.build_payload_from(game.clue, game.a_me, game.a_opp, game.my_excluded)
    panel.refresh(payload)
    assert not panel.archive_label.isHidden()
    assert game.last_archive_path in panel.archive_label.text()
    assert Path(game.last_archive_path).is_file()
