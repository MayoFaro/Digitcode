# Endgame Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An exact endgame engine for boards with at most `ENDGAME_N_MAX` solutions. It says whether to guess now or ask a question, which question, and which code to guess after each answer. It is shown in the native app as a "Fin de partie" block.

**Architecture:** New module `endgame.py`. It enumerates the N candidate codes once and turns every question into a bitmask partition of those candidates. It then runs a memoised alternating-turn expectimax over `(pool S, my failed guess e, a_me, a_opp, mover, m_fail)`. `game_state.py` gets `opp_fail_pool_size` and `build_endgame_from`. The native app runs it in a separate cancellable `EndgameWorker` after each full payload and renders the result in `SolutionsPanel`. The existing engine (`strategy.py`) and the payload stay unchanged.

**Tech Stack:** Python ≥3.10 (`int.bit_count`), pytest, PySide6 (QThread/Signal).

**Spec:** `docs/superpowers/specs/2026-09-23-endgame-engine-design.md`

## Global Constraints

- Run everything from the repo root `/home/cedric/Documents/digitcode` with the venv: `.venv/bin/python -m pytest ...`. Plain `python` does not exist on this machine.
- Imports use the package name `digitcode.` (for example `from digitcode.endgame import ...`). Inside the package, use relative imports (`from .solver import ...`).
- `strategy.py`, `solver.py` and the web app are **not modified**.
- Opponent-hit probability: `1/(m−1) + (m−s)/((m−1)·s)` for s ≥ 2, **and 1.0 when s = 1**. The spec's formula omits the s = 1 case, and Task 7 corrects the spec.
- `ENDGAME_N_MAX = 20` and `ENDGAME_TIME_BUDGET_S = 30.0`. Prototype measurements on random real games: N ≤ 20 solves in < 1.5 s, N = 24 in 1–3 s, N = 28 in 31 s.
- UI strings are in French and match the existing panel style (percentages printed as `f"{x * 100:.0f}%"`).
- The full existing suite (195 tests, about 5 min) must still pass at the end.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

---

### Task 1: Candidate universe (`endgame.py` foundations)

**Files:**
- Create: `endgame.py`
- Test: `tests/test_endgame.py`

**Interfaces:**
- Produces:
  - `Candidate = Tuple[int, int, int, int, int, int]` (digits for positions T,U,V,W,X,Y)
  - `ENDGAME_N_MAX: int = 20`, `ENDGAME_TIME_BUDGET_S: float = 30.0`, `OPP_FAIL_COUNT_CAP: int = 1000`
  - `ME = 0`, `OPP = 1`, `NO_CANDIDATE = -1`
  - `class EndgameBudgetExceeded(Exception)`
  - `@dataclass(frozen=True) class EQuestion: qtype: str; label: str; answers: Tuple[str, ...]; classes: Tuple[int, ...]` (parallel tuples; every class is a non-empty bitmask; there are at least 2 classes; the classes partition the universe)
  - `code_consistent(code: Candidate, clue: Clue) -> bool`
  - `build_universe(solver: DigitcodeSolver, clue: Clue, n_max: int = ENDGAME_N_MAX, should_cancel=_never) -> Optional[Tuple[List[Candidate], List[EQuestion]]]` (returns `None` when there are 0 or more than `n_max` solutions)
  - `opp_hit_probability(s: int, m_fail: int) -> float`
  - `code_to_string(code: Candidate) -> str` (format `"123 456"`)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_endgame.py`:

```python
import pytest

from digitcode.endgame import (
    EQuestion,
    build_universe,
    code_consistent,
    code_to_string,
    opp_hit_probability,
)
from digitcode.solver import Clue

from tests.conftest import make_solver


def test_every_enumerated_candidate_is_consistent_with_its_clue():
    s = make_solver({"X": {5, 6}, "Y": {1, 2, 3}})
    candidates, _ = build_universe(s, Clue())
    assert len(candidates) == 6
    assert all(code_consistent(c, Clue()) for c in candidates)


def test_every_question_partitions_the_universe():
    s = make_solver({"X": {5, 6}, "Y": {1, 2, 3}})
    candidates, questions = build_universe(s, Clue())
    full = (1 << len(candidates)) - 1
    assert questions, "a 6-candidate board must have informative questions"
    for q in questions:
        assert isinstance(q, EQuestion)
        assert len(q.classes) == len(q.answers) >= 2
        union = 0
        for cls in q.classes:
            assert cls != 0
            assert union & cls == 0, f"{q.label}: classes overlap"
            union |= cls
        assert union == full, f"{q.label}: classes do not cover the universe"


def test_a_candidate_is_inconsistent_with_an_answer_outside_its_class():
    s = make_solver({"X": {5, 6}, "Y": {1, 2, 3}})
    candidates, questions = build_universe(s, Clue())
    q = questions[0]
    idx_in_first = next(i for i in range(len(candidates)) if q.classes[0] >> i & 1)
    # Rebuild the clue for the SECOND answer and check the first-class
    # candidate is rejected by it.
    raw_q = next(r for r in s.enumerate_all_questions(Clue()) if r["label"] == q.label)
    child = s._apply_answer_to_clue(Clue(), raw_q, q.answers[1], 0)
    assert not code_consistent(candidates[idx_in_first], child)


def test_build_universe_returns_none_above_n_max():
    s = make_solver({"X": {5, 6}, "Y": {1, 2, 3}})
    assert build_universe(s, Clue(), n_max=5) is None


@pytest.mark.parametrize("s, m_fail, expected", [
    (3, 0, 1 / 3),       # no opponent failure: uniform over the public pool
    (2, 0, 0.5),
    (1, 0, 1.0),
    (2, 4, 2 / 3),       # failed at m=4, pool now 2: spec's worked example
    (3, 3, 0.5),         # failed on this very pool: 1/(m-1)
    (4, 4, 1 / 3),
    (1, 4, 1.0),         # only the truth left: certain hit (formula's 0/0 case)
    (5, 3, 0.25),        # inconsistent m < s is clamped to m = s
])
def test_opp_hit_probability(s, m_fail, expected):
    assert opp_hit_probability(s, m_fail) == pytest.approx(expected)


def test_code_to_string():
    assert code_to_string((1, 2, 3, 4, 5, 6)) == "123 456"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_endgame.py -v`
Expected: collection ERROR, `ModuleNotFoundError: No module named 'digitcode.endgame'`

- [ ] **Step 3: Write the implementation**

Create `endgame.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_endgame.py -v`
Expected: all PASS (12 tests).

- [ ] **Step 5: Commit**

```bash
git add endgame.py tests/test_endgame.py
git commit -m "feat(endgame): candidate universe and opponent-hit belief

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Exact alternating search (`EndgameSolver.value`)

**Files:**
- Modify: `endgame.py` (append)
- Test: `tests/test_endgame.py` (append)

