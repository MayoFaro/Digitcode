"""User's E4 ... G1 game: starter correction and unambiguous EV presentation."""
import pytest
from digitcode.game_state import GameState
from digitcode.native.panels.endgame_format import format_endgame, format_endgame_details
from digitcode.native.panels.solutions_panel import SolutionsPanel


@pytest.fixture
def game(monkeypatch):
    gs = GameState()
    # Only skip the unrelated early-game recommendations between entries.
    monkeypatch.setattr(gs, 'payload', lambda: {})
    moves = [
        ('col_total', dict(col='E', value=4)),
        ('comparison', dict(left='U', rel='>', right='T')),
        ('row_total', dict(row='S', value=0)),
        ('comparison', dict(left='U', rel='>', right='X')),
        ('row_total', dict(row='K', value=5)),
        ('comparison', dict(left='X', rel='>', right='W')),
        ('row_total', dict(row='O', value=1)),
        ('comparison', dict(left='Y', rel='>', right='X')),
        ('row_total', dict(row='M', value=5)),
        ('comparison', dict(left='Y', rel='>', right='V')),
        ('col_total', dict(col='G', value=1)),
    ]
    for kind, fields in moves:
        gs.apply_clue_fast(kind, **fields)
    return gs


def test_starter_toggle_recalculates_automatic_phase_and_can_be_undone(game):
    assert game.endgame_turn_phase() == 'my_post_question'
    game.set_opp_starts(True)
    assert game.endgame_turn_phase() == 'opp_post_question'
    game.undo()
    assert game.opp_starts is False
    assert game.endgame_turn_phase() == 'my_post_question'
    game.set_opp_starts(True)
    game.set_opp_starts(False)
    assert game.endgame_turn_phase() == 'my_post_question'


def test_explicit_turn_override_remains_the_anchor(game):
    game.set_endgame_phase('my_turn')
    game.set_opp_starts(True)
    assert game.endgame_turn_phase() == 'my_turn'
    game.undo()  # undo the starter change
    game.undo()  # undo the explicit correction
    game.set_opp_starts(True)
    assert game.endgame_turn_phase() == 'opp_post_question'


def test_g1_opponent_must_still_decide_before_my_turn(game):
    game.set_opp_starts(True)
    result = game.endgame()
    assert result['phase'] == 'opp_post_question'
    assert result['best_question'] is None
    game.end_endgame_turn()
    assert game.endgame_turn_phase() == 'my_turn'


def test_three_fixed_action_values_and_existing_recommendation_are_unchanged(game):
    game.set_endgame_phase('my_turn')
    r = game.endgame()
    assert r['p_win'] == pytest.approx(0.625)
    assert r['decision'] == 'question'
    assert r['best_question']['label'] == 'Combien en ligne L ?'
    assert r['guess_now']['p_win'] == pytest.approx(7 / 12)
    assert r['best_question_then_guess']['p_win'] == pytest.approx(0.625)
    assert r['null_without_guess']['p_win'] == pytest.approx(1 / 3)
    assert r['best_null_question']['p_win'] == pytest.approx(7 / 12)
    text = format_endgame(r)
    assert 'Proposer sans question (064 147) : P = 58,3 %' in text
    assert 'Poser une question puis proposer : P = 62,5 %' in text
    assert 'Question nulle sans proposer : P = 33,3 %' in text
    assert 'Mon conseil : poser Combien en ligne L ?' in text
    assert 'Si la réponse est 2 : proposer 064 147' in text
    assert 'Si la réponse est 3 : proposer 684 147' in text
    assert 'victoire 50' not in text
    details = format_endgame_details(r)
    assert 'réussite immédiate 33,3 % ; victoire finale 50,0 %' in details
    assert '75,0 % × 50,0 % + 25,0 % × 100,0 % = 62,5 %' in details
    assert 'Victoire dès la proposition suivant la question : 50,0 %' in details


def test_probability_details_are_optional_and_cleared_with_stale_results(game, qapp):
    game.set_endgame_phase('my_turn')
    panel = SolutionsPanel(game, run=lambda fn: fn())
    panel.set_endgame_result(game.endgame())
    assert panel.endgame_details_label.isHidden()
    assert not panel.endgame_details_toggle.isHidden()
    panel.endgame_details_toggle.setChecked(True)
    assert not panel.endgame_details_label.isHidden()
    panel.hide_endgame()
    assert panel.endgame_details_toggle.isHidden()
    assert panel.endgame_details_label.isHidden()


def test_reset_discards_manual_anchor(game):
    game.set_endgame_phase('my_turn')
    game.reset()
    assert not game._endgame_manual


def test_secondary_comparisons_are_available_in_details(game, qapp):
    game.set_endgame_phase('my_turn')
    panel = SolutionsPanel(game, run=lambda fn: fn())
    payload = GameState.build_payload_from(game.clue, game.a_me, game.a_opp, game.my_excluded)
    panel.refresh(payload)
    panel.set_endgame_result(game.endgame())
    assert panel.analysis_group.isHidden()
    panel.endgame_details_toggle.setChecked(True)
    assert not panel.analysis_group.isHidden()
    panel.endgame_details_toggle.setChecked(False)
    assert panel.analysis_group.isHidden()
