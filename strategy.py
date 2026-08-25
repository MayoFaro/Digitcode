from __future__ import annotations

import time
from typing import Callable, Dict, FrozenSet, Optional, Tuple

from .solver import DigitcodeSolver, Clue

Candidate = Tuple[int, int, int, int, int, int]


def _clue_signature(clue: Clue) -> tuple:
    """Identifies a Clue by its posted constraints only.

    KNOWN LIMITATION: used as (part of) the memo key in `_exact_value`, this
    assumes constraint propagation is confluent -- that the same Clue always
    yields the same fixed point regardless of which solver state it was
    reached from. That is not reliably true: `solver.py`'s
    `apply_no_equal_adjacent` / `apply_max_two` only prune values out of
    domains with len() > 1, so a violation between two positions that were
    already pinned to singletons by independent constraints is never caught,
    and whether that happens depends on the order positions get fixed. See
    the note at the memo dict in `evaluate_race_strategy`.
    """
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
    # `excluded` is passed to enumerate_solutions itself (not just filtered
    # afterwards): callers may pass an `n_total` that already accounts for
    # exclusion (see evaluate_race_strategy), so `limit=n_total + 1` must be
    # applied to the already-excluded pool, not the raw one -- otherwise a
    # low limit could stop the DFS before reaching enough non-excluded
    # candidates to fill it.
    remaining = [
        _solution_tuple(s)
        for s in solver.enumerate_solutions(clue, limit=n_total + 1, excluded=excluded)
    ]
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


def _question_branches(
    solver: DigitcodeSolver, clue: Clue, q: dict, cap: Optional[int] = None,
    excluded: FrozenSet[Candidate] = frozenset(),
) -> list:
    """Reachable (child_clue, child_solver, n_solutions) branches of `q`.

    `excluded` (candidates I have already tried and failed on) is subtracted
    from every branch's count, so a candidate ruled out by a real failed
    guess stops being treated as a live possibility anywhere in the engine,
    not just in the immediate guess-now decision -- see the note in
    `evaluate_race_strategy`.

    Callers must normalize branch probabilities by `sum(n for _, _, n in ...)`
    and NOT by the parent's own count: the two are not guaranteed equal (see
    `_clue_signature`), and using the parent count yields weights that do not
    sum to 1."""
    branches = []
    for out in q["outcomes"]:
        child_clue = solver._apply_answer_to_clue(clue, q, out["answer"], 0)
        child_solver = _solver_for(solver, child_clue)
        if child_solver is None:
            continue
        n_ans = child_solver.count_solutions_exact(child_clue, cap=cap, excluded=excluded)
        if n_ans == 0:
            continue
        branches.append((child_clue, child_solver, n_ans))
    return branches


class _BudgetExceeded(Exception):
    pass


# How many of the fallback heuristic's top-ranked candidates get the extra
# lookahead pass below (see _apply_lookahead_penalty). Keeps the added cost
# bounded regardless of how many questions are available overall (measured
# ~0.5s for 5 candidates on a N=117 board with ~39 questions -- extending
# this to all questions would multiply the existing 1-ply pass's own cost
# by the same factor).
_LOOKAHEAD_BEAM_WIDTH = 4
# How much a branch that hands the opponent an easy follow-up should worsen
# a question's score, on the same [0, 1]-ish scale as the entropy score
# lower-is-better convention. Chosen to be able to swap the ranking of two
# otherwise-close candidates without overriding a clearly better one.
_LOOKAHEAD_DANGER_PENALTY = 0.4


