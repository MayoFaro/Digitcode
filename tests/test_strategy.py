from digitcode.solver import DigitcodeSolver, Clue
from digitcode.strategy import _clue_signature, _solution_tuple, _solver_for, _best_guess_value


def test_clue_signature_equal_for_equal_clues():
    c1 = Clue()
    c1.row_totals["J"] = 3
    c1.parity["T"] = "Pair"
    c2 = Clue()
    c2.row_totals["J"] = 3
    c2.parity["T"] = "Pair"
    assert _clue_signature(c1) == _clue_signature(c2)


def test_clue_signature_differs_for_different_clues():
    c1 = Clue()
    c1.row_totals["J"] = 3
    c2 = Clue()
    c2.row_totals["J"] = 4
    assert _clue_signature(c1) != _clue_signature(c2)


def test_solution_tuple_order():
    sol = {"T": 1, "U": 2, "V": 3, "W": 4, "X": 5, "Y": 6}
    assert _solution_tuple(sol) == (1, 2, 3, 4, 5, 6)


def test_solver_for_valid_clue_propagates():
    base = DigitcodeSolver()
    clue = Clue()
    clue.parity["T"] = "Pair"
    result = _solver_for(base, clue)
    assert result is not None
    assert all(d % 2 == 0 for d in result.domains["T"])


def test_solver_for_contradiction_returns_none():
    base = DigitcodeSolver()
    base.domains["T"] = {1}  # only odd value available
    clue = Clue()
    clue.parity["T"] = "Pair"  # forces T's domain to empty -> contradiction
    result = _solver_for(base, clue)
    assert result is None


def test_best_guess_value_no_attempts_returns_none():
    s = DigitcodeSolver()
    s.domains = {"T": {0}, "U": {1}, "V": {2}, "W": {3}, "X": {4}, "Y": {5, 6}}
    clue = Clue()
    result = _best_guess_value(s, clue, n_total=2, attempts=0, excluded=frozenset(), win_value=1.0, lose_recurse=lambda ne: 0.0)
    assert result is None


def test_best_guess_value_single_remaining_candidate_is_certain():
    s = DigitcodeSolver()
    s.domains = {"T": {0}, "U": {1}, "V": {2}, "W": {3}, "X": {4}, "Y": {5}}
    clue = Clue()
    result = _best_guess_value(s, clue, n_total=1, attempts=1, excluded=frozenset(), win_value=1.0, lose_recurse=lambda ne: 0.0)
    assert result == 1.0


def test_best_guess_value_two_candidates_is_fifty_fifty():
    s = DigitcodeSolver()
    s.domains = {"T": {0}, "U": {1}, "V": {2}, "W": {3}, "X": {4}, "Y": {5, 6}}
    clue = Clue()
    result = _best_guess_value(
        s, clue, n_total=2, attempts=1, excluded=frozenset(), win_value=1.0,
        lose_recurse=lambda ne: 0.0,
    )
    assert result == 0.5


def test_best_guess_value_excludes_already_tried_candidates():
    s = DigitcodeSolver()
    s.domains = {"T": {0}, "U": {1}, "V": {2}, "W": {3}, "X": {4}, "Y": {5, 6}}
    clue = Clue()
    sols = s.enumerate_solutions(clue, limit=2)
    already_tried = frozenset({_solution_tuple(sols[0])})
    result = _best_guess_value(
        s, clue, n_total=2, attempts=1, excluded=already_tried, win_value=1.0,
        lose_recurse=lambda ne: 0.0,
    )
    # only one candidate left after exclusion -> certain win
    assert result == 1.0


def test_best_guess_value_all_candidates_excluded_returns_none():
    s = DigitcodeSolver()
    s.domains = {"T": {0}, "U": {1}, "V": {2}, "W": {3}, "X": {4}, "Y": {5, 6}}
    clue = Clue()
    sols = s.enumerate_solutions(clue, limit=2)
    # exclude both remaining candidates
    already_tried = frozenset({_solution_tuple(sols[0]), _solution_tuple(sols[1])})
    result = _best_guess_value(
        s, clue, n_total=2, attempts=1, excluded=already_tried, win_value=1.0,
        lose_recurse=lambda ne: 0.0,
    )
    # no candidates remain -> return None
    assert result is None
