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
