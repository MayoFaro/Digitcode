from digitcode.solver import DigitcodeSolver, Clue
from digitcode.strategy import _clue_signature, _solution_tuple, _solver_for, _best_guess_value


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
