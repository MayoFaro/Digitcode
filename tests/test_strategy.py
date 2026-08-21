from digitcode.solver import DigitcodeSolver, Clue
from digitcode.strategy import _clue_signature, _solution_tuple, _solver_for, _best_guess_value, _question_branches


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


# --- p_win must always be a probability -------------------------------------
#
# Root cause these guard: summing count_solutions_exact() over a question's
# answer branches does NOT reproduce the parent's own count. solver.py's
# apply_no_equal_adjacent / apply_max_two only prune domains with len() > 1,
# so a violation between two positions already pinned to singletons by
# independent constraints goes uncaught -- and whether that happens depends on
# the order positions get fixed, which differs between parent and child
# enumerations. Weights must therefore be normalized per question, by that
# question's own branch-count sum, never by the parent count.

import pytest


def assert_probabilities(res, context: str) -> None:
    assert 0.0 <= res["p_win"] <= 1.0, f"{context}: p_win={res['p_win']!r}"
    for alt in res["ranked_alternatives"]:
        assert 0.0 <= alt["p_win"] <= 1.0, f"{context}: {alt['label']} p_win={alt['p_win']!r}"


def reported_cli_state():
    """The exact state from the final-review bug report, reached in the CLI
    with `L0, Q0, F0, I9, H5, U pair, V pair, W pair, X impair`. Its parent
    count is 4 while one question's branches count 1+4+1=6, so dividing by the
    parent count gave weights summing above 1 (reported P(je gagne)=103.12%)."""
    clue = Clue()
    clue.row_totals["L"] = 0
    clue.row_totals["Q"] = 0
    clue.col_totals["F"] = 0
    clue.col_totals["I"] = 9
    clue.col_totals["H"] = 5
    clue.parity["U"] = "Pair"
    clue.parity["V"] = "Pair"
    clue.parity["W"] = "Pair"
    clue.parity["X"] = "Impair"
    s = DigitcodeSolver()
    s.propagate(clue)
    return s, clue


def test_exact_path_p_win_within_zero_one_on_reported_cli_state():
    s, clue = reported_cli_state()
    res = evaluate_race_strategy(s, clue, a_me=2, a_opp=2)
    assert res["exact"] is True  # this state must exercise the exact path
    assert_probabilities(res, "reported CLI state")


@pytest.mark.parametrize("a_me,a_opp", [(2, 2), (1, 2), (2, 1), (1, 1)])
def test_exact_path_p_win_within_zero_one_across_attempt_counts(a_me, a_opp):
    s, clue = reported_cli_state()
    res = evaluate_race_strategy(s, clue, a_me=a_me, a_opp=a_opp)
    assert_probabilities(res, f"reported CLI state a_me={a_me} a_opp={a_opp}")


@pytest.mark.parametrize("free,expect_exact", [
    ({"Y": {7, 8}}, True),
    ({"Y": {3, 5, 7}}, True),
    ({"X": {6, 7}, "Y": {8, 9}}, True),
    # N=5 costs ~23s to solve exactly, so the default time budget makes it
    # fall back -- the invariant must hold on either path.
    ({"Y": {1, 3, 5, 7, 9}}, False),
])
def test_exact_path_p_win_within_zero_one_over_constructed_states(free, expect_exact):
    # Property-style sweep: the mismatch is state-dependent, so cover several
    # small boards rather than relying on one.
    s = make_solver(free)
    res = evaluate_race_strategy(s, Clue(), a_me=2, a_opp=2)
    assert res["exact"] is expect_exact
    assert_probabilities(res, f"{free} (exact={res['exact']})")


def non_saturated_fallback_state():
    """A moderately-constrained board with N=138: above n_exact_max (so the
    fallback runs) but far below fallback_cap (so it takes the *non-saturated*
    branch, which the saturated-path guard above does not cover). Found by a
    randomized sweep; one of its questions has branch counts 96+138+138+96=468
    against a parent count of 138, which made the old `n`-normalized score
    2.97 and hence p_win = -1.97 for that alternative."""
    clue = Clue()
    clue.parity["T"] = "Impair"
    clue.parity["U"] = "Impair"
    clue.row_totals["K"] = 1
    clue.row_totals["P"] = 3
    clue.row_totals["Q"] = 0
    clue.col_totals["A"] = 2
    clue.col_totals["I"] = 0
    s = DigitcodeSolver()
    s.propagate(clue)
    return s, clue


def test_fallback_non_saturated_p_win_and_alternatives_stay_within_zero_one():
    s, clue = non_saturated_fallback_state()
    n = s.count_solutions_exact(clue, cap=500)
    assert 5 < n < 500, f"state must land in the non-saturated fallback branch, got N={n}"
    res = evaluate_race_strategy(s, clue, a_me=2, a_opp=2)
    assert res["exact"] is False
    assert_probabilities(res, "non-saturated fallback")