def _exact_value(cur_clue, a_me_, a_opp_, excl_, mover, base_solver, memo, node_counter, node_budget, deadline):
    # NOTE: the key deliberately omits `base_solver` -- see the limitation
    # documented on `_clue_signature` and at the memo dict in
    # `evaluate_race_strategy`.
    key = (_clue_signature(cur_clue), a_me_, a_opp_, excl_, mover)
    if key in memo:
        return memo[key]

    # Once a player has exhausted both attempts, the other side can keep
    # asking questions for free (no attempt spent) until the board is fully
    # determined and declare with certainty -- confirmed rule, not an
    # estimate. This must hold immediately regardless of the current board
    # size or whose turn it nominally is: leaving it to the recursion below
    # to "find its way" to this conclusion only works when the search is
    # exhaustive, and stops working once search is beam-limited (some
    # branches pruned away, including possibly the ones that reach this
    # conclusion). Both attempts exhausted simultaneously is a separate,
    # pre-existing degenerate case (nobody can ever declare) and is left
    # alone below.
    if a_me_ == 0 and a_opp_ > 0:
        memo[key] = 0.0
        return 0.0
    if a_opp_ == 0 and a_me_ > 0:
        memo[key] = 1.0
        return 1.0

    node_counter[0] += 1
    # Two independent termination conditions: node count bounds the search
    # size, the deadline bounds wall-clock latency (a single node can cost an
    # uncapped DFS count plus a full question enumeration, so 20k nodes is
    # far more than a few seconds near the endgame). Both raise the same
    # exception so `evaluate_race_strategy` falls back identically.
    if node_counter[0] > node_budget or time.monotonic() > deadline:
        raise _BudgetExceeded()

    cur_solver = _solver_for(base_solver, cur_clue)
    if cur_solver is None:
        memo[key] = 0.0
        return 0.0

    # `excl_` (candidates I've already tried and failed on) is a fact about
    # the board itself, not about whose turn it is -- it must reduce `n`
    # here regardless of `mover`. It is NOT applied to the opponent's own
    # guess-now simulation below (that always uses a fresh frozenset()),
    # which models a separate concern: the opponent guessing a different,
    # untracked puzzle.
    n = cur_solver.count_solutions_exact(cur_clue, cap=None, excluded=excl_)
    if n == 0:
        memo[key] = 0.0
        return 0.0

    questions = [q for q in cur_solver.enumerate_all_questions(cur_clue) if len(q["outcomes"]) > 1]

    def recurse(clue_, a_me2, a_opp2, excl2, mover2, solver2):
        return _exact_value(clue_, a_me2, a_opp2, excl2, mover2, solver2, memo, node_counter, node_budget, deadline)

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
        # Weights are normalized by this question's OWN branch-count sum, not
        # by the parent's `n`. Sum(n_ans) != n in general: solver.py's
        # singleton-guard gap makes counts depend on the order positions get
        # fixed, which differs between parent and child enumerations (measured:
        # a parent counting 4 with branches counting 1+4+1=6). Dividing by `n`
        # produced probability weights summing above 1 and p_win > 1.
        branches = _question_branches(cur_solver, cur_clue, q, excluded=excl_)
        sum_n_ans = sum(b[2] for b in branches)
        if sum_n_ans == 0:
            continue
        total = 0.0
        for child_clue, child_solver, n_ans in branches:
            p = n_ans / sum_n_ans
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
        if best is None or (mover == "me" and total > best) or (mover == "opp" and total < best):
            best = total

    result = best if best is not None else 0.5
    memo[key] = result
    return result


def _opponent_has_no_safe_question(child_solver: DigitcodeSolver, child_clue: Clue) -> bool:
    """True if, from this branch, the opponent (whose turn is always next)
    has NO safe question available: every question they could ask risks an
    outcome that leaves a small, exactly-known number of candidates. A
    single question with a risky-looking outcome among several safe ones
    doesn't count -- a rational opponent just avoids that one question, so
    only "every option is risky" is a genuine trap (same "no safe move"
    concept as the pre-existing, unused `evaluate_forcing_questions` in
    solver.py, adapted to reuse data already computed here instead of its
    own separate exhaustive check).

    A question with NO outcome below the exact-vs-capped boundary is
    "safe": reuses `enumerate_all_questions`'s own per-outcome `n` field,
    already computed there via a `limit=3` capped DFS, so this costs
    nothing beyond the `enumerate_all_questions` call itself (measured
    ~30ms even on a fully empty board). That cap makes `n` exact for 0, 1,
    or 2 and ambiguous at exactly 3 (could be higher) -- treating n=3 as
    safe is the conservative direction (under-flagging risk, never
    inventing risk that isn't confirmed)."""
    questions = child_solver.enumerate_all_questions(child_clue)
    if not questions:
        return True  # board already fully determined -- trivially no "move" needed
    for q in questions:
        if all(out["n"] >= 3 for out in q["outcomes"]):
            return False  # this question is safe -- the opponent has an out
    return True


