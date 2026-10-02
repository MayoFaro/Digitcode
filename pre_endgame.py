"""Progressive risk and question evaluation before the <=20 endgame.

Only complete post-question values can blacklist a question. Large and timed
out branches stay unknown; never substitute a heuristic for their win EV.
"""
from __future__ import annotations

from copy import deepcopy
import time

from .endgame import ENDGAME_N_MAX, EndgameBudgetExceeded
from .endgame_tempo import TempoEndgameSolver, universe_from_solutions
from .mapping import ADJACENT, POSITIONS, DIGIT_TO_SEGS, row_contributors, col_contributors
from .solver import Cancelled, DigitcodeSolver

RISK_THRESHOLD = 0.40
TIME_BUDGET_S = 55.0
MAX_TIME_BUDGET_S = 60.0
POOL_CACHE_MAX = 500


def _question_specs(solver, clue):
    """Cheap legal answer supersets; branch enumeration removes impossible answers."""
    for kind, letters, recorded, contributors in (
        ('row', 'JKLMNOPQRS', clue.row_totals, row_contributors),
        ('col', 'ABCDEFGHI', clue.col_totals, col_contributors),
    ):
        for letter in letters:
            if letter not in recorded:
                noun = 'ligne' if kind == 'row' else 'colonne'
                yield dict(qtype=kind, label=f'Combien en {noun} {letter} ?',
                           answers=[str(v) for v in solver._reachable_sums(contributors(letter))])
    for p in POSITIONS:
        if p not in clue.parity:
            yield dict(qtype='parity', label=f'{p} pair/impair ?', answers=['Pair', 'Impair'])
    asked = {frozenset((a, b)) for a, _, b in clue.comparisons}
    for a, b in ADJACENT:
        if frozenset((a, b)) not in asked:
            yield dict(qtype='cmp', label=f'Qui est plus grand, {a} ou {b} ?', answers=[f'{a}<{b}', f'{a}>{b}'])
    for p in POSITIONS:
        for seg in 'abcdefg':
            if (p, seg) not in clue.segment_state:
                values = {seg in DIGIT_TO_SEGS[d] for d in solver.domains[p]}
                if len(values) == 2:
                    yield dict(qtype='seg', label=f'{p}.{seg} on/off ?', answers=['on', 'off'])