def test_fallback_non_saturated_on_a_small_constructed_board():
    s = make_solver({"X": {5, 6, 7}, "Y": {1, 2, 3}})  # N=9: fallback, unsaturated
    n = s.count_solutions_exact(Clue(), cap=500)
    assert 5 < n < 500
    res = evaluate_race_strategy(s, Clue(), a_me=2, a_opp=2)
    assert res["exact"] is False
    assert_probabilities(res, "non-saturated fallback (constructed)")


def test_heuristic_fallback_with_zero_solutions_does_not_divide_by_zero():
    from digitcode.strategy import _heuristic_fallback

    s = DigitcodeSolver()
    s.domains = {k: {5} for k in ["T", "U", "V", "W", "X", "Y"]}
    clue = Clue()
    clue.parity["T"] = "Pair"  # unsatisfiable against the pinned odd domain
    assert s.count_solutions_exact(clue, cap=500) == 0
    # A non-empty question list is required to get past the `if not questions`
    # early return; the n == 0 guard must fire before anything is read from it.
    fake_questions = [{"qtype": "row", "label": "?", "outcomes": [{"answer": "0"}, {"answer": "1"}]}]
    res = _heuristic_fallback(s, clue, fake_questions, n_gate=0, a_me=2, fallback_cap=500)
    assert res["exact"] is False
    assert res["best_question"] is None
    assert 0.0 <= res["p_win"] <= 1.0


def test_time_budget_forces_fallback_even_under_threshold():
    # Companion to the node_budget guard: an already-expired wall-clock
    # deadline must trigger the same fallback path.
    s = make_solver({"X": {6, 7}, "Y": {8, 9}})  # N=4, normally exact
    res = evaluate_race_strategy(s, Clue(), a_me=2, a_opp=2, time_budget_s=-1.0)
    assert res["exact"] is False


def test_exact_path_stays_within_the_default_time_budget():
    # Regression guard for interactive latency: node_budget alone did not
    # bound wall-clock time (each node costs an uncapped DFS count plus a full
    # question enumeration). This N=5 board measured ~23s before the node
    # budget ever tripped; show_race now runs after every CLI input line.
    import time

    s = make_solver({"Y": {1, 3, 5, 7, 9}})
    t0 = time.monotonic()
    res = evaluate_race_strategy(s, Clue(), a_me=2, a_opp=2)
    elapsed = time.monotonic() - t0
    assert elapsed < 10.0, f"took {elapsed:.1f}s despite the 3s default budget"
    assert_probabilities(res, "default time budget")


def test_near_finish_true_when_a_branch_reaches_the_default_threshold():
    # N=2: any informative question resolves to two 1-solution branches,
    # i.e. immediately near-finish under the default threshold (3).
    s = make_solver({"Y": {7, 8}})
    res = evaluate_race_strategy(s, Clue(), a_me=2, a_opp=2)
    assert res["exact"] is True
    assert res["best_question"]["near_finish"] is True


def test_near_finish_threshold_is_configurable():
    s = make_solver({"Y": {7, 8}})
    res = evaluate_race_strategy(s, Clue(), a_me=2, a_opp=2, near_finish_threshold=0)
    # a branch of size 1 never satisfies a threshold of 0 -- nothing qualifies.
    assert res["best_question"]["near_finish"] is False
    for alt in res["ranked_alternatives"]:
        assert alt["near_finish"] is False


def test_near_finish_matches_the_recommended_questions_own_branch_counts():
    s = make_solver({"X": {6, 7}, "Y": {8, 9}})  # N=4
    res = evaluate_race_strategy(s, Clue(), a_me=2, a_opp=2)
    assert res["exact"] is True

    all_questions = [q for q in s.enumerate_all_questions(Clue()) if len(q["outcomes"]) > 1]
    for entry in [res["best_question"]] + res["ranked_alternatives"]:
        matching_q = next(q for q in all_questions if q["label"] == entry["label"])
        branches = _question_branches(s, Clue(), matching_q)
        expected = any(n_ans <= 3 for _, _, n_ans in branches)
        assert entry["near_finish"] == expected, entry["label"]


def test_near_finish_always_false_in_the_fallback_regime():
    s = DigitcodeSolver()
    s.propagate(Clue())
    res = evaluate_race_strategy(s, Clue(), a_me=2, a_opp=2)
    assert res["exact"] is False
    assert res["best_question"]["near_finish"] is False
    for alt in res["ranked_alternatives"]:
        assert alt["near_finish"] is False
