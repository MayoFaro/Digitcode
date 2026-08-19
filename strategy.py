from __future__ import annotations
from typing import Dict, Optional, Tuple

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
