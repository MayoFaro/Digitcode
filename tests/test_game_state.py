import pytest

import digitcode.game_state as game_state_module
from digitcode.game_state import EV_SCAN_MAX_N, GameState, _ev_plus_questions
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


class _FakeChild:
    """Stands in for the DigitcodeSolver _child_solver() would normally
    build and propagate -- see the monkeypatch of _child_solver in the
    _ev_plus_questions tests below. Only implements the one method
    _ev_plus_questions actually calls on a child."""

    def __init__(self, n: int) -> None:
        self._n = n

    def count_solutions_capped(self, clue, cap=None, excluded=frozenset(), should_cancel=None):
        return min(self._n, cap) if cap is not None else self._n


class _FakeSolver:
    """`answer` doubles as the branch's fake solution count, keyed via
    branch_counts (closed over by the test) -- _apply_answer_to_clue would
    normally derive a new Clue from the answer, but _ev_plus_questions only
    ever threads its return value straight into _child_solver, so a plain
    passthrough is enough to drive the fake."""

    def _apply_answer_to_clue(self, clue, q, answer, meta):
        return answer


def _patch_child_solver(monkeypatch, branch_counts: dict[str, int]) -> None:
    monkeypatch.setattr(
        game_state_module, "_child_solver",
        lambda solver, clue: _FakeChild(branch_counts[clue]),
    )


def test_ev_plus_questions_keeps_a_lopsided_but_safe_split(monkeypatch):
    """1 vs 11 (no branch in the trap zone): the exact shape from the real
    game session that prompted this feature -- a 1-solution win branch
    that's rare, but whose only alternative is safely far from the trap
    zone, must be surfaced."""
    _patch_child_solver(monkeypatch, {"win": 1, "safe": 11})
    questions = {
        "q": {"qtype": "cmp", "label": "Qui est plus grand, X ou Y ?",
              "outcomes": [{"answer": "win"}, {"answer": "safe"}]},
    }
    result = _ev_plus_questions(_FakeSolver(), None, questions, n_solutions_total=12, excluded=frozenset())
    assert [e["label"] for e in result] == ["Qui est plus grand, X ou Y ?"]
    assert result[0]["ev"] == pytest.approx(1 / 12)
    assert result[0]["p_win"] == pytest.approx(1 / 12)
    assert result[0]["p_trap"] == 0.0


def test_ev_plus_questions_excludes_a_win_paired_with_a_trap_branch(monkeypatch):
    """1 vs 2 (trap zone): a wrong guess after landing on the 2-solution
    branch hands the opponent a near-certain win, so this must NOT be
    surfaced even though it can technically end the game."""
    _patch_child_solver(monkeypatch, {"win": 1, "trap": 2})
    questions = {
        "q": {"qtype": "cmp", "label": "bad question",
              "outcomes": [{"answer": "win"}, {"answer": "trap"}]},
    }
    result = _ev_plus_questions(_FakeSolver(), None, questions, n_solutions_total=3, excluded=frozenset())
    assert result == []


def test_ev_plus_questions_excludes_questions_with_no_winning_branch():
    questions = {
        "q": {"qtype": "cmp", "label": "no win here", "outcomes": []},
    }
    result = _ev_plus_questions(_FakeSolver(), None, questions, n_solutions_total=12, excluded=frozenset())
    assert result == []


def test_ev_plus_questions_is_skipped_above_the_scan_threshold(monkeypatch):
    """Deliberately not scanned on a wide-open board (see EV_SCAN_MAX_N) --
    a singleton branch there is negligible, and scanning every candidate
    question would be needless cost that far up the game. _child_solver is
    left unpatched here: if this guard were missing, the fake data below
    (which _apply_answer_to_clue would return unmodified) would blow up
    trying to actually propagate a Clue, catching a regression either way."""
    questions = {
        "q": {"qtype": "cmp", "label": "irrelevant", "outcomes": [{"answer": "win"}]},
    }
    result = _ev_plus_questions(
        _FakeSolver(), None, questions, n_solutions_total=EV_SCAN_MAX_N + 1, excluded=frozenset(),
    )
    assert result == []


def test_ev_plus_questions_reproduces_the_real_game_scenario():
    """Integration-level regression test for the exact sequence that
    prompted this feature: at this board state, X vs Y splits into a
    1-solution branch and an 11-solution branch -- a real "coup à solution
    unique" that the plain best-question ranking buries near the bottom of
    its list (see evaluate_race_strategy's expected-reduction heuristic,
    which penalizes lopsided splits regardless of a rare winning branch)."""
    gs = GameState()
    for clue_type, fields in [
        ("row_total", dict(row="M", value=4)),
        ("comparison", dict(left="T", rel=">", right="U")),
        ("row_total", dict(row="P", value=3)),
        ("comparison", dict(left="U", rel=">", right="X")),
        ("row_total", dict(row="K", value=3)),
        ("comparison", dict(left="V", rel=">", right="U")),
        ("col_total", dict(col="C", value=2)),
        ("comparison", dict(left="W", rel=">", right="X")),
        ("col_total", dict(col="G", value=1)),
        ("col_total", dict(col="H", value=4)),
        ("comparison", dict(left="V", rel=">", right="Y")),
    ]:
        payload = gs.apply_clue(clue_type, **fields)

    assert payload["n_solutions_total"] == 12
    labels = {e["label"]: e for e in payload["ev_plus_questions"]}
    assert "Qui est plus grand, X ou Y ?" in labels
    xy = labels["Qui est plus grand, X ou Y ?"]
    assert xy["p_win"] == pytest.approx(1 / 12)
    assert xy["p_trap"] == 0.0
