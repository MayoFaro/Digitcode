"""Endgame with a finite shared reserve of unasked, non-informative questions.

The released engine remains in endgame.py. This module extends its decision
model, without claiming to solve the imperfect-information equilibrium.
"""
from __future__ import annotations

import time
from typing import Callable, Dict, FrozenSet, List, Optional, Tuple
from .endgame import (
    Candidate, EQuestion, ENDGAME_N_MAX, ENDGAME_TIME_BUDGET_S,
    EndgameBudgetExceeded, ME, OPP, NO_CANDIDATE,
    PHASE_MY_TURN, PHASE_MY_POST_QUESTION, PHASE_OPP_TURN,
    _never, _bits, _keep, code_to_string, opp_hit_probability,
)
from .mapping import POSITIONS, ADJACENT, DIGIT_TO_SEGS, row_contributors, col_contributors
from .solver import Cancelled, Clue, DigitcodeSolver

PHASE_OPP_POST_QUESTION = "opp_post_question"
PHASES = (PHASE_MY_TURN, PHASE_MY_POST_QUESTION, PHASE_OPP_TURN, PHASE_OPP_POST_QUESTION)


def question_entry(q: EQuestion, answer: str) -> dict:
    """Structured clue entry for recording a played null question."""
    if q.qtype == "row":
        return dict(clue_type="row_total", row=q.label.split()[-2], value=int(answer))
    if q.qtype == "col":
        return dict(clue_type="col_total", col=q.label.split()[-2], value=int(answer))
    if q.qtype == "parity":
        return dict(clue_type="parity", pos=q.label.split()[0], value=answer)
    if q.qtype == "seg":
        pos, seg = q.label.split()[0].split(".")
        return dict(clue_type="segment", pos=pos, seg=seg, value=answer == "on")
    return dict(clue_type="comparison", left=answer[0], rel=answer[1], right=answer[2])


def build_universe(solver, clue, n_max=ENDGAME_N_MAX, should_cancel=_never):
    """All unasked questions, including answers already implied by the clues.

    Compute answers directly from complete codes and the shared segment map.
    Unlike the heuristic question enumerator this includes fixed segments and
    excludes comparisons already asked in either direction.
    """
    sols = solver.enumerate_solutions(clue, limit=n_max + 1, should_cancel=should_cancel)
    if not sols or len(sols) > n_max:
        return None
    return universe_from_solutions(sols, clue, should_cancel)


def universe_from_solutions(sols, clue, should_cancel=_never):
    """Build partitions from an already enumerated, complete public pool."""
    candidates = [tuple(sol[p] for p in POSITIONS) for sol in sols]
    questions = []
    def add(qtype, label, answer):
        if should_cancel():
            raise Cancelled()
        groups = {}
        for i, sol in enumerate(sols):
            a = answer(sol)
            groups[a] = groups.get(a, 0) | (1 << i)
        questions.append(EQuestion(qtype, label, tuple(groups), tuple(groups.values())))
    for row in "JKLMNOPQRS":
        if row not in clue.row_totals:
            parts = row_contributors(row)
            add("row", f"Combien en ligne {row} ?", lambda s: str(sum(seg in DIGIT_TO_SEGS[s[p]] for p, seg in parts)))
    for col in "ABCDEFGHI":
        if col not in clue.col_totals:
            parts = col_contributors(col)
            add("col", f"Combien en colonne {col} ?", lambda s: str(sum(seg in DIGIT_TO_SEGS[s[p]] for p, seg in parts)))
    for p in POSITIONS:
        if p not in clue.parity:
            add("parity", f"{p} pair/impair ?", lambda s: "Pair" if s[p] % 2 == 0 else "Impair")
    asked_pairs = {frozenset((a, b)) for a, _, b in clue.comparisons}
    for a, b in ADJACENT:
        if frozenset((a, b)) not in asked_pairs:
            add("cmp", f"Qui est plus grand, {a} ou {b} ?", lambda s: f"{a}>{b}" if s[a] > s[b] else f"{a}<{b}")
    for p in POSITIONS:
        for seg in "abcdefg":
            if (p, seg) not in clue.segment_state:
                add("seg", f"{p}.{seg} on/off ?", lambda s: "on" if seg in DIGIT_TO_SEGS[s[p]] else "off")
    return candidates, questions


