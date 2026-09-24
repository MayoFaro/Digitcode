import pytest
from digitcode.game_state import GameState
from digitcode.endgame_tempo import PHASES, build_universe, question_entry
from digitcode.solver import DigitcodeSolver
from tests.test_game_state import _n4_state


@pytest.fixture
def gs(monkeypatch):
    # Exercise real clue/turn transitions without running the unrelated
    # early-game strategy after every recorded event.
    monkeypatch.setattr(GameState, "payload", lambda self: {})
    return _n4_state()


def null_entries(gs):
    solver = DigitcodeSolver()
    solver.propagate(gs.clue)
    _, questions = build_universe(solver, gs.clue)
    return [question_entry(q, q.answers[0]) for q in questions if len(q.classes) == 1]


@pytest.mark.parametrize("phase,next_phase", list(zip(PHASES, (
    "my_post_question", "opp_post_question", "opp_post_question", "my_post_question"))))
def test_override_is_a_new_anchor_and_next_question_advances(gs, phase, next_phase):
    gs.set_endgame_phase(phase)
    assert gs.endgame_turn_phase() == phase
    gs.record_null_question(null_entries(gs)[0])
    assert gs.endgame_turn_phase() == next_phase
    gs.record_null_question(null_entries(gs)[0])
    assert gs.endgame_turn_phase() == ("opp_post_question" if next_phase == "my_post_question" else "my_post_question")


def test_my_post_question_state_allows_guess_and_undo_restores_it(gs):
    gs.set_endgame_phase("my_post_question")
    before = (gs.a_me, gs.my_excluded)
    gs.guess_failed({"who": "me", "candidate": [1,2,3,4,5,6]})
    assert gs.endgame_turn_phase() == "opp_turn"
    assert gs.a_me == 1
    gs.undo()
    assert gs.endgame_turn_phase() == "my_post_question"
    assert (gs.a_me, gs.my_excluded) == before


def test_finish_turn_is_only_legal_after_question_and_is_undoable(gs):
    gs.set_endgame_phase("my_turn")
    with pytest.raises(ValueError):
        gs.end_endgame_turn()
    gs.set_endgame_phase("my_post_question")
    gs.end_endgame_turn()
    assert gs.endgame_turn_phase() == "opp_turn"
    gs.undo()
    assert gs.endgame_turn_phase() == "my_post_question"


def test_opponent_post_question_and_failure_undo(gs):
    gs.set_endgame_phase("opp_post_question")
    gs.guess_failed({"who": "opponent"})
    assert gs.endgame_turn_phase() == "my_turn"
    assert gs.opp_fail_pool_size == 4
    gs.undo()
    assert gs.endgame_turn_phase() == "opp_post_question"
    assert gs.a_opp == 2 and gs.opp_fail_pool_size == 0


def test_null_question_consumed_once_and_undo_restores_availability_and_turn(gs):
    gs.set_endgame_phase("my_turn")
    entries = null_entries(gs)
    gs.record_null_question(entries[0])
    assert len(null_entries(gs)) == len(entries) - 1
    assert gs.endgame_turn_phase() == "my_post_question"
    with pytest.raises(ValueError):
        gs.record_null_question(entries[0])
    gs.undo()
    assert gs.endgame_turn_phase() == "my_turn"
    assert entries[0] in null_entries(gs)


def test_reentering_same_answer_does_not_advance_turn(gs):
    gs.set_endgame_phase("my_post_question")
    gs.apply_clue_fast("row_total", row="K", value=6)
    assert gs.endgame_turn_phase() == "my_post_question"


def test_invalid_clue_leaves_override_and_history_intact(gs):
    gs.set_endgame_phase("opp_post_question")
    depth = len(gs.history)
    with pytest.raises(ValueError):
        gs.apply_clue_fast("row_total", row="K", value=99)
    assert gs.endgame_turn_phase() == "opp_post_question"
    assert len(gs.history) == depth


def test_override_undo_and_reset(gs):
    before = gs.endgame_turn_phase()
    gs.set_endgame_phase("opp_turn")
    gs.undo()
    assert gs.endgame_turn_phase() == before
    gs.set_endgame_phase("opp_post_question")
    gs.reset()
    assert gs.endgame_turn_phase() == "my_turn"
    assert gs.history == [] and gs._state_history == []


def test_override_not_available_before_endgame():
    gs = GameState()
    with pytest.raises(ValueError):
        gs.set_endgame_phase("my_post_question")
    with pytest.raises(ValueError):
        gs.end_endgame_turn()
    assert not gs.history
