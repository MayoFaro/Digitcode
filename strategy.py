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
    attempt is available or if no candidates remain after exclusion."""
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
