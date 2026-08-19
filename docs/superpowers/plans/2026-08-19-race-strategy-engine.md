# Race Strategy Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the zugzwang-based strategy heuristics in `cli.py` with an
exact recursive race-strategy engine (`strategy.py`) that accounts
for the new rule: each player may ask a question and/or attempt a solution
(budget of 2 attempts each) on their turn, first correct guess wins.

**Architecture:** A pure, memoized recursive value function computes
`P(I win)` under optimal alternating play, exact whenever the number of
remaining candidate solutions is small enough to be tractable (default
N ≤ 5, with a node-count safety budget as a second guard), falling back to
the existing single-pass EV heuristic (`ev_metrics_for_question`, already in
`solver.py`) otherwise. `solver.py` and `mapping.py` are not modified.
`cli.py` gains race-state tracking (attempts remaining, my failed guesses)
and a new `race` command that replaces `force`/`zug`.

**Tech Stack:** Python 3.12, stdlib only for the engine itself, `pytest` for
tests (dev-only dependency), packaged via `pyproject.toml` with an editable
install so `digitcode.*` imports work regardless of current directory.

**Spec:** `docs/superpowers/specs/2026-08-18-strategy-and-web-gui-design.md`

## Global Constraints

- Budget of 2 solution attempts per player, exact and symmetric (opponent's
  failed attempts are announced, so `a_opp` is exact — see spec).
- A failed attempt never gives partial feedback and never reveals the
  guessed code.
- Opponent's private exclusions are never modeled (conservative approximation
  — see spec's "hypothèse simplificatrice").
- Exact engine default thresholds: `n_exact_max=5`, `node_budget=20_000`
  (both configurable, validated empirically during brainstorming — worst
  case N=5 concentrated on one position takes ~6s, N=6+ reliably falls back).
- `mapping.py` and the existing public/private API of `solver.py` are not
  modified.

---

### Task 1: Project packaging and dev environment

**Files:**
- Create: `pyproject.toml`
- Modify: `.gitignore`
- Create: `tests/__init__.py` (empty, makes `tests` a package for consistent pytest rootdir behavior)