def evaluate_pre_endgame(clue, a_me, a_opp, excluded=frozenset(), opp_fail_pool_size=0, *,
                         time_budget_s=TIME_BUDGET_S, should_cancel=lambda: False,
                         on_progress=lambda result: None):
    """Screen hypothetical *my* questions, regardless of the actual turn.

    One deadline includes preparation. Globally smallest branches run first.
    A failed time slice retains the engine's memo for subsequent passes.
    Risk flags persist while other evaluable branches continue for ranking.
    The result lists only informative questions with a reachable <=20 branch.
    """
    start = time.monotonic()
    deadline = (float('inf') if time_budget_s is None else
                start + max(0.0, min(time_budget_s, MAX_TIME_BUDGET_S)))
    result = dict(kind='pre_endgame', threshold=RISK_THRESHOLD, questions=[],
                  discovery_complete=False, finished=False, elapsed_s=0.0)

    def check():
        if should_cancel():
            raise Cancelled()
        if time.monotonic() >= deadline:
            raise EndgameBudgetExceeded()
        return False

    def publish():
        result['elapsed_s'] = time.monotonic() - start
        on_progress(deepcopy(result))  # queued Qt signals must own immutable snapshots

    def finish():
        result['finished'] = True
        result['elapsed_s'] = time.monotonic() - start
        return result

    if a_me <= 0 or a_opp <= 0:
        result['discovery_complete'] = True
        return finish()
    tasks = {}
    shared_engine = None
    shared_candidates = None

    def add_question(spec, branches):
        live = [b for b in branches if b['n_mine'] != 0]
        if len(branches) <= 1 or not any(not b['capped'] and b['n'] <= ENDGAME_N_MAX for b in live):
            return
        q = dict(qtype=spec['qtype'], label=spec['label'], status='incomplete',
                 branches=[], ev=None, worst=None, best=None)
        for b in live:
            record = {k: b[k] for k in ('answer', 'n', 'n_mine', 'capped')}
            record['p_win'] = None
            q['branches'].append(record)
            if not b['capped'] and b['n'] <= ENDGAME_N_MAX:
                key = b['key']
                task = tasks.setdefault(key, dict(branch=b, refs=[], engine=None))
                task['refs'].append((q, record))
        result['questions'].append(q)

    try:
        check()
        solver = DigitcodeSolver()
        solver.propagate(clue)
        # On modest pools, enumerating once gives every partition exactly and
        # allows one shared memo across questions. No global N eligibility cap.
        sols = solver.enumerate_solutions(clue, limit=POOL_CACHE_MAX + 1, should_cancel=check)
        if len(sols) <= POOL_CACHE_MAX:
            if len(sols) <= ENDGAME_N_MAX:
                result['discovery_complete'] = True
                return finish()
            shared_candidates, questions = universe_from_solutions(sols, clue, check)
            shared_engine = TempoEndgameSolver(len(sols), questions, should_cancel=should_cancel)
            private_mask = sum(1 << i for i, c in enumerate(shared_candidates) if c in excluded)
            for q in questions:
                check()
                branches = [dict(answer=ans, n=mask.bit_count(),
                                 n_mine=(mask & ~private_mask).bit_count(), capped=False,
                                 key=mask, mask=mask)
                            for ans, mask in zip(q.answers, q.classes)]
                add_question(dict(qtype=q.qtype, label=q.label), branches)
        else:
            # Wide board: never enumerate the entire pool. Stop each answer
            # after 21 public solutions; a capped branch cannot be certified.
            for spec in _question_specs(solver, clue):
                branches = []
                for answer in spec['answers']:
                    check()
                    child_clue = solver._apply_answer_to_clue(clue, spec, answer, 0)
                    child = DigitcodeSolver()
                    child.domains = {p: set(ds) for p, ds in solver.domains.items()}
                    try:
                        child.propagate(child_clue)
                    except ValueError:
                        continue
                    child_sols = child.enumerate_solutions(child_clue, limit=ENDGAME_N_MAX + 1, should_cancel=check)
                    if not child_sols:
                        continue
                    codes = tuple(sorted(tuple(s[p] for p in POSITIONS) for s in child_sols))
                    capped = len(codes) > ENDGAME_N_MAX
                    branches.append(dict(answer=answer, n=len(codes), capped=capped,
                                         n_mine=None if capped else sum(c not in excluded for c in codes),
                                         key=codes, sols=child_sols))
                add_question(spec, branches)
        result['discovery_complete'] = True
    except EndgameBudgetExceeded:
        return finish()

    publish()
    pending = sorted(tasks.values(), key=lambda t: t['branch']['n'])
    quantum = 0.25
    while pending:
        retry = []
        for task in pending:
            refs = task['refs']
            if not refs:
                continue
            try:
                check()
            except EndgameBudgetExceeded:
                return finish()
            branch = task['branch']
            if shared_engine is not None:
                engine, candidates, S = shared_engine, shared_candidates, branch['mask']
            else:
                if task['engine'] is None:
                    # Keep the parent question catalogue and consume one move.
                    # Rebuilding only from clues without consuming it would
                    # give an extra null question and an incorrect tempo.
                    candidates, qs = universe_from_solutions(branch['sols'], clue, should_cancel)
                    task['engine'] = (TempoEndgameSolver(len(candidates), qs, should_cancel=should_cancel), candidates)
                engine, candidates = task['engine']
                S = (1 << len(candidates)) - 1
            e = next((i for i, code in enumerate(candidates) if code in excluded and S & (1 << i)), -1)
            # After the cheap sweep, finish fully evaluable questions first.
            # Spreading every slice equally can leave *all* EVs incomplete.
            focus = quantum > 0.25 and any(all(not b2['capped'] and b2['n'] <= ENDGAME_N_MAX
                                               for b2 in q['branches']) for q, _ in refs)
            engine.deadline = deadline if focus else min(deadline, time.monotonic() + quantum)
            try:
                raw = engine.analyze_post_question(S, e, a_me, a_opp, opp_fail_pool_size, used=1)
            except EndgameBudgetExceeded:
                retry.append(task)
                continue
            value = raw['p_win']
            for q, b in refs:
                b['p_win'] = value
                if value < RISK_THRESHOLD - 1e-12:
                    q['status'] = 'blacklisted'
                    if value < q.get('danger', {}).get('p_win', 1.0):
                        q['danger'] = dict(b)
                if all(b2['p_win'] is not None for b2 in q['branches']):
                    if q['status'] != 'blacklisted':
                        q['status'] = 'validated'
                    total = sum(b2['n_mine'] for b2 in q['branches'])
                    q['ev'] = sum(b2['p_win'] * b2['n_mine'] for b2 in q['branches']) / total
                    q['worst'] = min(b2['p_win'] for b2 in q['branches'])
                    q['best'] = max(b2['p_win'] for b2 in q['branches'])
            publish()
        pending = sorted(retry, key=lambda t: (
            not any(all(not b['capped'] and b['n'] <= ENDGAME_N_MAX
                                                        for b in q['branches']) for q, _ in t['refs']),
            t['branch']['n'],
        ))
        quantum = min(quantum * 4, 4.0)
    return finish()
