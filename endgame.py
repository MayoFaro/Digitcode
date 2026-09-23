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
    full_mask = (1 << len(candidates)) - 1
    questions: List[EQuestion] = []
    for q in solver.enumerate_all_questions(clue, should_cancel=should_cancel):
        answers: List[str] = []
        classes: List[int] = []
        covered = 0
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
                covered |= mask
        # A question whose enumerated outcomes don't cover every candidate
        # would silently make the branch probabilities at this node sum to
        # < 1 (some candidate has no answer under this question). Drop it
        # rather than search over an unsound partition.
        if len(classes) > 1 and covered == full_mask:
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


def _bits(mask: int) -> List[int]:
    out = []
    i = 0
    while mask:
        if mask & 1:
            out.append(i)
        mask >>= 1
        i += 1
    return out


def _keep(e: int, S: int) -> int:
    """My failed guess only matters while it is still in the public pool."""
    return e if e >= 0 and (S >> e) & 1 else NO_CANDIDATE


class EndgameSolver:
    """Memoised alternating-turn expectimax over candidate bitmasks.

    State: (S public pool, e my relevant failed guess or -1, a_me, a_opp,
    mover, m_fail = public pool size at the opponent's first failure or 0).
    At most one failure per side matters: a second one takes that player
    to 0 attempts, a terminal state. Value = my win probability.

    The three flags exist so the engine can reproduce strategy.py's exact
    search (all False) -- the non-regression anchor -- and so a self-play
    benchmark can compare the two models. Production uses all True.

    Approximation (spec, "information privée"): the opponent minimises my
    value computed with MY failed guess (as if it knew it -- pessimistic
    for me), and its choices don't depend on its own failed code (only its
    hit probability does, exactly)."""

    def __init__(
        self, n: int, questions: List[EQuestion], *, choose_guess: bool = True,
        interior_direct_guess: bool = True, track_opp_fail: bool = True,
        deadline: Optional[float] = None, should_cancel: Callable[[], bool] = _never,
    ) -> None:
        self.n = n
        self.questions = questions
        self.choose_guess = choose_guess
        self.interior_direct_guess = interior_direct_guess
        self.track_opp_fail = track_opp_fail
        self.deadline = deadline
        self.should_cancel = should_cancel
        self._memo: Dict[tuple, float] = {}
        self._informative_cache: Dict[int, List[EQuestion]] = {}

    def _check_budget(self) -> None:
        if self.should_cancel():
            raise Cancelled()
        if self.deadline is not None and time.monotonic() > self.deadline:
            raise EndgameBudgetExceeded()

    def informative(self, S: int) -> List[EQuestion]:
        qs = self._informative_cache.get(S)
        if qs is None:
            qs = [q for q in self.questions if sum(1 for c in q.classes if c & S) > 1]
            self._informative_cache[S] = qs
        return qs

    def value(self, S: int, e: int, a_me: int, a_opp: int, mover: int, m_fail: int) -> float:
        if a_me == 0 and a_opp == 0:
            return 0.5
        if a_me == 0:
            return 0.0
        if a_opp == 0:
            return 1.0
        key = (S, e, a_me, a_opp, mover, m_fail)
        cached = self._memo.get(key)
        if cached is not None:
            return cached
        self._check_budget()
        mine = S & ~(1 << e) if e >= 0 else S
        if mine == 0:
            result = 0.0
        elif mover == ME:
            result = self._me_value(S, e, mine, a_me, a_opp, m_fail)
        else:
            result = self._opp_value(S, e, mine, a_me, a_opp, m_fail)
        self._memo[key] = result
        return result

    # --- my moves -------------------------------------------------------

    def my_guess_value(self, S: int, pool: int, g: int, a_me: int, a_opp: int, m_fail: int) -> float:
        k = pool.bit_count()
        if k == 1:
            return 1.0
        return 1.0 / k + (1.0 - 1.0 / k) * self.value(S, g, a_me - 1, a_opp, OPP, m_fail)

    def best_my_guess(self, S: int, pool: int, a_me: int, a_opp: int, m_fail: int) -> Tuple[float, int]:
        choices = _bits(pool)
        if not self.choose_guess:
            choices = choices[:1]
        best_v, best_g = -1.0, choices[0]
        for g in choices:
            v = self.my_guess_value(S, pool, g, a_me, a_opp, m_fail)
            if v > best_v:
                best_v, best_g = v, g
        return best_v, best_g

    def _my_question(
        self, S: int, e: int, mine: int, q: EQuestion, a_me: int, a_opp: int, m_fail: int,
    ) -> Tuple[float, List[dict]]:
        n_mine = mine.bit_count()
        total = 0.0
        branches: List[dict] = []
        for ci, cls in enumerate(q.classes):
            sub = cls & mine
            if not sub:
                continue
            S2 = cls & S
            wait = self.value(S2, _keep(e, S2), a_me, a_opp, OPP, m_fail)
            guess, g = self.best_my_guess(S2, sub, a_me, a_opp, m_fail)
            prob = sub.bit_count() / n_mine
            if guess >= wait:
                branch = {"ci": ci, "n": sub.bit_count(), "prob": prob, "action": "guess", "g": g, "value": guess}
            else:
                branch = {"ci": ci, "n": sub.bit_count(), "prob": prob, "action": "wait", "g": None, "value": wait}
            total += prob * branch["value"]
            branches.append(branch)
        return total, branches

    def _me_value(self, S: int, e: int, mine: int, a_me: int, a_opp: int, m_fail: int) -> float:
        qs = self.informative(S)
        options: List[float] = []
        if self.interior_direct_guess or not qs:
            options.append(self.best_my_guess(S, mine, a_me, a_opp, m_fail)[0])
        for q in qs:
            options.append(self._my_question(S, e, mine, q, a_me, a_opp, m_fail)[0])
        return max(options)

    # --- opponent moves -------------------------------------------------

    def _opp_guess(self, S: int, e: int, a_me: int, a_opp: int, m_fail: int) -> float:
        s = S.bit_count()
        hit = opp_hit_probability(s, m_fail if self.track_opp_fail else 0)
        if hit >= 1.0:
            return 0.0
        new_m = m_fail if m_fail else (s if self.track_opp_fail else 0)
        return (1.0 - hit) * self.value(S, e, a_me, a_opp - 1, ME, new_m)

    def _opp_value(self, S: int, e: int, mine: int, a_me: int, a_opp: int, m_fail: int) -> float:
        qs = self.informative(S)
        n_mine = mine.bit_count()
        options: List[float] = []
        if self.interior_direct_guess or not qs:
            options.append(self._opp_guess(S, e, a_me, a_opp, m_fail))
        for q in qs:
            total = 0.0
            for cls in q.classes:
                sub = cls & mine
                if not sub:
                    continue
                S2 = cls & S
                e2 = _keep(e, S2)
                wait = self.value(S2, e2, a_me, a_opp, ME, m_fail)
                guess = self._opp_guess(S2, e2, a_me, a_opp, m_fail)
                total += sub.bit_count() / n_mine * min(wait, guess)
            options.append(total)
        return min(options)

    # --- root -----------------------------------------------------------

    def analyze(self, S: int, e: int, a_me: int, a_opp: int, m_fail: int) -> dict:
        """Every option at the root (my turn), with raw candidate/question
        indices. The root always offers the direct guess, whatever
        `interior_direct_guess` says -- strategy.py does the same, which
        is what makes the legacy-mode comparison exact."""
        e = _keep(e, S)
        mine = S & ~(1 << e) if e >= 0 else S
        if a_me == 0 or mine == 0:
            p = 0.5 if (a_me == 0 and a_opp == 0) else 0.0
            return {"p_win": p, "decision": "none", "direct": None, "questions": []}
        v, g = self.best_my_guess(S, mine, a_me, a_opp, m_fail)
        direct = {"g": g, "p_win": v}
        questions = []
        for qi, q in enumerate(self.questions):
            if sum(1 for c in q.classes if c & S) <= 1:
                continue
            qv, branches = self._my_question(S, e, mine, q, a_me, a_opp, m_fail)
            questions.append({"qi": qi, "p_win": qv, "branches": branches})
        questions.sort(key=lambda r: -r["p_win"])
        if not questions or direct["p_win"] >= questions[0]["p_win"]:
            return {"p_win": direct["p_win"], "decision": "guess_now", "direct": direct, "questions": questions}
        return {"p_win": questions[0]["p_win"], "decision": "question", "direct": direct, "questions": questions}