**Interfaces:**
- Produces: an editable install of the `digitcode` package (so `import digitcode.solver` works from any working directory) and a `.venv` with `pytest` available for every later task.

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "digitcode"
version = "0.1.0"
requires-python = ">=3.10"
dependencies = [
    "flask>=3.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[tool.setuptools]
packages = ["digitcode"]
package-dir = {"digitcode" = "."}

[tool.pytest.ini_options]
pythonpath = ["."]
```

**Why the `[tool.pytest.ini_options]` section matters:** `digitcode`'s own
`__init__.py` lives at the repo root (because `package-dir` maps `digitcode`
to `.`), and `tests/__init__.py` (Step 5 below) makes `tests` a package too.
With pytest's default import mode, having an `__init__.py` at the repo root
makes pytest walk one directory further up looking for the "real" package
root, which breaks plain `from tests.conftest import ...` imports (used
starting in Task 4) with `ModuleNotFoundError: No module named 'tests'` —
confirmed by hitting this exact failure during validation. Setting
`pythonpath = ["."]` sidesteps the whole heuristic by putting the repo root
on `sys.path` directly, regardless of `__init__.py` placement.

- [ ] **Step 2: Add venv and packaging artifacts to `.gitignore`**

Ensure `.gitignore` contains at least:

```
.superpowers/
__pycache__/
*.pyc
.venv/
*.egg-info/
```

- [ ] **Step 3: Create the venv and install editable + dev deps**

Run:
```bash
python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -e ".[dev]"
```

- [ ] **Step 4: Verify the install is cwd-independent**

Run: `cd /tmp && /home/cedric/Documents/digitcode/.venv/bin/python -c "from digitcode.solver import DigitcodeSolver; print('ok')"`
Expected: prints `ok` (no `ModuleNotFoundError`), proving the editable install resolves `digitcode` regardless of the caller's directory.

- [ ] **Step 5: Create `tests/__init__.py`**

Empty file (just makes `tests/` an importable package for pytest).

- [ ] **Step 6: Verify pytest runs (0 tests collected is expected at this point)**

Run: `.venv/bin/pytest tests/ -v`
Expected: `no tests ran` / `collected 0 items` — no import errors.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml .gitignore tests/__init__.py
git commit -m "chore: package digitcode as an editable install, add pytest dev dependency"
```

---

### Task 2: Clue signature and solver-state helpers

**Files:**
- Create: `strategy.py`
- Create: `tests/test_strategy.py`

**Interfaces:**
- Consumes: `digitcode.solver.DigitcodeSolver`, `digitcode.solver.Clue` (unmodified).
- Produces:
  - `Candidate = Tuple[int, int, int, int, int, int]`
  - `_clue_signature(clue: Clue) -> tuple`
  - `_solution_tuple(sol: Dict[str, int]) -> Candidate`
  - `_solver_for(base: DigitcodeSolver, clue: Clue) -> Optional[DigitcodeSolver]` (returns `None` on contradiction instead of raising)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_strategy.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_strategy.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'digitcode.strategy'` (module doesn't exist yet).

- [ ] **Step 3: Write the minimal implementation**

```python
# strategy.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_strategy.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add strategy.py tests/test_strategy.py
git commit -m "feat: add clue signature and solver-state helpers for the race strategy engine"
```

---

### Task 3: Guess-now evaluation helper

**Files:**
- Modify: `strategy.py`
- Modify: `tests/test_strategy.py`

**Interfaces:**
- Consumes: `_solution_tuple` (Task 2).
- Produces: `_best_guess_value(solver, clue, n_total, attempts, excluded, win_value, lose_recurse) -> Optional[float]`

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_strategy.py
from digitcode.strategy import _best_guess_value


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_strategy.py -v`
Expected: FAIL with `ImportError: cannot import name '_best_guess_value'`.

- [ ] **Step 3: Write the minimal implementation**

```python
# append to strategy.py
from typing import Callable, FrozenSet


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_strategy.py -v`
Expected: PASS (9 passed).

- [ ] **Step 5: Commit**

```bash
git add strategy.py tests/test_strategy.py
git commit -m "feat: add guess-now evaluation helper to the race strategy engine"
```

---

### Task 4: Exact recursive engine, heuristic fallback, and public API

**Files:**
- Modify: `strategy.py`
- Modify: `tests/test_strategy.py`
- Create: `tests/conftest.py`

**Interfaces:**
- Consumes: `_clue_signature`, `_solution_tuple`, `_solver_for` (Task 2), `_best_guess_value` (Task 3).
- Produces:
  ```python
  def evaluate_race_strategy(
      solver: DigitcodeSolver,
      clue: Clue,
      a_me: int,
      a_opp: int,
      my_excluded: FrozenSet[Candidate] = frozenset(),
      n_exact_max: int = 5,
      node_budget: int = 20_000,
  ) -> dict:
      """Returns {'p_win': float, 'exact': bool,
      'best_question': {'qtype': str, 'label': str} | None,
      'guess_now': bool,
      'ranked_alternatives': [{'qtype': str, 'label': str, 'p_win': float}, ...]}"""
  ```
  This is the function `cli.py` (Task 5) and the future web backend call.

- [ ] **Step 1: Add the test helper fixture**

```python
# tests/conftest.py
import random

from digitcode.solver import DigitcodeSolver, Clue


def make_solver(free_positions: dict, tries: int = 500) -> DigitcodeSolver:
    """Builds a DigitcodeSolver whose domains are exactly `free_positions`
    for the given keys (each mapped to a set of >=1 candidate values) and a
    single random fixed value for every other position among T,U,V,W,X,Y.
    Retries with a fixed seed until propagating the identity Clue leaves
    every domain unchanged, so the constructed state is guaranteed valid
    under the real adjacency/max-two rules rather than hand-derived."""
    keys = ["T", "U", "V", "W", "X", "Y"]
    rng = random.Random(0)
    for _ in range(tries):
        domains = {}
        for k in keys:
            if k in free_positions:
                domains[k] = set(free_positions[k])
            else:
                domains[k] = {rng.randint(0, 9)}
        s = DigitcodeSolver()
        s.domains = {k: set(v) for k, v in domains.items()}
        before = {k: set(v) for k, v in domains.items()}
        try:
            s.propagate(Clue())
        except ValueError:
            continue
        if s.domains == before:
            return s
    raise RuntimeError(f"could not build a valid state for {free_positions} in {tries} tries")
```

- [ ] **Step 2: Write the failing tests**

```python
# append to tests/test_strategy.py
from digitcode.strategy import evaluate_race_strategy
from tests.conftest import make_solver


def test_single_solution_is_a_certain_win():
    s = make_solver({})
    res = evaluate_race_strategy(s, Clue(), a_me=2, a_opp=2)
    assert res["exact"] is True
    assert res["p_win"] == 1.0
    assert res["guess_now"] is True


def test_no_attempts_left_means_i_can_never_win():
    s = make_solver({"Y": {7, 8}})
    res = evaluate_race_strategy(s, Clue(), a_me=0, a_opp=2)
    assert res["exact"] is True
    assert res["p_win"] == 0.0


def test_two_candidates_with_an_informative_question_is_a_certain_win():
    # With 2 attempts and an informative question available, I can always
    # ask it and then use my bonus guess on the resolved answer.
    s = make_solver({"Y": {7, 8}})
    res = evaluate_race_strategy(s, Clue(), a_me=2, a_opp=2)
    assert res["exact"] is True
    assert res["p_win"] == 1.0
    assert res["best_question"] is not None


def test_above_threshold_falls_back_to_heuristic():
    s = make_solver({"Y": {6, 7, 8, 9, 0, 1}})  # N=6 > default n_exact_max=5
    res = evaluate_race_strategy(s, Clue(), a_me=2, a_opp=2)
    assert res["exact"] is False
    assert 0.0 <= res["p_win"] <= 1.0
    assert res["best_question"] is not None


def test_node_budget_forces_fallback_even_under_threshold():
    s = make_solver({"X": {6, 7}, "Y": {8, 9}})  # N=4, normally exact
    res = evaluate_race_strategy(s, Clue(), a_me=2, a_opp=2, node_budget=1)
    assert res["exact"] is False


def test_ranked_alternatives_sorted_descending_by_p_win():
    s = make_solver({"X": {6, 7}, "Y": {8, 9}})
    res = evaluate_race_strategy(s, Clue(), a_me=2, a_opp=2)
    values = [res["best_question"]] + res["ranked_alternatives"]
    p_wins = [res["p_win"]] + [alt["p_win"] for alt in res["ranked_alternatives"]]
    assert p_wins == sorted(p_wins, reverse=True)


def test_fallback_stays_fast_on_a_nearly_empty_board():
    # Regression guard: an uncapped fallback measured ~28s here during
    # brainstorming (0.38s x 74 candidate questions on a fresh board).
    # fallback_cap must keep this well under interactive-use latency.
    import time

    s = DigitcodeSolver()
    s.propagate(Clue())  # full domains, N far above n_exact_max -> fallback path
    t0 = time.time()
    res = evaluate_race_strategy(s, Clue(), a_me=2, a_opp=2)
    elapsed = time.time() - t0
    assert res["exact"] is False
    assert elapsed < 5.0, f"fallback took {elapsed:.1f}s, expected well under 5s"


def test_fallback_p_win_and_alternatives_stay_within_zero_one_on_saturated_board():
    # Regression guard: the first "expected remaining candidates" attempt
    # let multiple branches independently saturate fallback_cap, producing
    # a weighted score above N (observed: 200% of N) once turned into a
    # [0,1]-ish p_win. Must never happen regardless of board size.
    s = DigitcodeSolver()
    s.propagate(Clue())
    res = evaluate_race_strategy(s, Clue(), a_me=2, a_opp=2)
    assert res["exact"] is False
    assert 0.0 <= res["p_win"] <= 1.0
    for alt in res["ranked_alternatives"]:
        assert 0.0 <= alt["p_win"] <= 1.0


def test_fallback_prefers_more_reachable_answers_when_saturated():
    # Regression guard: under the same saturation bug, a 7-outcome column
    # question could rank *below* a 2-outcome parity question (both hit the
    # cap identically, so the buggy score couldn't tell them apart in the
    # right direction). A column touches 2 positions (more reachable sums)
    # and must never rank below a single-position parity question here.
    s = DigitcodeSolver()
    s.propagate(Clue())
    res = evaluate_race_strategy(s, Clue(), a_me=2, a_opp=2)
    labels = [res["best_question"]["label"]] + [a["label"] for a in res["ranked_alternatives"]]
    first_col = min(i for i, l in enumerate(labels) if l.startswith("Combien en colonne"))
    first_parity = min(i for i, l in enumerate(labels) if "pair/impair" in l)
    assert first_col < first_parity
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_strategy.py -v`
Expected: FAIL with `ImportError: cannot import name 'evaluate_race_strategy'`.

- [ ] **Step 4: Write the minimal implementation**

```python
# append to strategy.py
from typing import List


class _BudgetExceeded(Exception):
    pass


def _exact_value(cur_clue, a_me_, a_opp_, excl_, mover, base_solver, memo, node_counter, node_budget):
    key = (_clue_signature(cur_clue), a_me_, a_opp_, excl_, mover)
    if key in memo:
        return memo[key]

    node_counter[0] += 1
    if node_counter[0] > node_budget:
        raise _BudgetExceeded()

    cur_solver = _solver_for(base_solver, cur_clue)
    if cur_solver is None:
        memo[key] = 0.0
        return 0.0

    n = cur_solver.count_solutions_exact(cur_clue, cap=None)
    if n == 0:
        memo[key] = 0.0
        return 0.0

    questions = [q for q in cur_solver.enumerate_all_questions(cur_clue) if len(q["outcomes"]) > 1]

    def recurse(clue_, a_me2, a_opp2, excl2, mover2, solver2):
        return _exact_value(clue_, a_me2, a_opp2, excl2, mover2, solver2, memo, node_counter, node_budget)

    if not questions:
        if mover == "me":
            gv = _best_guess_value(
                cur_solver, cur_clue, n, a_me_, excl_, 1.0,
                lambda ne: recurse(cur_clue, a_me_ - 1, a_opp_, ne, "opp", base_solver),
            )
            result = gv if gv is not None else 0.5
        else:
            gv = _best_guess_value(
                cur_solver, cur_clue, n, a_opp_, frozenset(), 0.0,
                lambda ne: recurse(cur_clue, a_me_, a_opp_ - 1, excl_, "me", base_solver),
            )
            result = gv if gv is not None else 0.5
        memo[key] = result
        return result

    best = None
    for q in questions:
        total = 0.0
        for out in q["outcomes"]:
            child_clue = cur_solver._apply_answer_to_clue(cur_clue, q, out["answer"], 0)
            child_solver = _solver_for(cur_solver, child_clue)
            if child_solver is None:
                continue
            n_ans = child_solver.count_solutions_exact(child_clue, cap=None)
            if n_ans == 0:
                continue
            p = n_ans / n
            if mover == "me":
                wait_val = recurse(child_clue, a_me_, a_opp_, excl_, "opp", cur_solver)
                gv = _best_guess_value(
                    child_solver, child_clue, n_ans, a_me_, excl_, 1.0,
                    lambda ne, cc=child_clue, cs=cur_solver: recurse(cc, a_me_ - 1, a_opp_, ne, "opp", cs),
                )
                outcome_val = max(wait_val, gv) if gv is not None else wait_val
            else:
                wait_val = recurse(child_clue, a_me_, a_opp_, excl_, "me", cur_solver)
                gv = _best_guess_value(
                    child_solver, child_clue, n_ans, a_opp_, frozenset(), 0.0,
                    lambda ne, cc=child_clue, cs=cur_solver: recurse(cc, a_me_, a_opp_ - 1, excl_, "me", cs),
                )
                outcome_val = min(wait_val, gv) if gv is not None else wait_val
            total += p * outcome_val
        label = q["label"]
        if best is None or (mover == "me" and total > best[0]) or (mover == "opp" and total < best[0]):
            best = (total, label)

    result = best[0] if best is not None else 0.5
    memo[key] = result
    return result


def _heuristic_fallback(solver: DigitcodeSolver, clue: Clue, questions: list, n_gate: int, a_me: int, fallback_cap: int) -> dict:
    """n_gate is the (possibly heavily capped, at n_exact_max+1) count used
    only for the guess_now check. It is NOT used for scoring: scoring needs
    its own count against fallback_cap (a much higher cap), computed below."""
    if not questions:
        return {
            "p_win": 0.5, "exact": False, "best_question": None,
            "guess_now": a_me > 0 and 0 < n_gate <= 2, "ranked_alternatives": [],
        }

    n = solver.count_solutions_exact(clue, cap=fallback_cap)
    saturated = n >= fallback_cap

    if saturated:
        # N is too large for per-branch counting to stay meaningful even
        # capped: if multiple branches independently saturate fallback_cap,
        # a weighted-sum score can exceed N and even invert the ranking
        # (measured: a 7-outcome question scored worse than a 2-outcome one
        # because both saturated identically). Fall back to the number of
        # distinct reachable answers -- already computed by
        # enumerate_all_questions, no extra DFS, immune to saturation.
        max_outcomes = max(len(q["outcomes"]) for q in questions)
        scored = [(1.0 - len(q["outcomes"]) / max_outcomes, q) for q in questions]
    else:
        # n is exact (not saturated): minimize the expected number of
        # remaining candidates after the answer -- Sum (n_r/n) * n_r.
        # Standard "maximize information gain" criterion; the uniform
        # distribution over consistent solutions (p = n_r/n) is already
        # assumed everywhere else in this module.
        scored = []
        for q in questions:
            expected_remaining = 0.0
            for out in q["outcomes"]:
                child_clue = solver._apply_answer_to_clue(clue, q, out["answer"], 0)
                child_solver = _solver_for(solver, child_clue)
                if child_solver is None:
                    continue
                n_r = child_solver.count_solutions_exact(child_clue, cap=fallback_cap)
                if n_r == 0:
                    continue
                expected_remaining += (n_r / n) * n_r
            scored.append((expected_remaining / n, q))

    scored.sort(key=lambda t: t[0])  # lower score = more reduction = better
    best_score, best_q = scored[0]
    return {
        # Not a calibrated win probability in this regime -- a bounded
        # reduction-quality proxy (1 - normalized score), consistent with
        # "exact": False signaling the estimate is approximate.
        "p_win": 1.0 - best_score,
        "exact": False,
        "best_question": {"qtype": best_q["qtype"], "label": best_q["label"]},
        "guess_now": a_me > 0 and 0 < n_gate <= 2,
        "ranked_alternatives": [
            {"qtype": q["qtype"], "label": q["label"], "p_win": 1.0 - s} for s, q in scored[1:]
        ],
    }


def evaluate_race_strategy(
    solver: DigitcodeSolver,
    clue: Clue,
    a_me: int,
    a_opp: int,
    my_excluded: "FrozenSet[Candidate]" = frozenset(),
    n_exact_max: int = 5,
    node_budget: int = 20_000,
    fallback_cap: int = 500,
) -> dict:
    n = solver.count_solutions_exact(clue, cap=n_exact_max + 1)
    questions = [q for q in solver.enumerate_all_questions(clue) if len(q["outcomes"]) > 1]

    if 0 < n <= n_exact_max:
        memo: Dict[tuple, float] = {}
        node_counter = [0]
        try:
            ranked = []
            for q in questions:
                total = 0.0
                for out in q["outcomes"]:
                    child_clue = solver._apply_answer_to_clue(clue, q, out["answer"], 0)
                    child_solver = _solver_for(solver, child_clue)
                    if child_solver is None:
                        continue
                    n_ans = child_solver.count_solutions_exact(child_clue, cap=None)
                    if n_ans == 0:
                        continue
                    p = n_ans / n
                    wait_val = _exact_value(child_clue, a_me, a_opp, my_excluded, "opp", solver, memo, node_counter, node_budget)
                    gv = _best_guess_value(
                        child_solver, child_clue, n_ans, a_me, my_excluded, 1.0,
                        lambda ne, cc=child_clue, cs=solver: _exact_value(cc, a_me - 1, a_opp, ne, "opp", cs, memo, node_counter, node_budget),
                    )
                    outcome_val = max(wait_val, gv) if gv is not None else wait_val
                    total += p * outcome_val
                ranked.append((total, q))
            ranked.sort(key=lambda t: -t[0])

            direct_guess = _best_guess_value(
                solver, clue, n, a_me, my_excluded, 1.0,
                lambda ne: _exact_value(clue, a_me - 1, a_opp, ne, "opp", solver, memo, node_counter, node_budget),
            )

            if not ranked:
                return {
                    "p_win": direct_guess if direct_guess is not None else 0.0,
                    "exact": True, "best_question": None,
                    "guess_now": direct_guess is not None, "ranked_alternatives": [],
                }

            best_val, best_q = ranked[0]
            guess_now = direct_guess is not None and direct_guess >= best_val
            return {
                "p_win": max(best_val, direct_guess) if direct_guess is not None else best_val,
                "exact": True,
                "best_question": {"qtype": best_q["qtype"], "label": best_q["label"]},
                "guess_now": guess_now,
                "ranked_alternatives": [
                    {"qtype": q["qtype"], "label": q["label"], "p_win": v} for v, q in ranked[1:]
                ],
            }
        except _BudgetExceeded:
            pass

    return _heuristic_fallback(solver, clue, questions, n, a_me, fallback_cap)
```

**Why the fallback has two regimes:** the first version scored every
question by `_ev_immediate_for_question` (credits only outcomes reaching
≤2 solutions). Measured on an empty board: **all 74 candidate questions
score exactly 0.0** — the metric only discriminates near the endgame, which
is not the regime the fallback serves. Switching to "expected remaining
candidates" fixes that, but only when `n = count_solutions_exact(clue,
cap=fallback_cap)` is not itself capped — when several branches
independently saturate `fallback_cap`, the weighted sum can exceed `n`
(measured: 200% of N) and even invert the ranking (a question with more
reachable answers scoring *worse* than one with fewer, because both hit the
cap equally). The `saturated` branch avoids this entirely by not counting
per-branch sizes at all, using outcome count instead — free (no DFS),
immune to the saturation bug. Do not merge the two branches into a single
formula without re-measuring on an empty board.

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_strategy.py -v`
Expected: PASS (18 passed). Note: `test_single_solution_is_a_certain_win` and the N=4/N=6 tests may take a few seconds — that's expected given the validated worst-case timings (see spec).

