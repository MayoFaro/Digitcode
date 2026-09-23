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
