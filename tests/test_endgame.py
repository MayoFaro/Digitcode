import pytest
import time

from digitcode.endgame import (
    EQuestion,
    ME,
    OPP,
    build_universe,
    code_consistent,
    code_to_string,
    opp_hit_probability,
    EndgameBudgetExceeded,
    EndgameSolver,
)
from digitcode.solver import Clue, Cancelled

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


def test_build_universe_skips_a_question_that_does_not_cover_every_candidate(monkeypatch):
    import digitcode.endgame as endgame_module

    s = make_solver({"X": {5, 6}, "Y": {1, 2, 3}})
    candidates_before, questions_before = build_universe(s, Clue())
    assert questions_before, "sanity: this board normally has informative questions"

    # Make one candidate consistent with NO answer of ANY question -- an
    # (artificial) failure to cover the universe. Every question must then
    # be dropped rather than searched over with probabilities summing < 1.
    target = candidates_before[0]
    real_code_consistent = endgame_module.code_consistent

    def fake_code_consistent(code, clue):
        if code == target:
            return False
        return real_code_consistent(code, clue)

    monkeypatch.setattr(endgame_module, "code_consistent", fake_code_consistent)
    _, questions_after = build_universe(s, Clue())
    assert questions_after == []


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


# --- turn phases ------------------------------------------------------------

from digitcode.endgame import PHASE_MY_POST_QUESTION, PHASE_MY_TURN, PHASE_OPP_TURN


def test_post_question_phase_compares_guessing_with_ending_the_turn():
    # N2, no question: guessing now wins 1/2 and, if wrong, the opponent must
    # guess 1/2 before I win -> 3/4. Ending the turn: the opponent guesses
    # 1/2; if wrong, it failed on this very pool, so after my own miss its
    # next guess is certain -> 1/2 * 1/2 = 1/4.
    eng = _toy(2, [], **FULL_FLAGS)
    res = eng.analyze_post_question(3, -1, 2, 2, 0)
    assert res["decision"] == "guess_now"
    assert res["p_win"] == pytest.approx(0.75)
    assert res["end_turn_p_win"] == pytest.approx(0.25)
    assert res["questions"] == []


def test_post_question_phase_without_attempts_ends_the_turn():
    eng = _toy(2, [], **FULL_FLAGS)
    res = eng.analyze_post_question(3, -1, 0, 1, 0)
    assert res["decision"] == "end_turn"
    assert res["direct"] is None
    assert res["p_win"] == 0.0


def test_opp_turn_phase_reports_my_value_with_the_opponent_to_move():
    eng = _toy(2, [], **FULL_FLAGS)
    res = eng.analyze_opp_turn(3, -1, 2, 2, 0)
    assert res["decision"] == "opp_turn"
    assert res["p_win"] == pytest.approx(0.25)


def test_evaluate_endgame_phases():
    s = make_solver({"X": {5, 6}, "Y": {1, 2}})
    mine = evaluate_endgame(s, Clue(), 2, 2, frozenset())
    assert mine["phase"] == PHASE_MY_TURN

    post = evaluate_endgame(s, Clue(), 2, 2, frozenset(), phase=PHASE_MY_POST_QUESTION)
    assert post["phase"] == PHASE_MY_POST_QUESTION
    assert post["decision"] in ("guess_now", "end_turn")
    assert post["best_question"] is None and post["ranked_questions"] == []
    assert post["p_win"] == pytest.approx(max(post["guess_now"]["p_win"], post["end_turn_p_win"]))

    opp = evaluate_endgame(s, Clue(), 2, 2, frozenset(), phase=PHASE_OPP_TURN)
    assert opp["decision"] == "opp_turn"
    assert opp["guess_now"] is None
    assert opp["p_win"] == pytest.approx(post["end_turn_p_win"])