- [ ] **Step 6: Commit**

```bash
git add strategy.py tests/test_strategy.py tests/conftest.py
git commit -m "feat: implement exact recursive race-strategy engine with heuristic fallback"
```

---

### Task 5: CLI integration — replace zugzwang display with the race engine

**Files:**
- Modify: `cli.py`

**Interfaces:**
- Consumes: `evaluate_race_strategy` (Task 4).
- Produces: a `race` CLI command; removes the now-superseded `force`/`zug` commands.

- [ ] **Step 1: Add race-state tracking and a display helper**

In `cli.py`, add the import and a display function near `show_forcing`/`print_force_alert` (around line 112-134):

```python
from digitcode.strategy import evaluate_race_strategy
```

Add this function after `show_forcing`:

```python
def show_race(s: DigitcodeSolver, clue: Clue, a_me: int, a_opp: int, my_excluded: frozenset) -> None:
    res = evaluate_race_strategy(s, clue, a_me, a_opp, my_excluded)
    tag = "exact" if res["exact"] else "estimation (N trop grand)"
    print(f"🎲 Stratégie de course [{tag}] — essais: moi {a_me}/2, adversaire {a_opp}/2")
    print(f"   P(je gagne) = {_format_pct(res['p_win'])}")
    if res["guess_now"]:
        print("   -> PROPOSER UNE SOLUTION MAINTENANT.")
    if res["best_question"] is not None:
        print(f"   Meilleure question : {res['best_question']['label']}")
    for alt in res["ranked_alternatives"][:5]:
        print(f"     · {alt['label']} — P(gagner)={_format_pct(alt['p_win'])}")
```

