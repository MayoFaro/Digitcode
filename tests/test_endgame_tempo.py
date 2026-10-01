"""Rule-level oracle: track every available question explicitly, without
partition deduplication, reserve compression, or calls to the production search.
"""
from functools import lru_cache
import random

import pytest

from digitcode.endgame import EQuestion, EndgameBudgetExceeded, ME, OPP, code_consistent
from digitcode.endgame_tempo import TempoEndgameSolver, build_universe, evaluate_endgame, question_entry
from digitcode.solver import Cancelled, Clue
from tests.conftest import make_solver


def question(*classes):
    return EQuestion("toy", "toy", tuple(map(str, range(len(classes)))), tuple(classes))


def explicit_oracle(questions):
    @lru_cache(None)
    def value(S, e, a, b, mover, m, available):
        if a == 0 or b == 0:
            return 0.5 if a == b == 0 else float(a > 0)
        pool = S & ~(1 << e) if e >= 0 else S
        if not pool:
            return 0.0

        def guess(S, pool, e, remaining):
            if mover == ME:
                n = pool.bit_count()
                return max(1 / n + (1 - 1 / n) * value(S, g, a - 1, b, OPP, m, remaining)
                           for g in range(S.bit_length()) if pool & (1 << g))
            n = S.bit_count()
            # Marginalize explicitly over a hidden failed code (may be outside S).
            if n == 1:
                hit = 1.0
            elif m:
                size = max(m, n)
                hit = ((n - 1) / (size - 1) / (n - 1)
                       + (size - n) / (size - 1) / n)
            else:
                hit = 1 / n
            return (1 - hit) * value(S, e, a, b - 1, ME, m or n, remaining)

        combine = max if mover == ME else min
        options = [guess(S, pool, e, available)]
        for qi in available:
            remaining = tuple(i for i in available if i != qi)
            total = 0.0
            for cls in questions[qi].classes:
                child = S & cls
                sub = pool & child
                if not sub:
                    continue
                e2 = e if e >= 0 and child & (1 << e) else -1
                wait = value(child, e2, a, b, 1 - mover, m, remaining)
                total += sub.bit_count() / pool.bit_count() * combine(wait, guess(child, sub, e2, remaining))
            options.append(total)
        return combine(options)
    return value


@pytest.mark.parametrize("seed", range(12))
def test_search_matches_explicit_legal_action_oracle(seed):
    rng = random.Random(seed)
    n = rng.randrange(2, 5)
    full = (1 << n) - 1
    qs = []
    for _ in range(3):
        left = rng.randrange(1, full)
        qs.append(question(left, full ^ left))
    qs += [qs[0]]  # Equal partitions remain two distinct playable questions.
    qs += [question(full)] * rng.randrange(0, 7)
    oracle = explicit_oracle(qs)
    engine = TempoEndgameSolver(n, qs)
    for a, b in ((1, 1), (1, 2), (2, 1), (2, 2)):
        for mover in (ME, OPP):
            e = 0 if a == 1 else -1
            m = n + 1 if b == 1 else 0
            expected = oracle(full, e, a, b, mover, m, tuple(range(len(qs))))
            assert engine.value(full, e, a, b, mover, m) == pytest.approx(expected)


def test_a_null_question_changes_the_best_move_and_is_consumed():
    qs = [question(3, 12), question(15)]
    oracle = explicit_oracle(qs)
    engine = TempoEndgameSolver(4, qs)
    r = engine.analyze(15, -1, 1, 1, 0)
    assert r["p_win"] == pytest.approx(oracle(15, -1, 1, 1, ME, 0, (0, 1)))
    null = next(q for q in r["questions"] if q["qi"] == 1)
    assert null["branches"][0]["action"] == "wait"
    assert null["p_win"] > r["direct"]["p_win"]
    assert engine.value(15, -1, 1, 1, ME, 0, used=1) == pytest.approx(
        oracle(15, -1, 1, 1, ME, 0, (0,)))


