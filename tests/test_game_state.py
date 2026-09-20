import pytest

from digitcode.game_state import GameState
from digitcode.solver import Cancelled


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


def test_build_payload_from_matches_payload_on_the_same_state():
    """build_payload_from is payload()'s guts, extracted to take explicit
    inputs instead of reading self.* so it can run on a snapshot from a
    background thread (see native/solve_worker.py) -- this is a pure
    refactor, so it must produce the exact same result as payload() for the
    same state."""
    gs = GameState()
    gs.apply_clue("row_total", row="J", value=3)
    gs.apply_clue("comparison", left="T", rel=">", right="U")
    assert gs.build_payload_from(gs.clue, gs.a_me, gs.a_opp, gs.my_excluded) == gs.payload()


def test_build_payload_from_raises_cancelled_when_asked_to_stop():
    gs = GameState()
    with pytest.raises(Cancelled):
        gs.build_payload_from(gs.clue, gs.a_me, gs.a_opp, gs.my_excluded, should_cancel=lambda: True)


def test_apply_clue_fast_mutates_without_computing_the_display_payload():
    gs = GameState()
    result = gs.apply_clue_fast("parity", pos="T", value="Pair")
    assert result is None
    assert gs.clue.parity["T"] == "Pair"
    assert all(d % 2 == 0 for d in gs.payload()["domains"]["T"])


def test_apply_clue_fast_contradiction_rolls_back_and_does_not_grow_history():
    """Same rollback guarantee as apply_clue's equivalent test, but
    apply_clue_fast validates via a bare propagate() instead of a full
    payload() -- must still reject and roll back identically."""
    gs = GameState()
    gs.apply_clue_fast("parity", pos="T", value="Pair")
    gs.apply_clue_fast("segment", pos="T", seg="b", value=False)
    history_len_before = len(gs.history)
    with pytest.raises(ValueError):
        gs.apply_clue_fast("segment", pos="T", seg="a", value=False)
    assert len(gs.history) == history_len_before
    assert gs.payload()["domains"]["T"] == [6]


def test_apply_clue_fast_unknown_type_raises():
    gs = GameState()
    with pytest.raises(ValueError, match="unknown clue type"):
        gs.apply_clue_fast("bogus")


def test_apply_clue_with_fallback_fast_uses_first_non_contradicting_attempt():
    gs = GameState()
    gs.apply_clue_fast("parity", pos="T", value="Pair")
    gs.apply_clue_fast("segment", pos="T", seg="b", value=False)
    result = gs.apply_clue_with_fallback_fast(
        "segment", [{"pos": "T", "seg": "a", "value": True}, {"pos": "T", "seg": "a", "value": False}]
    )
    assert result is None
    assert gs.clue.segment_state[("T", "a")] is True


def test_apply_clue_with_fallback_fast_empty_attempts_raises_value_error():
    gs = GameState()
    with pytest.raises(ValueError, match="no attempts"):
        gs.apply_clue_with_fallback_fast("parity", [])


def test_build_quick_payload_from_reflects_the_clue_without_the_expensive_fields():
    gs = GameState()
    gs.apply_clue_fast("row_total", row="J", value=3)
    quick = GameState.build_quick_payload_from(gs.clue)
    assert quick["row_totals"] == {"J": 3}
    assert "domains" in quick
    assert "n_solutions_total" not in quick
    assert "race" not in quick


def test_build_quick_payload_from_raises_on_a_contradictory_clue():
    gs = GameState()
    gs.apply_clue_fast("parity", pos="T", value="Pair")
    gs.apply_clue_fast("segment", pos="T", seg="b", value=False)
    gs.clue.segment_state[("T", "a")] = False  # bypass apply_clue_fast's own rollback
    with pytest.raises(ValueError):
        GameState.build_quick_payload_from(gs.clue)
