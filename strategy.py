from __future__ import annotations
from typing import Callable, Dict, FrozenSet, Optional, Tuple

from .solver import DigitcodeSolver, Clue

Candidate = Tuple[int, int, int, int, int, int]


def _clue_signature(clue: Clue) -> tuple:
    return (
        tuple(sorted(clue.row_totals.items())),
        tuple(sorted(clue.col_totals.items())),
        tuple(sorted(clue.parity.items())),
        tuple(sorted(clue.comparisons)),
        tuple(sorted(clue.segment_state.items())),
    )


def _solution_tuple(sol: Dict[str, int]) -> Candidate:
    return (sol["T"], sol["U"], sol["V"], sol["W"], sol["X"], sol["Y"])


def _solver_for(base: DigitcodeSolver, clue: Clue) -> Optional[DigitcodeSolver]:
    child = DigitcodeSolver()
    child.domains = {p: set(v) for p, v in base.domains.items()}
    try:
        child.propagate(clue)
    except ValueError:
        return None
    return child


def _best_guess_value(
    solver: DigitcodeSolver,
    clue: Clue,
    n_total: int,
    attempts: int,
    excluded: FrozenSet[Candidate],
    win_value: float,
    lose_recurse: Callable[[FrozenSet[Candidate]], float],
) -> Optional[float]:
    """Value of attempting a guess now instead of waiting. None if no
    attempt is available."""
    if attempts <= 0:
        return None
    candidates = [_solution_tuple(s) for s in solver.enumerate_solutions(clue, limit=n_total + 1)]
    remaining = [c for c in candidates if c not in excluded]
    n_remaining = len(remaining)
    if n_remaining == 0:
        return None
    p_hit = 1.0 / n_remaining
    p_miss = 1.0 - p_hit
    if p_miss == 0.0:
        return win_value
    # Which specific remaining candidate is tried doesn't matter by symmetry.
    new_excluded = excluded | {remaining[0]}
    return p_hit * win_value + p_miss * lose_recurse(new_excluded)
