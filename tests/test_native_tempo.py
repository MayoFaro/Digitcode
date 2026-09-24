import pytest
from digitcode.game_state import GameState
from digitcode.solver import Clue
from digitcode.native.panels.solutions_panel import SolutionsPanel
from digitcode.native.panels.endgame_format import format_endgame


@pytest.fixture
def gs():
    state = GameState()
    state.clue = Clue(row_totals={"K": 6, "S": 1}, col_totals={"H": 3, "C": 3, "E": 1},
                      parity={"T": "Pair", "W": "Pair", "Y": "Pair", "X": "Impair"})
    return state


def test_controls_only_in_endgame_and_refresh_does_not_override(qapp, gs):
    panel = SolutionsPanel(gs, run=lambda fn: fn())
    panel.refresh(gs.payload())
    assert not panel.endgame_controls.isHidden()
    assert panel.turn_override_combo.count() == 4
    assert gs.history == []
    gs.reset()
    panel.refresh(gs.payload())
    assert panel.endgame_controls.isHidden()


def test_menu_keeps_post_question_state_until_guess_or_end_turn(qapp, gs):
    panel = SolutionsPanel(gs, run=lambda fn: fn())
    panel.refresh(gs.payload())
    panel.turn_override_combo.activated.emit(1)
    assert gs.endgame_turn_phase() == "my_post_question"
    panel.refresh(gs.payload())
    result = gs.endgame()
    panel.set_endgame_result(result)
    text = panel.endgame_label.text()
    assert "Proposer" in text and "Terminer mon tour sans proposer" in text
    assert "Une nouvelle question n'est pas autorisée" in text
    assert panel.end_turn_btn.isEnabled()
    panel.end_turn_btn.click()
    assert gs.endgame_turn_phase() == "opp_turn"


def test_null_question_button_records_and_cannot_replay_stale_entry(qapp, gs):
    panel = SolutionsPanel(gs, run=lambda fn: fn())
    gs.set_endgame_phase("my_turn")
    panel.refresh(gs.payload())
    panel.set_endgame_result(gs.endgame())
    assert panel.null_questions_combo.count() > 0
    entry = panel.null_questions_combo.currentData()
    panel.record_null_btn.click()
    assert gs.endgame_turn_phase() == "my_post_question"
    with pytest.raises(ValueError):
        gs.record_null_question(entry)
    panel.hide_endgame()
    assert not panel.record_null_btn.isEnabled()
    assert panel.null_questions_combo.count() == 0


def test_before_question_keeps_all_action_comparisons(gs):
    gs.set_endgame_phase("my_turn")
    text = format_endgame(gs.endgame())
    assert "Proposer directement" in text
    assert "Question informative" in text
    assert "Question nulle" in text
    assert "Après la question informative" in text
    assert "Après la question nulle" in text


def test_opponent_post_question_has_no_second_question_recommendation(gs):
    gs.set_endgame_phase("opp_post_question")
    text = format_endgame(gs.endgame())
    assert "Il propose" in text and "Il termine sans proposer" in text
    assert "Question informative" not in text and "Conseil : poser" not in text


def test_private_exclusion_does_not_activate_endgame_above_public_limit(qapp, gs, monkeypatch):
    import digitcode.game_state as state_module
    from digitcode.solver import DigitcodeSolver
    # A small boundary case: four public candidates, three for me. The
    # eligible threshold must use the public pool, not my private exclusion.
    solver = DigitcodeSolver()
    solver.propagate(gs.clue)
    solution = solver.enumerate_solutions(gs.clue, limit=1)[0]
    gs.my_excluded = frozenset({tuple(solution[p] for p in "TUVWXY")})
    gs.a_me = 1
    monkeypatch.setattr(state_module, "ENDGAME_N_MAX", 3)
    payload = gs.payload()
    assert payload["n_solutions_total"] == 3
    panel = SolutionsPanel(gs, run=lambda fn: fn())
    panel.refresh(payload)
    assert panel.endgame_controls.isHidden()