- [ ] **Step 2: Add race-state variables to `main()`**

In `main()` (around line 267-270), change:

```python
def main():
    s = DigitcodeSolver()
    clue = Clue()
    history: List[Clue] = []
```

to:

```python
def main():
    s = DigitcodeSolver()
    clue = Clue()
    history: List[Clue] = []
    a_me = 2
    a_opp = 2
    my_excluded: frozenset = frozenset()
```

- [ ] **Step 3: Reset race state on `reset`**

Change the `reset` branch (around line 284-286):

```python
        if low == "reset":
            s = DigitcodeSolver(); clue = Clue(); history.clear()
            print("Réinitialisé."); continue
```

to:

```python
        if low == "reset":
            s = DigitcodeSolver(); clue = Clue(); history.clear()
            a_me, a_opp, my_excluded = 2, 2, frozenset()
            print("Réinitialisé."); continue
```

- [ ] **Step 4: Replace the `force`/`zug` command branch with `race`**

Replace the block (around line 321-337):

```python
        if low.startswith("force") or low == "zug":
            try:
                s = DigitcodeSolver(); s.propagate(clue); print_trace(s)
                only, top = None, 20
                strict = True
                parts = low.split()
                if len(parts) >= 2:
                    arg = parts[1]
                    if arg == "all": top = None
                    elif arg in ("rows","lignes"): only = {"row"}; top = None
                    elif arg in ("cols","colonnes"): only = {"col"}; top = None
                    elif arg == "loose": strict = False
                    elif arg.isdigit(): top = int(arg)
                show_forcing(s, clue, top=top, only_types=only, strict=strict)
            except Exception as e:
                print(f"Erreur: {e}")
            continue
```