def _apply_lookahead_penalty(
    solver: DigitcodeSolver, clue: Clue, scored: list, fallback_cap: int, my_excluded: FrozenSet[Candidate],
) -> list:
    """Adjusts the top `_LOOKAHEAD_BEAM_WIDTH` non-saturated candidates by
    how often their branches hand the opponent (who always moves next) an
    easy follow-up -- the 1-ply entropy score alone only looks at how much
    *I* learn, not what I leave the opponent able to do with it. A
    genuinely bounded approximation of "does this look like a trap or a
    gift", deliberately not full alternating-turn search: extending
    `_exact_value`'s own exact recursion to this N range was tried and
    measured to blow the time budget outright even at N=8-16, because N
    does not collapse to a terminal state quickly enough for width- or
    depth-limiting the search tree alone to bound it -- this stays bounded
    instead by never recursing past one extra ply and using only the
    already-capped `n` field `enumerate_all_questions` computes anyway.

    Takes and returns (score, q, risky) triples: `risky` (always False on
    input) is set True for a beam entry with any weight on a branch that
    hands the opponent a forced position, so callers can surface *why* a
    question dropped in the ranking, not just that it did -- entries past
    the beam keep `risky=False` (not evaluated, not a claim of safety)."""
    beam = scored[:_LOOKAHEAD_BEAM_WIDTH]
    rest = scored[_LOOKAHEAD_BEAM_WIDTH:]
    adjusted = []
    for score, q, _ in beam:
        branches = _question_branches(solver, clue, q, cap=fallback_cap, excluded=my_excluded)
        sum_n_r = sum(b[2] for b in branches)
        if sum_n_r == 0:
            adjusted.append((score, q, False))
            continue
        danger_mass = sum(
            n_r for child_clue, child_solver, n_r in branches
            if _opponent_has_no_safe_question(child_solver, child_clue)
        )
        danger_fraction = danger_mass / sum_n_r
        adjusted.append((score + _LOOKAHEAD_DANGER_PENALTY * danger_fraction, q, danger_fraction > 0))
    return sorted(adjusted, key=lambda t: t[0]) + rest


def _heuristic_fallback(
    solver: DigitcodeSolver, clue: Clue, questions: list, n_gate: int, a_me: int, fallback_cap: int,
    my_excluded: FrozenSet[Candidate] = frozenset(),
) -> dict:
    """n_gate is the (possibly heavily capped, at n_exact_max+1) count used
    only for the guess_now check. It is NOT used for scoring: scoring needs
    its own count against fallback_cap (a much higher cap), computed below.

    `my_excluded` (candidates already tried and failed) is subtracted from
    both, so a ruled-out candidate doesn't inflate the score against."""
    def _no_info() -> dict:
        return {
            "p_win": 0.5, "exact": False, "best_question": None,
            "guess_now": a_me > 0 and 0 < n_gate <= 2, "ranked_alternatives": [],
        }

    if not questions:
        return _no_info()

    n = solver.count_solutions_exact(clue, cap=fallback_cap, excluded=my_excluded)
    if n == 0:
        # Degenerate (contradictory) board: nothing to score against.
        # Defensive -- `_exact_value` and the exact-path gate already treat
        # n == 0 as a real case, and the scoring below has no meaning here.
        return _no_info()
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
        scored = [(1.0 - len(q["outcomes"]) / max_outcomes, q, False) for q in questions]
    else:
        # n is exact (not saturated): minimize the expected *fraction* of
        # candidates surviving the answer -- Sum p_r^2 with p_r = n_r/sum_n_r.
        # Standard "maximize information gain" criterion.
        #
        # sum_n_r is this question's own branch-count sum, NOT the parent's
        # `n`: the two are not guaranteed equal (see `_clue_signature`), and
        # using `n` as the denominator produced scores far above 1 and hence
        # negative p_win (measured: score -20.28). Normalizing per question
        # makes each p_r a real probability, so the score -- a weighted
        # average of terms <= 1 -- is always in [0, 1] and so is 1 - score.
        scored = []
        for q in questions:
            branches = _question_branches(solver, clue, q, cap=fallback_cap, excluded=my_excluded)
            sum_n_r = sum(b[2] for b in branches)
            if sum_n_r == 0:
                scored.append((1.0, q, False))  # no reachable branch -> no reduction
                continue
            score = sum((n_r / sum_n_r) ** 2 for _, _, n_r in branches)
            scored.append((score, q, False))

    scored.sort(key=lambda t: t[0])  # lower score = more reduction = better
    if not saturated:
        # Only meaningful (and only affordable) once branch counts are exact
        # -- see _apply_lookahead_penalty. Re-sorts its own beam internally.
        scored = _apply_lookahead_penalty(solver, clue, scored, fallback_cap, my_excluded)
    best_score, best_q, best_risky = scored[0]
    return {
        # Not a calibrated win probability in this regime -- a bounded
        # reduction-quality proxy (1 - normalized score), consistent with
        # "exact": False signaling the estimate is approximate.
        "p_win": 1.0 - best_score,
        "exact": False,
        # near_finish is deliberately always False here: computing it would
        # need the same per-branch exact counts the "exact" regime already
        # has for free, but the fallback regime is exactly where those counts
        # are unreliable/expensive (see the saturation note above) -- and a
        # "near finish" signal is rarely meaningful this far from the endgame
        # anyway. lookahead_risk (see _apply_lookahead_penalty) IS computed
        # here, for the top few candidates only -- unevaluated candidates
        # report False (not a claim of safety, just "not checked").
        "best_question": {
            "qtype": best_q["qtype"], "label": best_q["label"], "near_finish": False, "lookahead_risk": best_risky,
        },
        "guess_now": a_me > 0 and 0 < n_gate <= 2,
        "ranked_alternatives": [
            {"qtype": q["qtype"], "label": q["label"], "p_win": 1.0 - s, "near_finish": False, "lookahead_risk": r}
            for s, q, r in scored[1:]
        ],
    }