class TempoEndgameSolver:
    """Finite search including every unasked public question.

    ``used`` counts questions consumed since this universe was built. Every
    consumed question is constant on the current public pool, so the number
    of available null questions is constant_count(S) - used. Their identities
    do not matter. Informative partitions can be grouped for evaluation, but
    their multiplicities must be retained in constant_count.

    Private-information approximations are inherited from the released
    engine: this is NOT an equilibrium solver for an optimal hidden policy.
    """

    def __init__(
        self, n: int, questions: List[EQuestion], *,
        deadline: Optional[float] = None, should_cancel: Callable[[], bool] = _never,
    ) -> None:
        self.n = n
        self.questions = questions
        self.deadline = deadline
        self.should_cancel = should_cancel
        self._memo: Dict[tuple, float] = {}
        self._guess_cache: dict[tuple, tuple[float, int]] = {}
        self._available_cache: dict[tuple[int, bool], list[EQuestion]] = {}
        self._partition_cache: dict[int, tuple[list[EQuestion], int]] = {}
        self._stability_cache: dict[tuple[int, int, int], int] = {}

    def _check_budget(self) -> None:
        if self.should_cancel():
            raise Cancelled()
        if self.deadline is not None and time.monotonic() > self.deadline:
            raise EndgameBudgetExceeded()

    def partitions(self, S: int) -> tuple[list[EQuestion], int]:
        cached = self._partition_cache.get(S)
        if cached is None:
            unique = {}
            constant_count = 0
            for q in self.questions:
                signature = tuple(sorted(c & S for c in q.classes if c & S))
                if len(signature) == 1:
                    constant_count += 1
                else:
                    if signature not in unique:
                        unique[signature] = EQuestion(q.qtype, q.label, (), signature)
            cached = (list(unique.values()), constant_count)
            self._partition_cache[S] = cached
        return cached

    def stability_threshold(self, S: int, a: int, b: int) -> int:
        """Certified threshold above which only null-reserve parity matters.

        Account for null questions created by each informative answer, which
        gives a much tighter bound than twice the remaining game depth.
        The proof is in docs/superpowers/specs/2026-09-24-endgame-tempo.md.
        """
        if not a or not b or S.bit_count() <= 1:
            return 0
        key = (S, a, b)
        cached = self._stability_cache.get(key)
        if cached is None:
            self._check_budget()
            qs, constant_count = self.partitions(S)
            failures = max(self.stability_threshold(S, a - 1, b),
                           self.stability_threshold(S, a, b - 1))
            children = {c & S for q in qs for c in q.classes if c & S}
            questions = max((self.stability_threshold(child, a, b)
                             - (self.partitions(child)[1] - constant_count - 1)
                             for child in children), default=0)
            cached = 1 + max(1, failures + 1, questions)
            self._stability_cache[key] = cached
        return cached

    def available(self, S: int, used: int) -> list[EQuestion]:
        informative, constant_count = self.partitions(S)
        has_null = constant_count > used
        key = (S, has_null)
        cached = self._available_cache.get(key)
        if cached is None:
            cached = ([EQuestion("null", "Question sans information", ("connue",), (S,))]
                      + informative) if has_null else informative
            self._available_cache[key] = cached
        return cached

    def value(self, S: int, e: int, a_me: int, a_opp: int, mover: int, m_fail: int, used: int = 0) -> float:
        if a_me == 0 and a_opp == 0:
            return 0.5
        if a_me == 0:
            return 0.0
        if a_opp == 0:
            return 1.0
        if S.bit_count() == 1:
            return 1.0 if mover == ME else 0.0
        # Above the proven stability threshold, remove an even number of
        # null moves. Keep the actual question counts in the public result.
        null_count = self.partitions(S)[1] - used
        bound = self.stability_threshold(S, a_me, a_opp)
        if null_count > bound + 1:
            used += null_count - (bound + (null_count - bound) % 2)
        key = (S, e, a_me, a_opp, mover, m_fail, used)
        cached = self._memo.get(key)
        if cached is not None:
            return cached
        self._check_budget()
        mine = S & ~(1 << e) if e >= 0 else S
        if mine == 0:
            result = 0.0
        elif mover == ME:
            result = self._me_value(S, e, mine, a_me, a_opp, m_fail, used)
        else:
            result = self._opp_value(S, e, mine, a_me, a_opp, m_fail, used)
        self._memo[key] = result
        return result

    # --- my moves -------------------------------------------------------

    def my_guess_value(self, S: int, pool: int, g: int, a_me: int, a_opp: int, m_fail: int, used: int = 0) -> float:
        k = pool.bit_count()
        if k == 1:
            return 1.0
        return 1.0 / k + (1.0 - 1.0 / k) * self.value(S, g, a_me - 1, a_opp, OPP, m_fail, used)

    def best_my_guess(self, S: int, pool: int, a_me: int, a_opp: int, m_fail: int, used: int = 0) -> Tuple[float, int]:
        if pool.bit_count() == 1 or a_me == 1:
            return 1.0 / pool.bit_count(), (pool & -pool).bit_length() - 1
        null_count = self.partitions(S)[1] - used
        bound = self.stability_threshold(S, a_me - 1, a_opp)
        if null_count > bound + 1:
            used += null_count - (bound + (null_count - bound) % 2)
        key = (S, pool, a_me, a_opp, m_fail, used)
        cached = self._guess_cache.get(key)
        if cached is not None:
            return cached
        choices = _bits(pool)
        best_v, best_g = -1.0, choices[0]
        for g in choices:
            v = self.my_guess_value(S, pool, g, a_me, a_opp, m_fail, used)
            if v > best_v:
                best_v, best_g = v, g
        self._guess_cache[key] = (best_v, best_g)
        return best_v, best_g

    def _my_question(
        self, S: int, e: int, mine: int, q: EQuestion, a_me: int, a_opp: int, m_fail: int, used: int = 0,
    ) -> Tuple[float, List[dict]]:
        used += 1
        n_mine = mine.bit_count()
        total = 0.0
        branches: List[dict] = []
        for ci, cls in enumerate(q.classes):
            sub = cls & mine
            if not sub:
                continue
            S2 = cls & S
            wait = self.value(S2, _keep(e, S2), a_me, a_opp, OPP, m_fail, used)
            guess, g = self.best_my_guess(S2, sub, a_me, a_opp, m_fail, used)
            prob = sub.bit_count() / n_mine
            if guess >= wait:
                branch = {"ci": ci, "n": sub.bit_count(), "prob": prob, "action": "guess", "g": g, "value": guess}
            else:
                branch = {"ci": ci, "n": sub.bit_count(), "prob": prob, "action": "wait", "g": None, "value": wait}
            # Expose already-computed alternatives for the presentation layer.
            # This does not change the policy or the recursive EV calculation.
            branch.update(guess_value=guess, guess_g=g, wait_value=wait)
            total += prob * branch["value"]
            branches.append(branch)
        return total, branches

    def _my_question_value(self, S, e, mine, q, a_me, a_opp, m_fail, used, incumbent):
        total = 0.0
        remaining = mine.bit_count()
        target = incumbent * remaining
        for cls in q.classes:
            sub = cls & mine
            if not sub:
                continue
            S2 = cls & S
            guess = self.best_my_guess(S2, sub, a_me, a_opp, m_fail, used + 1)[0]
            wait = (self.value(S2, _keep(e, S2), a_me, a_opp, OPP, m_fail, used + 1)
                    if guess < 1.0 else 0.0)
            weight = sub.bit_count()
            total += weight * max(guess, wait)
            remaining -= weight
            # Even perfect wins in all remaining branches cannot improve best.
            if total + remaining <= target:
                return incumbent
        return total / mine.bit_count()

    def _me_value(self, S: int, e: int, mine: int, a_me: int, a_opp: int, m_fail: int, used: int = 0) -> float:
        if mine.bit_count() == 1:
            return 1.0
        best = self.best_my_guess(S, mine, a_me, a_opp, m_fail, used)[0]
        for q in self.available(S, used):
            if best >= 1.0:
                break
            best = max(best, self._my_question_value(S, e, mine, q, a_me, a_opp, m_fail, used, best))
        return best

    # --- opponent moves -------------------------------------------------

    def _opp_guess(self, S: int, e: int, a_me: int, a_opp: int, m_fail: int, used: int = 0) -> float:
        s = S.bit_count()
        hit = opp_hit_probability(s, m_fail)
        if hit >= 1.0:
            return 0.0
        if a_opp == 1:
            return 1.0 - hit
        new_m = m_fail or s
        return (1.0 - hit) * self.value(S, e, a_me, a_opp - 1, ME, new_m, used)

    def _opp_value(self, S: int, e: int, mine: int, a_me: int, a_opp: int, m_fail: int, used: int = 0) -> float:
        qs = self.available(S, used)
        n_mine = mine.bit_count()
        best = self._opp_guess(S, e, a_me, a_opp, m_fail, used)
        for q in qs:
            if best <= 0.0:
                break
            total = 0.0
            for cls in q.classes:
                sub = cls & mine
                if not sub:
                    continue
                S2 = cls & S
                e2 = _keep(e, S2)
                guess = self._opp_guess(S2, e2, a_me, a_opp, m_fail, used + 1)
                wait = (self.value(S2, e2, a_me, a_opp, ME, m_fail, used + 1)
                        if guess > 0.0 else 1.0)
                total += sub.bit_count() / n_mine * min(wait, guess)
                # Remaining contributions are non-negative; this question
                # cannot improve the opponent's incumbent minimum.
                if total >= best:
                    break
            best = min(best, total)
        return best

    # --- root -----------------------------------------------------------

    def analyze(self, S: int, e: int, a_me: int, a_opp: int, m_fail: int, used: int = 0) -> dict:
        """Rank every unasked question and the direct proposal at the root."""
        e = _keep(e, S)
        mine = S & ~(1 << e) if e >= 0 else S
        if a_me == 0 or mine == 0:
            p = 0.5 if (a_me == 0 and a_opp == 0) else 0.0
            return {"p_win": p, "decision": "none", "direct": None, "questions": []}
        v, g = self.best_my_guess(S, mine, a_me, a_opp, m_fail, used)
        direct = {"g": g, "p_win": v}
        questions = []
        evaluated = {}
        for qi, q in enumerate(self.questions):
            self._check_budget()
            signature = tuple(sorted(c & S for c in q.classes if c & S))
            if signature not in evaluated:
                qv, branches = self._my_question(S, e, mine, q, a_me, a_opp, m_fail, used)
                evaluated[signature] = (qv, {q.classes[b["ci"]] & S: b for b in branches})
            qv, by_mask = evaluated[signature]
            branches = [dict(by_mask[c & S], ci=ci) for ci, c in enumerate(q.classes) if c & S in by_mask]
            questions.append({"qi": qi, "p_win": qv, "branches": branches})
        questions.sort(key=lambda r: -r["p_win"])
        if not questions or direct["p_win"] >= questions[0]["p_win"]:
            return {"p_win": direct["p_win"], "decision": "guess_now", "direct": direct, "questions": questions}
        return {"p_win": questions[0]["p_win"], "decision": "question", "direct": direct, "questions": questions}

    def analyze_post_question(self, S: int, e: int, a_me: int, a_opp: int, m_fail: int, used: int = 0) -> dict:
        """My turn, after my question has been answered: the only choice left
        is guessing now (which code) or ending the turn without guessing --
        the same per-branch choice `_my_question` makes, seen from inside
        the branch."""
        e = _keep(e, S)
        mine = S & ~(1 << e) if e >= 0 else S
        wait = self.value(S, e, a_me, a_opp, OPP, m_fail, used)
        if a_me == 0 or mine == 0:
            return {"p_win": wait, "decision": "end_turn", "direct": None, "end_turn_p_win": wait, "questions": []}
        v, g = self.best_my_guess(S, mine, a_me, a_opp, m_fail, used)
        decision = "guess_now" if v >= wait else "end_turn"
        return {
            "p_win": max(v, wait), "decision": decision, "direct": {"g": g, "p_win": v},
            "end_turn_p_win": wait, "questions": [],
        }

    def analyze_opp_turn(self, S: int, e: int, a_me: int, a_opp: int, m_fail: int, used: int = 0) -> dict:
        """The opponent is to move: nothing for me to play, only my odds."""
        v = self.value(S, _keep(e, S), a_me, a_opp, OPP, m_fail, used)
        return {"p_win": v, "decision": "opp_turn", "direct": None, "questions": []}

    def analyze_opp_post_question(self, S: int, e: int, a_me: int, a_opp: int, m_fail: int, used: int = 0) -> dict:
        e = _keep(e, S)
        wait = self.value(S, e, a_me, a_opp, ME, m_fail, used)
        guess = self._opp_guess(S, e, a_me, a_opp, m_fail, used) if a_opp else wait
        return {"p_win": min(wait, guess), "decision": "opp_post_question", "direct": None,
                "questions": [], "opponent_end_turn_p_win": wait, "opponent_guess_p_win": guess}