def test_catalog_covers_all_unasked_questions_including_known_segments():
    s = make_solver({"X": {5, 6}, "Y": {1, 2}})
    candidates, qs = build_universe(s, Clue())
    assert len(qs) == 74  # 10 rows + 9 columns + 6 parities + 7 comparisons + 42 segments
    assert any(q.qtype == "seg" and len(q.classes) == 1 for q in qs)
    for q in qs:
        assert sum(q.classes) == (1 << len(candidates)) - 1
        for answer, mask in zip(q.answers, q.classes):
            child = s._apply_answer_to_clue(Clue(), {"qtype": q.qtype, "label": q.label}, answer, 0)
            for i, candidate in enumerate(candidates):
                assert code_consistent(candidate, child) == bool(mask & (1 << i))


def test_asked_comparison_is_removed_even_if_recorded_in_reverse():
    s = make_solver({"X": {5, 6}, "Y": {1, 2}})
    candidates, qs = build_universe(s, Clue())
    q = next(q for q in qs if q.qtype == "cmp" and len(q.classes) == 1)
    answer = q.answers[0]
    clue = Clue(comparisons=[(answer[2], "<" if answer[1] == ">" else ">", answer[0])])
    _, remaining = build_universe(s, clue)
    assert q.label not in [r.label for r in remaining]


def test_post_question_phases_offer_no_second_question():
    s = make_solver({"X": {5, 6}, "Y": {1, 2}})
    mine = evaluate_endgame(s, Clue(), 2, 2, frozenset(), phase="my_post_question")
    assert mine["decision"] in ("guess_now", "end_turn")
    assert mine["p_win"] == pytest.approx(max(mine["guess_now"]["p_win"], mine["end_turn_p_win"]))
    assert mine["best_question"] is None and mine["ranked_questions"] == []
    opp = evaluate_endgame(s, Clue(), 2, 1, frozenset(), 4, phase="opp_post_question")
    assert opp["decision"] == "opp_post_question"
    assert opp["p_win"] == pytest.approx(min(opp["opponent_guess_p_win"], opp["opponent_end_turn_p_win"]))
    assert opp["best_question"] is None and opp["guess_now"] is None


def test_budget_includes_universe_construction_and_cancellation():
    s = make_solver({"X": {5, 6}, "Y": {1, 2}})
    assert evaluate_endgame(s, Clue(), 2, 2, frozenset(), time_budget_s=-1)["complete"] is False
    with pytest.raises(Cancelled):
        evaluate_endgame(s, Clue(), 2, 2, frozenset(), should_cancel=lambda: True)


def test_terminal_does_not_recommend_another_move():
    s = make_solver({"X": {5, 6}, "Y": {1, 2}})
    result = evaluate_endgame(s, Clue(), 2, 0, frozenset())
    assert result["decision"] == "won" and result["p_win"] == 1.0
    assert result["guess_now"] is None


@pytest.mark.parametrize("n", (3, 4, 5))
def test_large_reserve_compression_matches_uncompressed_search(n):
    full = (1 << n) - 1
    qs = [question(1, full ^ 1), question(3, full ^ 3)] + [question(full)] * 35
    compressed = TempoEndgameSolver(n, qs)
    uncompressed = TempoEndgameSolver(n, qs)
    uncompressed.stability_threshold = lambda S, a, b: 10000
    for a, b in ((1, 1), (1, 2), (2, 1), (2, 2)):
        for mover in (ME, OPP):
            for used in (0, 1):
                assert compressed.value(full, -1, a, b, mover, n + 2, used) == pytest.approx(
                    uncompressed.value(full, -1, a, b, mover, n + 2, used))


def test_ranked_questions_export_every_branch_and_worst_value():
    solver = make_solver({'X': {5, 6}, 'Y': {1, 2}})
    result = evaluate_endgame(solver, Clue(), 1, 1, frozenset())
    assert result['complete'] and result['ranked_questions']
    for q in result['ranked_questions']:
        branches = q['branches']
        assert sum(b['prob'] for b in branches) == pytest.approx(1)
        assert q['worst'] == min(b['value'] for b in branches)
        assert q['p_win'] == pytest.approx(sum(b['prob'] * b['value'] for b in branches))