with:

```python
        if low == "race":
            try:
                s = DigitcodeSolver(); s.propagate(clue); print_trace(s)
                show_race(s, clue, a_me, a_opp, my_excluded)
            except Exception as e:
                print(f"Erreur: {e}")
            continue

        if low == "opp-miss":
            if a_opp <= 0:
                print("L'adversaire n'a plus d'essai.")
            else:
                a_opp -= 1
                print(f"Échec adverse enregistré. Adversaire : {a_opp}/2 essai(s) restant(s).")
            continue

        if low == "my-miss":
            if a_me <= 0:
                print("Vous n'avez plus d'essai.")
            else:
                try:
                    s = DigitcodeSolver(); s.propagate(clue)
                    sols = s.enumerate_solutions(clue, limit=6)
                    if not sols:
                        print("Aucune solution candidate à exclure.")
                    else:
                        print("Quelle solution avez-vous tentée ?")
                        for i, sol in enumerate(sols):
                            print(f"  {i}: {s.solution_to_string(sol)}")
                        idx_raw = input("  index > ").strip()
                        if idx_raw.isdigit() and int(idx_raw) < len(sols):
                            tried = _sol_tuple(sols[int(idx_raw)])
                            my_excluded = my_excluded | {tried}
                            a_me -= 1
                            print(f"Échec enregistré pour {s.solution_to_string(sols[int(idx_raw)])}. Vous : {a_me}/2 essai(s) restant(s).")
                        else:
                            print("Index invalide, rien d'enregistré.")
                except Exception as e:
                    print(f"Erreur: {e}")
            continue
```