def evaluate_endgame(
    solver: DigitcodeSolver, clue: Clue, a_me: int, a_opp: int,
    my_excluded: FrozenSet[Candidate], opp_fail_pool_size: int = 0, *,
    n_max: int = ENDGAME_N_MAX, time_budget_s: float = ENDGAME_TIME_BUDGET_S,
    should_cancel: Callable[[], bool] = _never,
) -> Optional[dict]:
    """Display-ready endgame recommendation, or None when the public pool
    is empty or larger than `n_max`. `solver` must already be propagated
    for `clue`."""
    universe = build_universe(solver, clue, n_max, should_cancel)
    if universe is None:
        return None
    candidates, questions = universe
    n = len(candidates)
    full = (1 << n) - 1
    index = {c: i for i, c in enumerate(candidates)}
    excluded_idx = sorted(index[c] for c in my_excluded if c in index)
    e = excluded_idx[0] if excluded_idx else NO_CANDIDATE
    mine = full
    for i in excluded_idx:
        mine &= ~(1 << i)
    engine = EndgameSolver(
        n, questions, deadline=time.monotonic() + time_budget_s, should_cancel=should_cancel,
    )
    try:
        raw = engine.analyze(full, e, a_me, a_opp, opp_fail_pool_size)
    except EndgameBudgetExceeded:
        return {"complete": False, "n_public": n}

    def fmt_question(r: dict, with_branches: bool) -> dict:
        q = questions[r["qi"]]
        out = {"qtype": q.qtype, "label": q.label, "p_win": r["p_win"]}
        if with_branches:
            out["branches"] = [
                {
                    "answer": q.answers[b["ci"]],
                    "n": b["n"],
                    "prob": b["prob"],
                    "action": b["action"],
                    "code": code_to_string(candidates[b["g"]]) if b["g"] is not None else None,
                    "value": b["value"],
                }
                for b in r["branches"]
            ]
        return out

    direct = raw["direct"]
    return {
        "complete": True,
        "n_public": n,
        "n_mine": mine.bit_count(),
        "p_win": raw["p_win"],
        "decision": raw["decision"],
        "guess_now": (
            {"code": code_to_string(candidates[direct["g"]]), "p_win": direct["p_win"]}
            if direct is not None else None
        ),
        "best_question": fmt_question(raw["questions"][0], True) if raw["questions"] else None,
        "ranked_questions": [fmt_question(r, False) for r in raw["questions"]],
    }