def evaluate_race_strategy(
    solver: DigitcodeSolver,
    clue: Clue,
    a_me: int,
    a_opp: int,
    my_excluded: FrozenSet[Candidate] = frozenset(),
    n_exact_max: int = 5,
    node_budget: int = 20_000,
    fallback_cap: int = 500,
    time_budget_s: float = 3.0,
    near_finish_threshold: int = 3,
) -> dict:
    # Candidates I've already tried and failed on are gone regardless of
    # regime: subtracting them here keeps the exact/fallback gate, and every
    # count derived from `n` below, consistent with what's actually still
    # possible.
    n = solver.count_solutions_exact(clue, cap=n_exact_max + 1, excluded=my_excluded)
    questions = [q for q in solver.enumerate_all_questions(clue) if len(q["outcomes"]) > 1]

    if 0 < n <= n_exact_max:
        # KNOWN LIMITATION: the memo key omits `base_solver`, although
        # `_exact_value`'s result depends on it through `_solver_for`. That is
        # only sound if propagation is confluent, which solver.py's
        # singleton-guard gap can violate (see `_clue_signature`). Fixing it
        # properly would mean either touching solver.py or keying the memo on
        # more state; neither is done here. The memo being per-call (a fresh
        # dict every invocation) bounds the practical impact to a single
        # evaluation. Documented, not fixed.
        memo: Dict[tuple, float] = {}
        node_counter = [0]
        deadline = time.monotonic() + time_budget_s
        try:
            ranked = []
            for q in questions:
                # Normalized by this question's own branch-count sum, not by
                # `n` -- see `_question_branches` and `_clue_signature`.
                branches = _question_branches(solver, clue, q, excluded=my_excluded)
                sum_n_ans = sum(b[2] for b in branches)
                if sum_n_ans == 0:
                    continue
                # A question is "near finish" if at least one reachable answer
                # would bring the solution count down to the threshold or
                # below -- an "opportunity" reading (matches the project's
                # existing "opportunités pouvant tomber à ≤N" vocabulary),
                # not a "every answer closes the game" guarantee.
                near_finish = any(n_ans <= near_finish_threshold for _, _, n_ans in branches)
                total = 0.0
                for child_clue, child_solver, n_ans in branches:
                    p = n_ans / sum_n_ans
                    wait_val = _exact_value(child_clue, a_me, a_opp, my_excluded, "opp", solver, memo, node_counter, node_budget, deadline)
                    gv = _best_guess_value(
                        child_solver, child_clue, n_ans, a_me, my_excluded, 1.0,
                        lambda ne, cc=child_clue, cs=solver: _exact_value(cc, a_me - 1, a_opp, ne, "opp", cs, memo, node_counter, node_budget, deadline),
                    )
                    outcome_val = max(wait_val, gv) if gv is not None else wait_val
                    total += p * outcome_val
                ranked.append((total, q, near_finish))
            ranked.sort(key=lambda t: -t[0])

            direct_guess = _best_guess_value(
                solver, clue, n, a_me, my_excluded, 1.0,
                lambda ne: _exact_value(clue, a_me - 1, a_opp, ne, "opp", solver, memo, node_counter, node_budget, deadline),
            )

            if not ranked:
                return {
                    "p_win": direct_guess if direct_guess is not None else 0.0,
                    "exact": True, "best_question": None,
                    "guess_now": direct_guess is not None, "ranked_alternatives": [],
                }

            best_val, best_q, best_near_finish = ranked[0]
            guess_now = direct_guess is not None and direct_guess >= best_val
            return {
                "p_win": max(best_val, direct_guess) if direct_guess is not None else best_val,
                "exact": True,
                "best_question": {"qtype": best_q["qtype"], "label": best_q["label"], "near_finish": best_near_finish},
                "guess_now": guess_now,
                "ranked_alternatives": [
                    {"qtype": q["qtype"], "label": q["label"], "p_win": v, "near_finish": nf} for v, q, nf in ranked[1:]
                ],
            }
        except _BudgetExceeded:
            pass

    return _heuristic_fallback(solver, clue, questions, n, a_me, fallback_cap, my_excluded)
