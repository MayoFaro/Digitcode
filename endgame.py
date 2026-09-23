"""Exact endgame engine for small boards.

See docs/superpowers/specs/2026-09-23-endgame-engine-design.md. Instead of
re-propagating a Clue at every search node (what makes strategy.py's exact
search cost ~20 s at N=6), the N remaining candidate codes are enumerated
once and every question is turned into a partition of them (one bitmask
per answer). A game state is then just a handful of small ints, which
makes an exact, memoised search affordable up to N ~ 20.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Dict, FrozenSet, List, Optional, Tuple

from .mapping import POSITIONS
from .solver import Cancelled, Clue, DigitcodeSolver

Candidate = Tuple[int, int, int, int, int, int]

# Measured on random real games (prototype, 2026-09-23): N <= 20 solves in
# < 1.5 s, N = 24 in 1-3 s, N = 28 in ~31 s. 20 keeps the worst case far
# inside the 30 s budget the user accepts in the endgame.
ENDGAME_N_MAX = 20
ENDGAME_TIME_BUDGET_S = 30.0
# Cap for counting the public pool when the opponent fails a guess (see
# GameState.guess_failed). Past ~1000 the opponent's failed code is almost
# surely gone from any endgame pool, so an undercount there is harmless.
OPP_FAIL_COUNT_CAP = 1000

ME = 0
OPP = 1
NO_CANDIDATE = -1


def _never() -> bool:
    return False


class EndgameBudgetExceeded(Exception):
    pass


@dataclass(frozen=True)
class EQuestion:
    """A question as a partition of the candidate universe: `classes[i]` is
    the bitmask of candidates for which the answer is `answers[i]`. Only
    non-empty classes are kept, and only questions with >= 2 of them."""
    qtype: str
    label: str
    answers: Tuple[str, ...]
    classes: Tuple[int, ...]


def code_consistent(code: Candidate, clue: Clue) -> bool:
    """True iff the full code satisfies every constraint of `clue`.
    Propagating over singleton domains is exact: every propagator either
    keeps a singleton or empties it (-> ValueError)."""
    s = DigitcodeSolver()
    s.domains = {p: {v} for p, v in zip(POSITIONS, code)}
    try:
        s.propagate(clue)
    except ValueError:
        return False
    return all(len(s.domains[p]) == 1 for p in POSITIONS)


def code_to_string(code: Candidate) -> str:
    return f"{code[0]}{code[1]}{code[2]} {code[3]}{code[4]}{code[5]}"


def build_universe(
    solver: DigitcodeSolver, clue: Clue, n_max: int = ENDGAME_N_MAX,
    should_cancel: Callable[[], bool] = _never,
) -> Optional[Tuple[List[Candidate], List[EQuestion]]]:
    """Candidates (public pool: my own failed guesses are NOT removed -- the
    opponent can't know them) and every informative question as a
    partition. None if there are no solutions or more than `n_max`."""
    sols = solver.enumerate_solutions(clue, limit=n_max + 1, should_cancel=should_cancel)
    if not sols or len(sols) > n_max:
        return None
    candidates: List[Candidate] = [tuple(sol[p] for p in POSITIONS) for sol in sols]
    questions: List[EQuestion] = []
    for q in solver.enumerate_all_questions(clue, should_cancel=should_cancel):
        answers: List[str] = []
        classes: List[int] = []
        for out in q["outcomes"]:
            if should_cancel():
                raise Cancelled()
            child = solver._apply_answer_to_clue(clue, q, out["answer"], 0)
            mask = 0
            for i, code in enumerate(candidates):
                if code_consistent(code, child):
                    mask |= 1 << i
            if mask:
                answers.append(out["answer"])
                classes.append(mask)
        if len(classes) > 1:
            questions.append(EQuestion(q["qtype"], q["label"], tuple(answers), tuple(classes)))
    return candidates, questions


def opp_hit_probability(s: int, m_fail: int) -> float:
    """Probability the opponent's next guess is right, from my point of view.

    `s` = public pool size now, `m_fail` = public pool size when the
    opponent failed its first guess (0 = no failure yet). Its failed code x
    is uniform over the failure-time pool minus the truth; the pool only
    shrinks, so P(x still in pool) = (s-1)/(m-1) and it guesses uniformly
    over the pool minus x. For s = 1 the pool is the truth alone (x can't
    be in it), so the hit is certain -- the closed form's first term would
    be a 0/0 there."""
    if s <= 1:
        return 1.0
    if not m_fail:
        return 1.0 / s
    m = max(m_fail, s)
    return 1.0 / (m - 1) + (m - s) / ((m - 1) * s)