- [ ] **Step 5: Update `HELP` text**

In the `HELP` constant (around line 7-26), replace the line:

```
  force  -> zugzwang (pas de question safe pour l'adversaire) [force all/rows/cols/loose/20]
  zug    -> alias de force
```

with:

```
  race     -> stratégie de course exacte (P(gagner), meilleure question, deviner ou non)
  opp-miss -> enregistre un échec de proposition de l'adversaire
  my-miss  -> enregistre un de vos échecs de proposition (choix parmi les solutions affichées)
```

- [ ] **Step 6: Remove now-unused `force`/`zug` display helpers**

Delete the functions `show_forcing` and `print_force_alert` (they were only used by the removed branch and by `show`/`undo`, which are updated in the next step).

- [ ] **Step 7: Update all remaining callers of `print_force_alert`**

`print_force_alert(s, clue)` is called in three places, always immediately
after `print_risk_alert(s, clue)`: in the `undo` branch, in the `show`
branch, and in the normal-input branch at the end of the loop. In all
three, replace:

```python
                print_risk_alert(s, clue)
                print_force_alert(s, clue)
```

with:

```python
                print_risk_alert(s, clue)
                show_race(s, clue, a_me, a_opp, my_excluded)
```

Search for `print_force_alert(s, clue)` in the file to confirm all three
occurrences are replaced and none remain.

- [ ] **Step 8: Manual smoke test**

Run: `.venv/bin/python -m digitcode.cli` (from the repo's parent directory, i.e. `cd .. && .../digitcode/.venv/bin/python -m digitcode.cli`, matching the existing absolute-import convention)
Type: `T2, race` and confirm it prints a `P(je gagne)` line without crashing. Type `quit` to exit.

- [ ] **Step 9: Commit**

```bash
git add cli.py
git commit -m "feat: replace zugzwang CLI commands with the exact race-strategy engine"
```
