import pytest

from digitcode.game_state import GameState


def test_fresh_state_has_full_domains_and_two_attempts_each():
    gs = GameState()
    payload = gs.payload()
    assert set(payload["domains"].keys()) == {"T", "U", "V", "W", "X", "Y"}
    assert all(len(v) == 10 for v in payload["domains"].values())
    assert payload["a_me"] == 2
    assert payload["a_opp"] == 2
    assert "race" in payload and "p_win" in payload["race"]


def test_apply_clue_parity_narrows_domain():
    gs = GameState()
    payload = gs.apply_clue("parity", pos="T", value="Pair")
    assert all(d % 2 == 0 for d in payload["domains"]["T"])


def test_apply_clue_unknown_type_raises():
    gs = GameState()
    with pytest.raises(ValueError, match="unknown clue type"):
        gs.apply_clue("bogus")


def test_apply_clue_missing_field_raises_without_touching_history():
    gs = GameState()
    with pytest.raises(ValueError, match="missing required field"):
        gs.apply_clue("row_total", value=3)
    assert gs.history == []


def test_apply_clue_row_total_non_numeric_value_raises_without_touching_history():
    gs = GameState()
    with pytest.raises(ValueError, match="must be an integer"):
        gs.apply_clue("row_total", row="J", value="abc")
    assert gs.history == []


def test_apply_clue_contradiction_rolls_back_and_does_not_grow_history():
    gs = GameState()
    gs.apply_clue("parity", pos="T", value="Pair")
    gs.apply_clue("segment", pos="T", seg="b", value=False)
    history_len_before = len(gs.history)
    with pytest.raises(ValueError):
        gs.apply_clue("segment", pos="T", seg="a", value=False)
    assert len(gs.history) == history_len_before
    assert gs.payload()["domains"]["T"] == [6]


def test_apply_clue_with_fallback_uses_first_non_contradicting_attempt():
    gs = GameState()
    gs.apply_clue("parity", pos="T", value="Pair")
    gs.apply_clue("segment", pos="T", seg="b", value=False)
    # After parity=Pair and seg T/b=False, T=6 (only even digit without segment b).
    # 6 has segment a, so Ta=True succeeds, Ta=False would contradict.
    # Fallback tries first and succeeds.
    payload = gs.apply_clue_with_fallback(
        "segment", [{"pos": "T", "seg": "a", "value": True}, {"pos": "T", "seg": "a", "value": False}]
    )
    assert payload["segment_state"]["Ta"] is True


def test_guess_failed_opponent_decrements_a_opp():
    gs = GameState()
    payload = gs.guess_failed({"who": "opponent"})
    assert payload["a_opp"] == 1


def test_guess_failed_me_missing_candidate_raises():
    gs = GameState()
    with pytest.raises(ValueError, match="candidate"):
        gs.guess_failed({"who": "me"})


def test_guess_failed_invalid_who_raises():
    gs = GameState()
    with pytest.raises(ValueError, match="who must be"):
        gs.guess_failed({"who": "nobody"})


def test_undo_restores_previous_clue():
    gs = GameState()
    gs.apply_clue("row_total", row="J", value=3)
    payload = gs.undo()
    assert payload["row_totals"] == {}


def test_apply_clue_fields_containing_clue_type_key_does_not_collide():
    """Regression test: clue_type is positional-only (game_state.py's
    `apply_clue(self, clue_type: str, /, **fields)`), so a fields dict
    that happens to contain a "clue_type" key can no longer raise
    `TypeError: got multiple values for argument 'clue_type'`. The real
    positional clue_type ("parity") wins; the bogus "clue_type" key in
    fields is simply unused."""
    gs = GameState()
    payload = gs.apply_clue("parity", pos="T", value="Pair", clue_type="bogus")
    assert all(d % 2 == 0 for d in payload["domains"]["T"])


def test_apply_clue_with_fallback_empty_attempts_raises_value_error():
    gs = GameState()
    with pytest.raises(ValueError, match="no attempts"):
        gs.apply_clue_with_fallback("parity", [])


def test_reset_clears_everything():
    gs = GameState()
    gs.apply_clue("row_total", row="J", value=3)
    gs.guess_failed({"who": "opponent"})
    payload = gs.reset()
    assert payload["row_totals"] == {}
    assert payload["a_me"] == 2
    assert payload["a_opp"] == 2