def evaluate_endgame(
    solver: DigitcodeSolver, clue: Clue, a_me: int, a_opp: int,
    my_excluded: FrozenSet[Candidate], opp_fail_pool_size: int = 0, *,
    phase: str = PHASE_MY_TURN,
    n_max: int = ENDGAME_N_MAX, time_budget_s: float = ENDGAME_TIME_BUDGET_S,
    should_cancel: Callable[[], bool] = _never,
) -> Optional[dict]:
    """Display-ready endgame recommendation, or None when the public pool
    is empty or larger than `n_max`. `solver` must already be propagated
    for `clue`. `phase` says where in the turn order the board is (see the
    PHASE_* constants): only PHASE_MY_TURN ranks questions."""
    deadline = time.monotonic() + time_budget_s
    def check():
        if should_cancel():
            raise Cancelled()
        if time.monotonic() >= deadline:
            raise EndgameBudgetExceeded()
        return False
    try:
        universe = build_universe(solver, clue, n_max, check)
    except EndgameBudgetExceeded:
        return {"complete": False, "n_public": None, "phase": phase}
    if universe is None:
        return None
    candidates, questions = universe
    n = len(candidates)
    full = (1 << n) - 1
    index = {c: i for i, c in enumerate(candidates)}
    excluded_idx = sorted(index[c] for c in my_excluded if c in index)
    e = excluded_idx[0] if excluded_idx else NO_CANDIDATE
    mine = full
    for i in excluded_idx:
        mine &= ~(1 << i)
    engine = TempoEndgameSolver(
        n, questions, deadline=deadline, should_cancel=should_cancel,
    )
    analyzers = {
        PHASE_MY_TURN: engine.analyze,
        PHASE_MY_POST_QUESTION: engine.analyze_post_question,
        PHASE_OPP_TURN: engine.analyze_opp_turn,
        PHASE_OPP_POST_QUESTION: engine.analyze_opp_post_question,
    }
    try:
        if phase not in analyzers:
            raise ValueError("Phase de tour inconnue")
        if a_me == 0 or a_opp == 0:
            raw = {"p_win": 0.5 if a_me == a_opp == 0 else float(a_me > 0),
                   "decision": "won" if a_me > 0 else "none", "direct": None, "questions": []}
        else:
            raw = analyzers[phase](full, e, a_me, a_opp, opp_fail_pool_size)
    except EndgameBudgetExceeded:
        return {"complete": False, "n_public": n}

    def fmt_question(r: dict, with_branches: bool) -> dict:
        q = questions[r["qi"]]
        out = {"qtype": q.qtype, "label": q.label, "p_win": r["p_win"],
               "worst": min(b["value"] for b in r["branches"]),
               "is_null": len(q.classes) == 1,
               "entry": question_entry(q, q.answers[0]) if len(q.classes) == 1 else None}
        if with_branches:
            out["branches"] = [
                {
                    "answer": q.answers[b["ci"]],
                    "n": b["n"],
                    "prob": b["prob"],
                    "action": b["action"],
                    "code": code_to_string(candidates[b["g"]]) if b["g"] is not None else None,
                    "value": b["value"],
                    "guess_value": b["guess_value"],
                    "guess_code": code_to_string(candidates[b["guess_g"]]),
                    "wait_value": b["wait_value"],
                    "immediate_hit": 1.0 / b["n"],
                }
                for b in r["branches"]
            ]
        return out

    direct = raw["direct"]
    # Presentation-only comparisons: fixed question-then-guess, and a null
    # question explicitly WITHOUT a guess, rather than the adaptive maximum.
    informative = [r for r in raw["questions"] if len(questions[r["qi"]].classes) > 1]
    then_guess = None
    if informative:
        chosen = max(informative, key=lambda r: sum(b["prob"] * b["guess_value"] for b in r["branches"]))
        then_guess = fmt_question(chosen, True)
        then_guess["p_win"] = sum(b["prob"] * b["guess_value"] for b in chosen["branches"])
    null = next((r for r in raw["questions"] if len(questions[r["qi"]].classes) == 1), None)
    null_wait = None
    if null is not None:
        null_wait = fmt_question(null, False)
        null_wait["p_win"] = null["branches"][0]["wait_value"]
    return {
        "complete": True,
        "model": "tempo",
        "best_question_then_guess": then_guess,
        "null_without_guess": null_wait,
        "null_questions_remaining": sum(len(q.classes) == 1 for q in questions),
        "null_questions": [dict(label=q.label, answer=q.answers[0], entry=question_entry(q, q.answers[0]))
                           for q in questions if len(q.classes) == 1],
        "opponent_end_turn_p_win": raw.get("opponent_end_turn_p_win"),
        "opponent_guess_p_win": raw.get("opponent_guess_p_win"),
        "phase": phase,
        "n_public": n,
        "n_mine": mine.bit_count(),
        "p_win": raw["p_win"],
        "decision": raw["decision"],
        "end_turn_p_win": raw.get("end_turn_p_win"),
        "guess_now": (
            {"code": code_to_string(candidates[direct["g"]]), "p_win": direct["p_win"]}
            if direct is not None else None
        ),
        "best_question": fmt_question(raw["questions"][0], True) if raw["questions"] else None,
        "ranked_questions": [fmt_question(r, True) for r in raw["questions"]],
        "best_informative_question": next((fmt_question(r, True) for r in raw["questions"]
                                            if len(questions[r["qi"]].classes) > 1), None),
        "best_null_question": next((fmt_question(r, True) for r in raw["questions"]
                                    if len(questions[r["qi"]].classes) == 1), None),
    }
