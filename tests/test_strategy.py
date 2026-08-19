from digitcode.solver import DigitcodeSolver, Clue
from digitcode.strategy import _clue_signature, _solution_tuple, _solver_for


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