**Interfaces:**
- Consumes: Task 1's `EQuestion`, `opp_hit_probability`, `ME`, `OPP`, `NO_CANDIDATE`, `EndgameBudgetExceeded`, `Cancelled`.
- Produces:
  - `class EndgameSolver(n: int, questions: List[EQuestion], *, choose_guess=True, interior_direct_guess=True, track_opp_fail=True, deadline: Optional[float] = None, should_cancel=_never)`
  - `.questions: List[EQuestion]` (public attribute)
  - `.value(S: int, e: int, a_me: int, a_opp: int, mover: int, m_fail: int) -> float` (my win probability)
  - `.my_guess_value(S: int, pool: int, g: int, a_me: int, a_opp: int, m_fail: int) -> float`
  - `.best_my_guess(S: int, pool: int, a_me: int, a_opp: int, m_fail: int) -> Tuple[float, int]` (value and candidate index; the first maximum wins)
  - `._my_question(S, e, mine, q, a_me, a_opp, m_fail) -> Tuple[float, List[dict]]`. Each branch dict holds `{"ci": int, "n": int, "prob": float, "action": "guess"|"wait", "g": Optional[int], "value": float}`. Task 3 uses this.

Model recap (all from the spec):
- **Terminals:** both players at 0 attempts → 0.5. `a_me == 0` → 0.0. `a_opp == 0` → 1.0. My pool empty → 0.0.
- My pool is `mine = S` minus my failed guess `e` (when `e` is in `S`).
- **At my turn**, I take the max over:
  - a direct guess, when `interior_direct_guess` is set or no question is informative;
  - each question that is informative on the public `S` (at least 2 classes intersect `S`). Each class `c` with `c & mine != 0` has weight `|c ∩ mine| / |mine|`. The child pool is `S2 = c & S`. The branch value is max(wait → opponent's turn, best guess in `c ∩ mine`).
- **At the opponent's turn**, it takes the min over the same families. Its guess succeeds with `opp_hit_probability(|S|, m_fail if track_opp_fail else 0)`. A failure decrements `a_opp` and sets `m_fail = |S|` (first failure only).
- **My guess `g`:** `1/k + (1 − 1/k) · value(S, g, a_me − 1, a_opp, OPP, m_fail)` with `k = |pool|`. It returns 1.0 when `k == 1`. `choose_guess=False` only tries the lowest-index candidate (legacy behaviour).
- **No "pass" move:** only questions informative on the public pool are allowed. This is the spec's open question 1, deliberately left out.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_endgame.py`:

```python
import time

from digitcode.endgame import ME, OPP, EndgameBudgetExceeded, EndgameSolver
from digitcode.solver import Cancelled

A, B, C, D = 1, 2, 4, 8
FULL_FLAGS = dict(choose_guess=True, interior_direct_guess=True, track_opp_fail=True)
LEGACY_FLAGS = dict(choose_guess=False, interior_direct_guess=False, track_opp_fail=False)


def _toy(n, partitions, **flags):
    qs = [
        EQuestion("seg", f"q{i}", tuple(str(k) for k in range(len(p))), tuple(p))
        for i, p in enumerate(partitions)
    ]
    return EndgameSolver(n, qs, **flags)


# Expected values: the first three are derived by hand in the plan's
# comments below; the others were computed with the validated prototype.
# N2 none: guess 1/2; if wrong the opponent (no question available) must
# guess 1/2, else I win -> 1/2 + 1/2*1/2 = 3/4.
# N3 A|BC: ask; A-branch (1/3) wins; BC-branch: guess 1/2, if wrong the
# opponent must guess 1/2 -> 3/4; total 1/3 + 2/3*3/4 = 5/6.
@pytest.mark.parametrize("n, partitions, flags, expected", [
    (2, [(A, B)], FULL_FLAGS, 1.0),
    (2, [], FULL_FLAGS, 0.75),
    (3, [(A, B | C)], FULL_FLAGS, 5 / 6),
    (3, [(A, B | C), (A | B, C)], FULL_FLAGS, 2 / 3),
    (4, [(A | B, C | D)], FULL_FLAGS, 0.75),
    (4, [(A | B, C | D), (A, B | C | D)], FULL_FLAGS, 0.625),
    (4, [(A | B, C | D), (A | C, B | D)], FULL_FLAGS, 0.625),
    (4, [(A | B, C | D), (A | C, B | D)], LEGACY_FLAGS, 0.5),
])
def test_toy_values(n, partitions, flags, expected):
    eng = _toy(n, partitions, **flags)
    assert eng.value((1 << n) - 1, -1, 2, 2, ME, 0) == pytest.approx(expected)


def test_which_code_is_guessed_matters():
    eng = _toy(4, [(A | B, C | D), (A, B | C | D)], **FULL_FLAGS)
    values = [eng.my_guess_value(15, 15, g, 2, 2, 0) for g in range(4)]
    assert values == pytest.approx([0.5, 5 / 12, 7 / 12, 7 / 12])
    v, g = eng.best_my_guess(15, 15, 2, 2, 0)
    assert (v, g) == (pytest.approx(7 / 12), 2)


def test_legacy_guess_choice_takes_the_first_candidate():
    eng = _toy(4, [(A | B, C | D), (A, B | C | D)], **LEGACY_FLAGS)
    v, g = eng.best_my_guess(15, 15, 2, 2, 0)
    assert g == 0


@pytest.mark.parametrize("a_me, a_opp, expected", [(0, 1, 0.0), (1, 0, 1.0), (0, 0, 0.5)])
def test_attempt_terminals(a_me, a_opp, expected):
    eng = _toy(3, [(A, B | C)], **FULL_FLAGS)
    assert eng.value(7, -1, a_me, a_opp, OPP, 0) == expected


def test_opponent_failure_tracking_lowers_my_value():
    # Same state; the opponent failed at m=3 and the pool is still 3, so
    # its next guess is 1/2 instead of 1/3.
    eng = _toy(3, [], **FULL_FLAGS)
    tracked = eng.value(7, -1, 2, 1, OPP, 3)
    untracked = _toy(3, [], choose_guess=True, interior_direct_guess=True, track_opp_fail=False).value(7, -1, 2, 1, OPP, 3)
    assert tracked < untracked


def test_deadline_in_the_past_raises_budget_exceeded():
    eng = _toy(4, [(A | B, C | D)], deadline=time.monotonic() - 1, **FULL_FLAGS)
    with pytest.raises(EndgameBudgetExceeded):
        eng.value(15, -1, 2, 2, ME, 0)


def test_should_cancel_raises_cancelled():
    eng = _toy(4, [(A | B, C | D)], should_cancel=lambda: True, **FULL_FLAGS)
    with pytest.raises(Cancelled):
        eng.value(15, -1, 2, 2, ME, 0)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_endgame.py -v`
Expected: ImportError for `EndgameSolver` (the whole module fails to collect).

- [ ] **Step 3: Write the implementation**

Append to `endgame.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_endgame.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add endgame.py tests/test_endgame.py
git commit -m "feat(endgame): exact alternating search over candidate bitmasks

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Root analysis and `evaluate_endgame` (with non-regression against `strategy.py`)

**Files:**
- Modify: `endgame.py` (append)
- Test: `tests/test_endgame.py` (append)

**Interfaces:**
- Consumes: Task 2's `EndgameSolver` (`value`, `best_my_guess`, `_my_question`, `informative`, `questions`) and Task 1's `build_universe` and `code_to_string`.
- Produces:
  - `EndgameSolver.analyze(S: int, e: int, a_me: int, a_opp: int, m_fail: int) -> dict` returning raw indices: `{"p_win": float, "decision": "guess_now"|"question"|"none", "direct": {"g": int, "p_win": float} | None, "questions": [{"qi": int, "p_win": float, "branches": [branch dicts from _my_question]}] sorted by p_win desc}`. `qi` indexes `self.questions`.
  - `evaluate_endgame(solver, clue, a_me, a_opp, my_excluded: FrozenSet[Candidate], opp_fail_pool_size: int = 0, *, n_max=ENDGAME_N_MAX, time_budget_s=ENDGAME_TIME_BUDGET_S, should_cancel=_never) -> Optional[dict]`. It returns `None` when there are more than `n_max` (or 0) public solutions. On budget overrun it returns `{"complete": False, "n_public": int}`. Otherwise it returns:
    ```
    {"complete": True, "n_public": int, "n_mine": int, "p_win": float,
     "decision": "guess_now"|"question"|"none",
     "guess_now": {"code": "123 456", "p_win": float} | None,
     "best_question": {"qtype", "label", "p_win", "branches": [
         {"answer": str, "n": int, "prob": float, "action": "guess"|"wait",
          "code": str | None, "value": float}]} | None,
     "ranked_questions": [{"qtype", "label", "p_win"}, ...]}   # all, desc
    ```
  - Tie rule (same as `strategy.py`): `decision == "guess_now"` when the direct value ≥ the best question value.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_endgame.py`:

```python
from digitcode.endgame import evaluate_endgame
from digitcode.strategy import evaluate_race_strategy


def _legacy_root_p_win(solver):
    candidates, questions = build_universe(solver, Clue())
    eng = EndgameSolver(len(candidates), questions, **LEGACY_FLAGS)
    return eng.analyze((1 << len(candidates)) - 1, -1, 2, 2, 0)["p_win"]


@pytest.mark.parametrize("free", [
    {"X": {5, 6}, "Y": {1, 2}},      # N=4 (old engine: guess now, 0.625)
    {"X": {5, 6}, "Y": {1, 2, 3}},   # N=6 (old engine: 0.583, ~3 s)
])
def test_legacy_mode_matches_the_existing_exact_engine_live(free):
    s = make_solver(free)
    old = evaluate_race_strategy(
        s, Clue(), 2, 2, n_exact_max=9, n_beam_max=12, time_budget_s=120, node_budget=10**7,
    )
    assert old["exact"]
    assert _legacy_root_p_win(s) == pytest.approx(old["p_win"])


@pytest.mark.parametrize("free, old_p_win", [
    # Measured 2026-09-23 with strategy.evaluate_race_strategy in full exact
    # mode (21 s and 23 s -- too slow to run live in the suite).
    ({"Y": {6, 7, 8, 9, 0, 1}}, 0.75),
    ({"X": {5, 6}, "Y": {1, 2, 3, 4}}, 0.625),
])
def test_legacy_mode_matches_the_existing_exact_engine_recorded(free, old_p_win):
    assert _legacy_root_p_win(make_solver(free)) == pytest.approx(old_p_win)


def test_analyze_prefers_guessing_now_on_the_n4_board():
    s = make_solver({"X": {5, 6}, "Y": {1, 2}})
    res = evaluate_endgame(s, Clue(), 2, 2, frozenset())
    assert res["complete"] is True
    assert res["n_public"] == 4 and res["n_mine"] == 4
    assert res["decision"] == "guess_now"
    assert res["p_win"] == pytest.approx(res["guess_now"]["p_win"])
    assert res["guess_now"]["p_win"] >= res["best_question"]["p_win"]
    assert len(res["guess_now"]["code"]) == 7  # "123 456"


def test_best_question_branches_are_consistent():
    s = make_solver({"X": {5, 6}, "Y": {1, 2, 3}})
    res = evaluate_endgame(s, Clue(), 2, 2, frozenset())
    best = res["best_question"]
    assert best["label"] == res["ranked_questions"][0]["label"]
    assert sum(b["prob"] for b in best["branches"]) == pytest.approx(1.0)
    assert sum(b["n"] for b in best["branches"]) == res["n_mine"]
    assert sum(b["prob"] * b["value"] for b in best["branches"]) == pytest.approx(best["p_win"])
    for b in best["branches"]:
        assert (b["code"] is not None) == (b["action"] == "guess")
    p_wins = [q["p_win"] for q in res["ranked_questions"]]
    assert p_wins == sorted(p_wins, reverse=True)


def test_my_failed_guess_is_removed_from_my_pool_only():
    s = make_solver({"X": {5, 6}, "Y": {1, 2, 3}})
    candidates, _ = build_universe(s, Clue())
    res = evaluate_endgame(s, Clue(), 1, 2, frozenset({candidates[0]}))
    assert res["n_public"] == 6
    assert res["n_mine"] == 5
    assert res["guess_now"]["code"] != code_to_string(candidates[0])


def test_no_attempts_left_gives_decision_none():
    s = make_solver({"X": {5, 6}, "Y": {1, 2}})
    candidates, _ = build_universe(s, Clue())
    res = evaluate_endgame(s, Clue(), 0, 1, frozenset(candidates[:2]))
    assert res["decision"] == "none"
    assert res["p_win"] == 0.0
    assert res["guess_now"] is None


def test_evaluate_endgame_returns_none_above_n_max():
    s = make_solver({"X": {5, 6}, "Y": {1, 2, 3}})
    assert evaluate_endgame(s, Clue(), 2, 2, frozenset(), n_max=5) is None


def test_evaluate_endgame_reports_incomplete_on_budget_overrun():
    s = make_solver({"X": {5, 6}, "Y": {1, 2, 3}})
    res = evaluate_endgame(s, Clue(), 2, 2, frozenset(), time_budget_s=-1.0)
    assert res == {"complete": False, "n_public": 6}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_endgame.py -v`
Expected: ImportError for `evaluate_endgame`.

- [ ] **Step 3: Write the implementation**

Add this method to `EndgameSolver` (after `_opp_value`):

```python
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
```

Append this function at module level:

```python
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
```

Note: when `a_me == 0`, `my_excluded` can hold 2 codes. `analyze` returns early in that case, so passing only the first one as `e` is harmless. `n_mine` still subtracts both.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_endgame.py -v`
Expected: all PASS. The live legacy test takes about 5 s because of the old engine at N=6.

If a legacy comparison fails, **do not tweak the expected values**. The prototype matched the old engine on all four boards, so a mismatch means `value`/`analyze` deviates from the model recap in Task 2. Re-check the terminals, the branch weights (`|c ∩ mine| / |mine|`), and that the root always offers the direct guess.

- [ ] **Step 5: Commit**

```bash
git add endgame.py tests/test_endgame.py
git commit -m "feat(endgame): root analysis and display-ready evaluate_endgame

Legacy mode (all extensions off) reproduces strategy.py's exact p_win on
the reference boards.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: GameState integration (`opp_fail_pool_size`, `build_endgame_from`)

**Files:**
- Modify: `game_state.py` (imports at the top; `GameState.__init__`, `reset`, `guess_failed`; new static method after `build_payload_from`)
- Test: `tests/test_game_state.py` (append)

**Interfaces:**
- Consumes: Task 1's `OPP_FAIL_COUNT_CAP` and Task 3's `evaluate_endgame`.
- Produces:
  - `GameState.opp_fail_pool_size: int` (0 = the opponent has not failed yet; otherwise the public solution count at its first failure, capped at `OPP_FAIL_COUNT_CAP`)
  - `GameState.build_endgame_from(clue, a_me, a_opp, excluded, opp_fail_pool_size, should_cancel=lambda: False) -> Optional[dict]` (static; same dict as `evaluate_endgame`; may raise `ValueError` on a contradictory clue, like `build_payload_from`)
  - `GameState.endgame() -> Optional[dict]` (convenience wrapper over the current state)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_game_state.py`:

```python
def _n4_state():
    # Same N=4 fixture as tests/test_native_solutions_panel.py.
    gs = GameState()
    for row, val in (("K", 6), ("S", 1)):
        gs.apply_clue("row_total", row=row, value=val)
    for col, val in (("H", 3), ("C", 3), ("E", 1)):
        gs.apply_clue("col_total", col=col, value=val)
    for pos, par in (("T", "Pair"), ("W", "Pair"), ("Y", "Pair"), ("X", "Impair")):
        gs.apply_clue("parity", pos=pos, value=par)
    return gs


def test_opponent_first_failure_records_the_public_pool_size():
    gs = _n4_state()
    assert gs.opp_fail_pool_size == 0
    gs.guess_failed({"who": "opponent"})
    assert gs.opp_fail_pool_size == 4
    assert gs.a_opp == 1


def test_opponent_second_failure_keeps_the_first_pool_size():
    gs = _n4_state()
    gs.guess_failed({"who": "opponent"})
    gs.guess_failed({"who": "opponent"})
    assert gs.opp_fail_pool_size == 4
    assert gs.a_opp == 0


def test_opponent_failure_on_a_wide_board_is_capped():
    gs = GameState()
    gs.guess_failed({"who": "opponent"})
    assert gs.opp_fail_pool_size == 1000


def test_reset_clears_the_opponent_failure_pool_size():
    gs = _n4_state()
    gs.guess_failed({"who": "opponent"})
    gs.reset()
    assert gs.opp_fail_pool_size == 0


def test_endgame_on_a_small_board_returns_a_recommendation():
    gs = _n4_state()
    res = gs.endgame()
    assert res["complete"] is True
    assert res["n_public"] == 4
    assert res["decision"] in ("guess_now", "question")


def test_endgame_on_a_wide_board_returns_none():
    assert GameState().endgame() is None


def test_endgame_passes_the_opponent_failure_to_the_engine(monkeypatch):
    gs = _n4_state()
    gs.guess_failed({"who": "opponent"})
    seen = {}
    real = game_state_module.evaluate_endgame

    def spy(solver, clue, a_me, a_opp, excluded, opp_fail_pool_size=0, **kw):
        seen["args"] = (a_me, a_opp, opp_fail_pool_size)
        return real(solver, clue, a_me, a_opp, excluded, opp_fail_pool_size, **kw)

    monkeypatch.setattr(game_state_module, "evaluate_endgame", spy)
    gs.endgame()
    assert seen["args"] == (2, 1, 4)
```

`tests/test_game_state.py` already imports `GameState` and `import digitcode.game_state as game_state_module` at the top.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_game_state.py -v -k "opponent or endgame"`
Expected: FAIL with `AttributeError: 'GameState' object has no attribute 'opp_fail_pool_size'` (and similar for `endgame`).

- [ ] **Step 3: Write the implementation**

In `game_state.py`, add this import next to `from .strategy import evaluate_race_strategy`:

```python
from .endgame import OPP_FAIL_COUNT_CAP, evaluate_endgame
```

In `GameState.__init__`, after `self.my_excluded: frozenset = frozenset()`:

```python
        # Public solution count when the opponent failed its FIRST guess (0 =
        # no failure yet). The endgame engine needs it to estimate the
        # opponent's odds on its next guess (its failed code may still be in
        # the pool) -- see endgame.opp_hit_probability. Only the first failure
        # matters: a second one leaves it at 0 attempts, a terminal state.
        self.opp_fail_pool_size = 0
```

In `reset`, after `self.my_excluded = frozenset()`:

```python
        self.opp_fail_pool_size = 0
```

In `guess_failed`, replace the opponent branch:

```python
        if who == "opponent":
            if self.a_opp > 0:
                self.a_opp -= 1
```

with:

```python
        if who == "opponent":
            if self.a_opp == 2:
                solver = DigitcodeSolver()
                solver.propagate(self.clue)
                self.opp_fail_pool_size = solver.count_solutions_capped(self.clue, cap=OPP_FAIL_COUNT_CAP)
            if self.a_opp > 0:
                self.a_opp -= 1
```

Add after `build_payload_from` (a static method, same style):

```python
    @staticmethod
    def build_endgame_from(
        clue: Clue, a_me: int, a_opp: int, excluded: frozenset, opp_fail_pool_size: int,
        should_cancel: Callable[[], bool] = lambda: False,
    ) -> dict | None:
        """Exact endgame recommendation (see endgame.evaluate_endgame), or
        None when the board still has more than endgame.ENDGAME_N_MAX
        public solutions. Deliberately separate from build_payload_from: it
        may take seconds (budget: endgame.ENDGAME_TIME_BUDGET_S), so the
        native app runs it on its own worker after the fast payload is
        already on screen."""
        solver = DigitcodeSolver()
        solver.propagate(clue)  # may raise ValueError; callers must catch it
        return evaluate_endgame(
            solver, clue, a_me, a_opp, excluded, opp_fail_pool_size, should_cancel=should_cancel,
        )

    def endgame(self) -> dict | None:
        return self.build_endgame_from(
            self.clue, self.a_me, self.a_opp, self.my_excluded, self.opp_fail_pool_size,
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_game_state.py tests/test_web.py -v`
Expected: all PASS. The web tests guard the `guess_failed` change.

- [ ] **Step 5: Commit**

```bash
git add game_state.py tests/test_game_state.py
git commit -m "feat(game_state): track opponent failure pool size, expose endgame

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: "Fin de partie" block in the Solutions panel

**Files:**
- Create: `native/panels/endgame_format.py`
- Modify: `native/panels/solutions_panel.py` (new label after `guess_now_label`; two new methods)
- Test: `tests/test_native_endgame_format.py` (create), `tests/test_native_solutions_panel.py` (append)

**Interfaces:**
- Consumes: the `evaluate_endgame` result dict (Task 3 shape).
- Produces:
  - `endgame_format.ENDGAME_PENDING_TEXT: str`
  - `endgame_format.format_endgame(result: dict) -> str`
  - `SolutionsPanel.show_endgame_text(text: str) -> None` (shows the label with that text)
  - `SolutionsPanel.hide_endgame() -> None`
  - `SolutionsPanel.endgame_label: QLabel` (hidden by default)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_native_endgame_format.py`:

```python
from digitcode.native.panels.endgame_format import ENDGAME_PENDING_TEXT, format_endgame


def _question_result():
    return {
        "complete": True, "n_public": 5, "n_mine": 5, "p_win": 0.53,
        "decision": "question",
        "guess_now": {"code": "123 456", "p_win": 0.40},
        "best_question": {
            "qtype": "seg", "label": "X.e on/off ?", "p_win": 0.53,
            "branches": [
                {"answer": "on", "n": 2, "prob": 0.4, "action": "guess", "code": "123 456", "value": 0.5},
                {"answer": "off", "n": 3, "prob": 0.6, "action": "wait", "code": None, "value": 5 / 9},
            ],
        },
        "ranked_questions": [{"qtype": "seg", "label": "X.e on/off ?", "p_win": 0.53}],
    }


def test_question_decision_shows_the_question_the_alternative_and_each_branch():
    text = format_endgame(_question_result())
    assert "Fin de partie" in text and "53%" in text
    assert "Poser : X.e on/off ?" in text
    assert "proposer 123 456 tout de suite : 40%" in text
    assert "on (2 sol., 40%) → proposer 123 456 (50%)" in text
    assert "off (3 sol., 60%) → attendre (56%)" in text


def test_guess_now_decision_shows_the_code_and_the_best_question_as_alternative():
    res = _question_result()
    res["decision"] = "guess_now"
    res["p_win"] = 0.625
    res["guess_now"] = {"code": "654 321", "p_win": 0.625}
    text = format_endgame(res)
    assert "Proposer 654 321 maintenant" in text
    assert "meilleure question : X.e on/off ? : 53%" in text
    assert "→" not in text  # branches are only listed for a question decision


def test_none_decision():
    res = {"complete": True, "n_public": 3, "n_mine": 1, "p_win": 0.0, "decision": "none",
           "guess_now": None, "best_question": None, "ranked_questions": []}
    assert "Aucun coup possible" in format_endgame(res)


def test_incomplete_result():
    text = format_endgame({"complete": False, "n_public": 20})
    assert "calcul trop long" in text and "20" in text


def test_pending_text_mentions_the_endgame():
    assert "Fin de partie" in ENDGAME_PENDING_TEXT
```

Append to `tests/test_native_solutions_panel.py`:

```python
def test_endgame_label_is_hidden_by_default_and_toggles(qapp):
    gs = GameState()
    panel = SolutionsPanel(gs, run=lambda fn: fn())
    panel.show()
    assert not panel.endgame_label.isVisible()
    panel.show_endgame_text("Fin de partie — test")
    assert panel.endgame_label.isVisible()
    assert panel.endgame_label.text() == "Fin de partie — test"
    panel.hide_endgame()
    assert not panel.endgame_label.isVisible()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_native_endgame_format.py tests/test_native_solutions_panel.py -v`
Expected: ImportError for `endgame_format` and AttributeError for `endgame_label`.

- [ ] **Step 3: Write the implementation**

Create `native/panels/endgame_format.py`:

```python
from __future__ import annotations

ENDGAME_PENDING_TEXT = "Fin de partie : calcul exact en cours…"


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def format_endgame(result: dict) -> str:
    """Multi-line text for the "Fin de partie" block (see
    endgame.evaluate_endgame for the dict shape)."""
    if not result["complete"]:
        return (
            f"Fin de partie ({result['n_public']} solutions) : calcul trop long, "
            "suivez la recommandation ci-dessus."
        )
    lines = [f"Fin de partie — P(je gagne) = {_pct(result['p_win'])} (exact)"]
    decision = result["decision"]
    guess = result["guess_now"]
    best = result["best_question"]
    if decision == "guess_now":
        lines.append(f"➡️ Proposer {guess['code']} maintenant ({_pct(guess['p_win'])})")
        if best is not None:
            lines.append(f"   (meilleure question : {best['label']} : {_pct(best['p_win'])})")
    elif decision == "question":
        lines.append(f"➡️ Poser : {best['label']} ({_pct(best['p_win'])})")
        if guess is not None:
            lines.append(f"   (proposer {guess['code']} tout de suite : {_pct(guess['p_win'])})")
        for b in best["branches"]:
            action = f"proposer {b['code']}" if b["action"] == "guess" else "attendre"
            lines.append(
                f"   • {b['answer']} ({b['n']} sol., {_pct(b['prob'])}) → {action} ({_pct(b['value'])})"
            )
    else:
        lines.append("Aucun coup possible (plus d'essai).")
    return "\n".join(lines)
```

In `native/panels/solutions_panel.py`, right after `layout.addWidget(self.guess_now_label)`, add:

```python
        # "Fin de partie" block: filled asynchronously by MainWindow's
        # EndgameWorker once the board is small enough (see endgame.py).
        self.endgame_label = QLabel()
        self.endgame_label.setWordWrap(True)
        self.endgame_label.setStyleSheet(
            "background: #eef6ee; padding: 4px; border-radius: 4px;"
        )
        self.endgame_label.hide()
        layout.addWidget(self.endgame_label)
```

Add these methods to `SolutionsPanel` (after `_on_my_miss`):

```python
    def show_endgame_text(self, text: str) -> None:
        self.endgame_label.setText(text)
        self.endgame_label.show()

    def hide_endgame(self) -> None:
        self.endgame_label.hide()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_native_endgame_format.py tests/test_native_solutions_panel.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add native/panels/endgame_format.py native/panels/solutions_panel.py tests/test_native_endgame_format.py tests/test_native_solutions_panel.py
git commit -m "feat(native): Fin de partie block in the Solutions panel

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: EndgameWorker and MainWindow scheduling

**Files:**
- Create: `native/endgame_worker.py`
- Modify: `native/main_window.py`
- Test: `tests/test_native_endgame_worker.py` (create), `tests/test_native_main_window.py` (append)

**Interfaces:**
- Consumes: Task 4's `GameState.build_endgame_from` and `opp_fail_pool_size`, Task 5's `SolutionsPanel.show_endgame_text`, `hide_endgame`, `ENDGAME_PENDING_TEXT` and `format_endgame`, and Task 1's `ENDGAME_N_MAX`.
- Produces:
  - `EndgameWorker(clue, a_me, a_opp, excluded, opp_fail_pool_size, generation, parent=None)` with signals `finished_ok = Signal(object, int)` (the result dict or `None`) and `failed = Signal(str, int)`, and methods `cancel()` and `run()`.
  - `MainWindow.solutions_panel`, `._endgame_worker`, `._endgame_generation`, `._schedule_endgame(payload)`, `._cancel_endgame()`, `._on_endgame_finished(result, generation)`, `._on_endgame_failed(message, generation)`.

Behaviour:
- `_schedule_endgame(payload)` runs after every **full** render: in `_on_worker_finished` and in `_run`'s success branch. It never runs after `_render_quick`.
  - It first cancels any running endgame worker.
  - If `payload["n_solutions_total"] > ENDGAME_N_MAX`, it hides the block.
  - Otherwise it shows `ENDGAME_PENDING_TEXT` and starts a worker on `clone_clue(self.game_state.clue)` plus the current attempts, exclusions and `opp_fail_pool_size`.
- `_schedule_refresh` (a new clue is being entered) cancels the endgame worker and hides the block. The next full payload reschedules it.
- Results carry `_endgame_generation`. `_cancel_endgame` bumps it, so a late result from a cancelled worker is ignored. A `None` result hides the block. `failed` shows `"Fin de partie : erreur (<message>)"`.
- Superseded endgame workers go into the existing `self._retired_workers` list: same crash-avoidance reason as `SolveWorker`, see the comment in `__init__`. `closeEvent` also waits for the live endgame worker.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_native_endgame_worker.py`:

```python
from digitcode.game_state import GameState
from digitcode.native.endgame_worker import EndgameWorker

from tests.test_game_state import _n4_state


def _worker(gs, generation=1):
    return EndgameWorker(gs.clue, gs.a_me, gs.a_opp, gs.my_excluded, gs.opp_fail_pool_size, generation)


def test_run_emits_the_endgame_result(qapp):
    gs = _n4_state()
    worker = _worker(gs, generation=3)
    received = []
    worker.finished_ok.connect(lambda res, gen: received.append((res, gen)))
    worker.run()  # direct call: runs on the test thread, deterministic
    assert len(received) == 1
    res, gen = received[0]
    assert gen == 3
    assert res == gs.endgame()


def test_run_emits_none_on_a_wide_board(qapp):
    gs = GameState()
    worker = _worker(gs)
    received = []
    worker.finished_ok.connect(lambda res, gen: received.append(res))
    worker.run()
    assert received == [None]


def test_run_emits_nothing_when_cancelled_before_starting(qapp):
    gs = _n4_state()
    worker = _worker(gs)
    worker.cancel()
    ok, failed = [], []
    worker.finished_ok.connect(lambda res, gen: ok.append(res))
    worker.failed.connect(lambda msg, gen: failed.append(msg))
    worker.run()
    assert ok == [] and failed == []


def test_run_emits_failed_on_an_unexpected_exception(qapp, monkeypatch):
    gs = _n4_state()
    worker = _worker(gs, generation=9)

    def boom(*args, **kwargs):
        raise TypeError("boom")

    monkeypatch.setattr(GameState, "build_endgame_from", staticmethod(boom))
    failed = []
    worker.failed.connect(lambda msg, gen: failed.append((msg, gen)))
    worker.run()
    assert failed == [("boom", 9)]
```

Append to `tests/test_native_main_window.py`:

```python
from digitcode.native.panels.endgame_format import ENDGAME_PENDING_TEXT, format_endgame

from tests.test_game_state import _n4_state


def test_endgame_block_is_hidden_on_a_fresh_board(qapp):
    window = MainWindow()
    window.show()
    assert window._endgame_worker is None
    assert not window.solutions_panel.endgame_label.isVisible()


def test_small_board_schedules_the_endgame_and_renders_its_result(qapp):
    window = MainWindow(_n4_state())
    window.show()
    window.stack.setCurrentIndex(2)
    assert window._endgame_worker is not None
    assert window.solutions_panel.endgame_label.text() == ENDGAME_PENDING_TEXT

    window._endgame_worker.wait()
    QApplication.processEvents()  # deliver the cross-thread finished_ok signal

    expected = format_endgame(window.game_state.endgame())
    assert window.solutions_panel.endgame_label.text() == expected
    assert window.solutions_panel.endgame_label.isVisible()


def test_schedule_refresh_cancels_the_endgame_and_hides_the_block(qapp):
    window = MainWindow(_n4_state())
    window.show()
    endgame_worker = window._endgame_worker
    window._schedule_refresh()
    assert endgame_worker._cancel_event.is_set()
    assert not window.solutions_panel.endgame_label.isVisible()
    for worker in list(window._retired_workers) + [window._worker]:
        worker.wait()
    QApplication.processEvents()  # the refreshed payload reschedules an endgame search
    if window._endgame_worker is not None:
        window._endgame_worker.wait()
        QApplication.processEvents()


def test_on_endgame_finished_ignores_a_stale_generation(qapp):
    window = MainWindow()
    window._endgame_generation = 5
    window._on_endgame_finished({"complete": False, "n_public": 3}, generation=4)
    assert not window.solutions_panel.endgame_label.isVisible()


def test_on_endgame_failed_shows_the_error(qapp):
    window = MainWindow()
    window.show()
    window.stack.setCurrentIndex(2)
    window._on_endgame_failed("boom", generation=window._endgame_generation)
    assert "boom" in window.solutions_panel.endgame_label.text()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_native_endgame_worker.py tests/test_native_main_window.py -v`
Expected: ImportError for `endgame_worker`, and AttributeError for `_endgame_worker` / `solutions_panel`.

- [ ] **Step 3: Write the implementation**

Create `native/endgame_worker.py`:

```python
from __future__ import annotations

import sys
import threading
import traceback
from typing import FrozenSet

from PySide6.QtCore import QThread, Signal

from ..game_state import GameState
from ..solver import Cancelled, Clue


class EndgameWorker(QThread):
    """Runs `GameState.build_endgame_from(...)` (the exact endgame search,
    up to endgame.ENDGAME_TIME_BUDGET_S) on a background thread, after the
    fast payload is already on screen. Same cooperative-cancellation
    contract as SolveWorker: MainWindow cancels it and moves on without
    waiting as soon as the board changes."""

    finished_ok = Signal(object, int)  # result dict, or None above ENDGAME_N_MAX
    failed = Signal(str, int)

    def __init__(
        self, clue: Clue, a_me: int, a_opp: int, excluded: FrozenSet, opp_fail_pool_size: int,
        generation: int, parent=None,
    ) -> None:
        super().__init__(parent)
        self._clue = clue
        self._a_me = a_me
        self._a_opp = a_opp
        self._excluded = excluded
        self._opp_fail_pool_size = opp_fail_pool_size
        self.generation = generation
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        if self._cancel_event.is_set():
            return
        try:
            result = GameState.build_endgame_from(
                self._clue, self._a_me, self._a_opp, self._excluded, self._opp_fail_pool_size,
                should_cancel=self._cancel_event.is_set,
            )
        except Cancelled:
            return
        except Exception as e:
            traceback.print_exc(file=sys.stderr)
            self.failed.emit(str(e), self.generation)
            return
        self.finished_ok.emit(result, self.generation)
```

In `native/main_window.py`:

1. Imports: add
```python
from ..endgame import ENDGAME_N_MAX
from .endgame_worker import EndgameWorker
from .panels.endgame_format import ENDGAME_PENDING_TEXT, format_endgame
```
and add `QThread` to the `PySide6.QtCore` import (`from PySide6.QtCore import QEvent, QThread, Qt`).

2. In `__init__`, after `self._retired_workers: list[SolveWorker] = []`, change that annotation to `list[QThread]` and add:
```python
        # Exact endgame search (endgame.py), run on its own worker after each
        # full payload once the board is small enough. Its own generation
        # counter: bumped by _cancel_endgame, so a result from a superseded
        # search is ignored.
        self._endgame_worker: EndgameWorker | None = None
        self._endgame_generation = 0
```

3. Replace the `SolutionsPanel(self.game_state, self._run),` entry of `self.panels` with `self.solutions_panel,`. Just before the `self.panels: list[QWidget] = [` line, add:
```python
        self.solutions_panel = SolutionsPanel(self.game_state, self._run)
```

4. In `_run`, in the `else:` branch, after `self._render(payload)`, add `self._schedule_endgame(payload)`.

5. In `_schedule_refresh`, at the top of the method body (before `if self._worker is not None:`), add:
```python
        self._cancel_endgame()
        self.solutions_panel.hide_endgame()
```

6. In `_on_worker_finished`, after `self._render(payload)`, add `self._schedule_endgame(payload)`.

7. Add these methods after `_on_worker_failed`:
```python
    def _cancel_endgame(self) -> None:
        if self._endgame_worker is not None:
            self._endgame_worker.cancel()
            self._retired_workers.append(self._endgame_worker)
            self._endgame_worker = None
        self._endgame_generation += 1

    def _schedule_endgame(self, payload: dict) -> None:
        """Start the exact endgame search for the state `payload` was just
        rendered from -- only after a FULL render (never _render_quick),
        and only when the board is small enough to be worth it."""
        self._cancel_endgame()
        if payload["n_solutions_total"] > ENDGAME_N_MAX:
            self.solutions_panel.hide_endgame()
            return
        gs = self.game_state
        worker = EndgameWorker(
            clone_clue(gs.clue), gs.a_me, gs.a_opp, gs.my_excluded, gs.opp_fail_pool_size,
            self._endgame_generation,
        )
        worker.finished_ok.connect(self._on_endgame_finished)
        worker.failed.connect(self._on_endgame_failed)
        worker.finished.connect(lambda w=worker: self._cleanup_worker(w))
        self._endgame_worker = worker
        self.solutions_panel.show_endgame_text(ENDGAME_PENDING_TEXT)
        worker.start()

    def _on_endgame_finished(self, result, generation: int) -> None:
        if generation != self._endgame_generation:
            return
        if result is None:
            self.solutions_panel.hide_endgame()
        else:
            self.solutions_panel.show_endgame_text(format_endgame(result))

    def _on_endgame_failed(self, message: str, generation: int) -> None:
        if generation != self._endgame_generation:
            return
        self.solutions_panel.show_endgame_text(f"Fin de partie : erreur ({message})")
```

8. In `closeEvent`, after `if self._worker is not None: workers.append(self._worker)`, add:
```python
        if self._endgame_worker is not None:
            workers.append(self._endgame_worker)
```

Note: `_cleanup_worker` already removes the worker from `_retired_workers` if it is there and calls `deleteLater()`. That works for both worker types.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_native_endgame_worker.py tests/test_native_main_window.py tests/test_native_solutions_panel.py tests/test_native_integration.py -v`
Expected: all PASS, including the pre-existing main-window tests.

If a pre-existing native test now aborts with "QThread: Destroyed while thread is still running", it built a small board through `MainWindow` and exits while an endgame worker is still alive. Make that test wait on `window._endgame_worker` (when it is not `None`) before it ends, the same way the existing tests wait on `window._worker`. Do not remove the scheduling.

- [ ] **Step 5: Commit**

```bash
git add native/endgame_worker.py native/main_window.py tests/test_native_endgame_worker.py tests/test_native_main_window.py
git commit -m "feat(native): run the exact endgame search after each full payload

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Benchmark (performance and self-play gain), spec update, full suite

**Files:**
- Create: `tests/bench_endgame.py`. It is not collected by pytest because it has no `test_` prefix.
- Modify: `docs/superpowers/specs/2026-09-23-endgame-engine-design.md` (append an "Évolution — mesures" section and fix the formula)

**Interfaces:**
- Consumes: Task 1's `build_universe`, `code_consistent` and `ME`, and Task 3's `EndgameSolver` and `analyze`.

- [ ] **Step 1: Write the benchmark script**

Create `tests/bench_endgame.py`:

```python
"""Endgame engine benchmark (not a test -- run by hand).

    .venv/bin/python -m tests.bench_endgame perf
    .venv/bin/python -m tests.bench_endgame selfplay

perf: solve time vs N on boards reached by random real games.
selfplay: exact expected win rate of the new engine (all extensions on)
against the legacy model (strategy.py-equivalent), exhaustive over every
possible secret code and both seat orders, on random endgame boards.
"""
import random
import sys
import time

from digitcode.endgame import ME, EndgameSolver, build_universe, code_consistent
from digitcode.solver import Clue, DigitcodeSolver

NEW = dict(choose_guess=True, interior_direct_guess=True, track_opp_fail=True)
LEGACY = dict(choose_guess=False, interior_direct_guess=False, track_opp_fail=False)


def random_board(seed: int, target: int):
    """Play random questions against a random secret code until at most
    `target` solutions remain. Returns (solver, clue)."""
    rng = random.Random(seed)
    while True:
        code = tuple(rng.randint(0, 9) for _ in range(6))
        if code_consistent(code, Clue()):
            break
    clue = Clue()
    while True:
        s = DigitcodeSolver()
        s.propagate(clue)
        if s.count_solutions_exact(clue, cap=target + 1) <= target:
            return s, clue
        q = rng.choice(s.enumerate_all_questions(clue))
        for out in q["outcomes"]:
            child = s._apply_answer_to_clue(clue, q, out["answer"], 0)
            if code_consistent(code, child):
                clue = child
                break


def perf() -> None:
    for target in (6, 10, 14, 20):
        worst = 0.0
        for k in range(5):
            s, clue = random_board(1000 * target + k, target)
            t0 = time.monotonic()
            candidates, questions = build_universe(s, clue, n_max=40)
            t1 = time.monotonic()
            n = len(candidates)
            EndgameSolver(n, questions, **NEW).analyze((1 << n) - 1, -1, 2, 2, 0)
            t2 = time.monotonic()
            worst = max(worst, t2 - t0)
            print(f"target<={target:2d} N={n:2d} Q={len(questions):2d} universe {t1 - t0:.2f}s solve {t2 - t1:.2f}s", flush=True)
        print(f"  worst total for target<={target}: {worst:.2f}s", flush=True)


def play(questions, n: int, truth: int, agents, first: int):
    """One game; returns the winning seat, or None for a draw."""
    S = (1 << n) - 1
    e, a, m_fail = [-1, -1], [2, 2], [0, 0]
    mover = first
    for _ in range(100):
        i, j = mover, 1 - mover
        if a[i] == 0 and a[j] == 0:
            return None
        if a[i] == 0:
            return j
        if a[j] == 0:
            return i
        ei = e[i] if e[i] >= 0 and (S >> e[i]) & 1 else -1
        r = agents[i].analyze(S, ei, a[i], a[j], m_fail[j])

        def guess(g: int) -> bool:
            if g == truth:
                return True
            a[i] -= 1
            e[i] = g
            if a[i] == 1:
                m_fail[i] = S.bit_count()
            return False

        if r["decision"] == "guess_now":
            if guess(r["direct"]["g"]):
                return i
        elif r["decision"] == "question":
            best = r["questions"][0]
            q = questions[best["qi"]]
            ci = next(k for k, c in enumerate(q.classes) if (c >> truth) & 1)
            S &= q.classes[ci]
            b = next(b for b in best["branches"] if b["ci"] == ci)
            if b["action"] == "guess" and guess(b["g"]):
                return i
        mover = j
    return None


def selfplay() -> None:
    new_wins = games = 0.0
    sanity = sanity_games = 0.0
    for k in range(20):
        s, clue = random_board(77 + k, 12)
        candidates, questions = build_universe(s, clue, n_max=40)
        n = len(candidates)
        if n < 3:
            continue
        new, legacy = EndgameSolver(n, questions, **NEW), EndgameSolver(n, questions, **LEGACY)
        board_new = board_games = 0.0
        for truth in range(n):
            for first in (0, 1):
                w = play(questions, n, truth, [new, legacy], first)
                board_new += 0.5 if w is None else (1.0 if w == 0 else 0.0)
                board_games += 1
                w2 = play(questions, n, truth, [new, EndgameSolver(n, questions, **NEW)], first)
                sanity += 0.5 if w2 is None else (1.0 if w2 == 0 else 0.0)
                sanity_games += 1
        new_wins += board_new
        games += board_games
        print(f"board {k:2d} N={n:2d}: new vs legacy {board_new / board_games:.3f}", flush=True)
    print(f"OVERALL new vs legacy: {new_wins / games:.4f} over {int(games)} games")
    print(f"SANITY new vs new: {sanity / sanity_games:.4f} (expected 0.5)")


if __name__ == "__main__":
    {"perf": perf, "selfplay": selfplay}[sys.argv[1]]()
```

- [ ] **Step 2: Run the performance benchmark**

Run: `.venv/bin/python -m tests.bench_endgame perf`
Expected: the "worst total" for target ≤ 20 is well under 30 s (the prototype measured < 1.5 s).

If the worst total goes over 10 s, lower `ENDGAME_N_MAX` in `endgame.py` to the largest target whose worst total stays under 10 s, and adjust the comment above it.

- [ ] **Step 3: Run the self-play benchmark**

Run: `.venv/bin/python -m tests.bench_endgame selfplay`
Expected: `SANITY` is exactly 0.5000 (both seats swapped over every secret code with the same engine). `OVERALL new vs legacy` is > 0.5.

If SANITY ≠ 0.5, `play` has a bug. Fix it before reading OVERALL.

- [ ] **Step 4: Update the spec**

In `docs/superpowers/specs/2026-09-23-endgame-engine-design.md`:

(a) In the "Croyance sur l'essai raté adverse" section, replace the line

```
Sans échec adverse : 1/|S|. Vérification : m=4, |S|=2 → 2/3.
```

with

```
Valable pour |S| ≥ 2. Pour |S| = 1, le pool ne contient que la solution
(x ≠ t) : la réussite est certaine (1), le premier terme de la formule
étant alors un 0/0. Sans échec adverse : 1/|S|. Vérification : m=4,
|S|=2 → 2/3.
```

(b) In the "Contexte et objectif" section, point 2, replace the sentence starting `Règle intuitive : tenter le code que les questions adverses` (through `branche décisive de l'adversaire.`) with:

```
La règle intuitive « tenter le code que les questions adverses
isoleraient » ne tient pas en général : sur un pool à 4 avec les
questions {A,B}|{C,D} et {A}|{B,C,D}, les valeurs des tentatives sont
A → 0,50, B → 0,42, C et D → 0,58. Seul le calcul tranche.
```

(c) Append at the end of the file:

```markdown
## Évolution — mesures d'implémentation (2026-09-23)

- `ENDGAME_N_MAX` = <final value> ; perf (random real games, `tests/bench_endgame.py perf`) :
  <paste the four "worst total" lines>
- Self-play exhaustif (chaque code secret × les deux ordres de jeu, 20
  plateaux N ≤ 12) : nouveau moteur contre modèle legacy (≡ strategy.py
  exact) = <OVERALL value> ; contrôle nouveau contre nouveau = <SANITY value>.
- Le moteur legacy (toutes extensions coupées) reproduit exactement les
  `p_win` de `strategy.py` en mode exact sur les grilles de référence
  (tests/test_endgame.py).
- « Passer » reste non modélisé (question ouverte 1).
```

Fill in the `<...>` placeholders with the numbers printed in Steps 2–3.

- [ ] **Step 5: Run the full test suite**

Run: `.venv/bin/python -m pytest -q`
Expected: every test passes (195 pre-existing plus the new ones). It takes about 5 min.

- [ ] **Step 6: Commit**

```bash
git add tests/bench_endgame.py docs/superpowers/specs/2026-09-23-endgame-engine-design.md endgame.py
git commit -m "chore(endgame): benchmark script, measured results in the spec

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
