"""Regression position: 30 September, after A=2 and before U/X."""
from copy import deepcopy

import pytest

from digitcode import pre_endgame as pre
from digitcode.solver import Cancelled, Clue


def n60_clue():
    return Clue(row_totals={'K': 4}, col_totals={'C': 4, 'D': 4, 'G': 1, 'A': 2},
                comparisons=[('T', '<', 'W'), ('T', '>', 'U')])


def by_label(result, label):
    return next(q for q in result['questions'] if q['label'] == label)


def test_real_archive_traps_are_detected_before_any_large_branch_is_evaluated():
    seen = []
    result = pre.evaluate_pre_endgame(n60_clue(), 2, 2, time_budget_s=2, on_progress=seen.append)
    for label in ('Qui est plus grand, U ou X ?', 'Qui est plus grand, U ou V ?'):
        q = by_label(result, label)
        assert q['status'] == 'blacklisted'
        assert q['danger']['p_win'] == pytest.approx(1/3)
        assert any(b['n'] > 20 and b['p_win'] is None for b in q['branches'])
    assert by_label(result, 'Combien en ligne Q ?')['danger']['p_win'] == pytest.approx(.25)
    assert result['finished']
    # Progress snapshots are not mutated by subsequent work.
    assert all(q['status'] == 'incomplete' for q in seen[0]['questions'])
    assert any(q['status'] == 'blacklisted' for q in seen[-1]['questions'])


def test_strict_threshold_and_weighted_ev_with_unknown_branches(monkeypatch):
    # Substitute only the expensive leaf oracle, retaining real partitions,
    # candidate weights, discovery, scheduling and result aggregation.
    def leaf(self, S, e, a_me, a_opp, m_fail, used=0):
        assert used == 1
        assert S.bit_count() <= 20
        return {'p_win': .4 if S.bit_count() == 4 else .5}
    monkeypatch.setattr(pre.TempoEndgameSolver, 'analyze_post_question', leaf)
    result = pre.evaluate_pre_endgame(n60_clue(), 2, 2)
    h = by_label(result, 'Combien en colonne H ?')
    assert h['status'] == 'validated'  # exactly 40% is not <40%
    assert h['worst'] == .4
    assert h['ev'] == pytest.approx((8*.4 + 52*.5)/60)
    ux = by_label(result, 'Qui est plus grand, U ou X ?')
    assert ux['status'] == 'incomplete'
    assert ux['ev'] is None  # the 54-candidate branch has no invented EV


def test_blacklisting_stops_sibling_work_and_reuses_equivalent_branches(monkeypatch):
    calls = []
    def leaf(self, S, *args, **kwargs):
        calls.append(S)
        return {'p_win': .399}
    monkeypatch.setattr(pre.TempoEndgameSolver, 'analyze_post_question', leaf)
    result = pre.evaluate_pre_endgame(n60_clue(), 2, 2)
    assert all(q['status'] == 'blacklisted' for q in result['questions'])
    assert len(calls) == len(set(calls))
    h = by_label(result, 'Combien en colonne H ?')
    assert sum(b['p_win'] is not None for b in h['branches']) == 1
    assert all(b['p_win'] is None for b in h['branches'] if b['n'] > 4)


def test_wide_board_fallback_preserves_small_branch_values(monkeypatch):
    # Force bounded per-answer discovery on the same known position.
    monkeypatch.setattr(pre, 'POOL_CACHE_MAX', 21)
    result = pre.evaluate_pre_endgame(n60_clue(), 2, 2, time_budget_s=2)
    q = by_label(result, 'Qui est plus grand, U ou X ?')
    assert q['danger']['p_win'] == pytest.approx(1/3)
    assert any(b['capped'] and b['p_win'] is None for b in q['branches'])


def test_zero_budget_and_cancellation_do_not_certify_questions():
    result = pre.evaluate_pre_endgame(n60_clue(), 2, 2, time_budget_s=0)
    assert result['finished'] and not result['discovery_complete']
    assert result['questions'] == []
    with pytest.raises(Cancelled):
        pre.evaluate_pre_endgame(n60_clue(), 2, 2, should_cancel=lambda: True)


def test_timeout_keeps_question_unknown_and_retries_with_memo(monkeypatch):
    calls = []
    def leaf(self, *args, **kwargs):
        calls.append(id(self))
        raise pre.EndgameBudgetExceeded()
    monkeypatch.setattr(pre.TempoEndgameSolver, 'analyze_post_question', leaf)
    result = pre.evaluate_pre_endgame(n60_clue(), 2, 2, time_budget_s=.05)
    assert calls and len(set(calls)) == 1
    assert all(q['status'] == 'incomplete' and q['ev'] is None for q in result['questions'])


def test_input_clue_is_not_modified():
    clue = n60_clue()
    before = deepcopy(clue)
    pre.evaluate_pre_endgame(clue, 2, 2, time_budget_s=.1)
    assert clue == before


def test_private_exclusion_changes_weights_without_shrinking_public_pool(monkeypatch):
    excluded = frozenset({(7, 6, 4, 8, 0, 1)})
    seen_exclusion = []
    def leaf(self, S, e, a_me, a_opp, m_fail, used=0):
        if e >= 0:
            assert S & (1 << e)
            seen_exclusion.append(e)
        return {'p_win': .4 if S.bit_count() == 4 else .5}
    monkeypatch.setattr(pre.TempoEndgameSolver, 'analyze_post_question', leaf)
    result = pre.evaluate_pre_endgame(n60_clue(), 1, 2, excluded)
    h = by_label(result, 'Combien en colonne H ?')
    assert seen_exclusion
    assert sum(b['n'] for b in h['branches']) == 60
    assert sum(b['n_mine'] for b in h['branches']) == 59
    assert h['ev'] == pytest.approx((7*.4 + 52*.5)/59)
