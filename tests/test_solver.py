import pytest

from digitcode.solver import DigitcodeSolver, Clue


def test_count_solutions_capped_matches_exact_on_empty_board():
    s = DigitcodeSolver()
    clue = Clue()
    s.propagate(clue)
    assert s.count_solutions_capped(clue) == s.count_solutions_exact(clue, cap=None)


def test_count_solutions_capped_matches_exact_with_row_and_col_totals():
    s = DigitcodeSolver()
    clue = Clue()
    clue.row_totals["J"] = 3
    clue.col_totals["A"] = 1
    s.propagate(clue)
    assert s.count_solutions_capped(clue) == s.count_solutions_exact(clue, cap=None)


def test_count_solutions_capped_matches_exact_with_comparisons():
    s = DigitcodeSolver()
    clue = Clue()
    clue.comparisons = [("T", ">", "U"), ("W", "<", "X")]
    s.propagate(clue)
    assert s.count_solutions_capped(clue) == s.count_solutions_exact(clue, cap=None)


def test_count_solutions_capped_matches_exact_with_parity_and_segments():
    s = DigitcodeSolver()
    clue = Clue()
    clue.parity["T"] = "Pair"
    clue.segment_state[("U", "g")] = False
    s.propagate(clue)
    assert s.count_solutions_capped(clue) == s.count_solutions_exact(clue, cap=None)


def test_count_solutions_capped_stops_early_at_cap():
    s = DigitcodeSolver()
    clue = Clue()
    s.propagate(clue)
    assert s.count_solutions_capped(clue, cap=100) == 100


def test_count_solutions_capped_returns_true_count_when_below_cap():
    s = DigitcodeSolver()
    clue = Clue()
    clue.row_totals["J"] = 3
    clue.col_totals["A"] = 1
    clue.row_totals["K"] = 4
    s.propagate(clue)
    exact = s.count_solutions_exact(clue, cap=None)
    assert exact < 1_000_000
    assert s.count_solutions_capped(clue, cap=exact + 1000) == exact


def test_count_solutions_capped_zero_on_contradiction():
    s = DigitcodeSolver()
    clue = Clue()
    clue.parity["T"] = "Pair"
    s.propagate(clue)
    clue.comparisons = [("T", "<", "U"), ("U", "<", "T")]
    # comparisons are re-checked directly, so a contradictory pair yields 0
    # even though propagate() (called before this edit) wouldn't have caught it.
    assert s.count_solutions_capped(clue) == 0


def test_propagate_rejects_a_row_and_col_total_combination_unreachable_together():
    """apply_total used to silently return when a target fell outside the
    current [glob_min, glob_max] range instead of emptying a domain, so
    propagate()'s post-loop "domaine vide" check never fired and a globally
    unreachable row/col total combination was accepted as if valid (see
    web/app.py's RANGE_DISPLAY_CAP work, which surfaced this via a mismatch
    between count_solutions_capped and enumerate_solutions). V's only
    reachable value under H's own segment target (1) is disjoint from what
    G's target (2) allows for the same two positions -- jointly unreachable."""
    s = DigitcodeSolver()
    clue = Clue()
    for seg in ("a", "b", "c", "d", "e", "f"):
        clue.segment_state[("T", seg)] = True
    clue.segment_state[("T", "g")] = False
    clue.parity["U"] = "Pair"
    clue.parity["V"] = "Impair"
    clue.row_totals["J"] = 1
    clue.col_totals["D"] = 1
    clue.col_totals["G"] = 2
    clue.comparisons.append(("U", ">", "X"))
    clue.col_totals["H"] = 1
    with pytest.raises(ValueError):
        s.propagate(clue)
