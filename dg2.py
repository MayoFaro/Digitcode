"""DG2: race planner with public questions and private failed guesses.

The module is deliberately independent from ``GameState``.  A caller gives a
player-only observation and receives one legal action; the secret and the
opponent's failed codes never enter this API.
"""
from __future__ import annotations

from dataclasses import dataclass
import random
from typing import Optional

from .endgame import Candidate
from .endgame_tempo import universe_from_solutions
from .mapping import POSITIONS
from .selfplay import Action, Ask, EndTurn, Guess, Observation
from .solver import Clue, DigitcodeSolver


@dataclass(frozen=True)
class DG2Recommendation:
    action: Action
    value: float
    exact: bool


class _BudgetExceeded(Exception):
    pass


class _Planner:
    """Alternating public-partition search from one player's observation.

    The public candidate mask is shared.  ``excluded`` is *only this
    player's* private failed-code mask.  The opponent's private code is not
    an input and is consequently never leaked.  Opponent proposals are
    evaluated from the public distribution, which is a conservative Bayesian
    prior until the next DG2 layer models the opponent's policy-conditioned
    hidden exclusion explicitly.
    """

    def __init__(self, candidates, questions, *, node_budget: int) -> None:
        self.candidates = candidates
        self.questions = questions
        self.node_budget = node_budget
        self.nodes = 0
        self.memo: dict[tuple, float] = {}

    def _tick(self) -> None:
        self.nodes += 1
        if self.nodes > self.node_budget:
            raise _BudgetExceeded()

    @staticmethod
    def _bits(mask: int):
        while mask:
            low = mask & -mask
            yield low.bit_length() - 1
            mask ^= low

    def _informative(self, public: int, asked: int):
        return [
            (i, q) for i, q in enumerate(self.questions)
            if not (asked & (1 << i)) and sum(bool(c & public) for c in q.classes) > 1
        ]

    def value(self, public: int, excluded: int, mine_attempts: int,
              opp_attempts: int, mine_to_move: bool, asked: int) -> float:
        if mine_attempts == 0:
            return 0.0
        if opp_attempts == 0:
            return 1.0
        excluded &= public
        mine = public & ~excluded
        if not mine:
            return 0.0
        key = (public, excluded, mine_attempts, opp_attempts, mine_to_move, asked)
        cached = self.memo.get(key)
        if cached is not None:
            return cached
        self._tick()
        value = self._mine_turn(public, excluded, mine_attempts, opp_attempts, asked) if mine_to_move else self._opp_turn(public, excluded, mine_attempts, opp_attempts, asked)
        self.memo[key] = value
        return value

    def guess_value(self, public: int, excluded: int, mine_attempts: int,
                    opp_attempts: int, asked: int, guess: int) -> float:
        mine = public & ~excluded
        k = mine.bit_count()
        if not k:
            return 0.0
        if k == 1:
            return 1.0
        return 1 / k + (1 - 1 / k) * self.value(
            public, excluded | (1 << guess), mine_attempts - 1,
            opp_attempts, False, asked,
        )

    def best_guess(self, public: int, excluded: int, mine_attempts: int,
                   opp_attempts: int, asked: int) -> tuple[float, list[int]]:
        mine = public & ~excluded
        values = [(self.guess_value(public, excluded, mine_attempts, opp_attempts, asked, g), g)
                  for g in self._bits(mine)]
        best = max(v for v, _ in values)
        return best, [g for v, g in values if abs(v - best) < 1e-12]

    def _mine_after_question(self, public: int, excluded: int, mine_attempts: int,
                             opp_attempts: int, asked: int) -> float:
        wait = self.value(public, excluded, mine_attempts, opp_attempts, False, asked)
        if not mine_attempts:
            return wait
        guess, _ = self.best_guess(public, excluded, mine_attempts, opp_attempts, asked)
        return max(wait, guess)

    def _mine_turn(self, public, excluded, mine_attempts, opp_attempts, asked) -> float:
        direct, _ = self.best_guess(public, excluded, mine_attempts, opp_attempts, asked)
        mine = public & ~excluded
        options = [direct]
        for qi, q in self._informative(public, asked):
            total = 0.0
            for cls in q.classes:
                sub = cls & mine
                if sub:
                    total += sub.bit_count() / mine.bit_count() * self._mine_after_question(
                        cls & public, excluded, mine_attempts, opp_attempts, asked | (1 << qi),
                    )
            options.append(total)
        return max(options)

    def _opp_guess_value(self, public, excluded, mine_attempts, opp_attempts, asked) -> float:
        # The opponent knows a private miss of its own, if any, but that miss
        # is intentionally not observable here.  From this player's legal
        # information set, its immediate hit probability is therefore 1/N.
        n = public.bit_count()
        if n <= 1:
            return 0.0
        return (1 - 1 / n) * self.value(public, excluded, mine_attempts, opp_attempts - 1, True, asked)

    def _opp_turn(self, public, excluded, mine_attempts, opp_attempts, asked) -> float:
        mine = public & ~excluded
        options = [self._opp_guess_value(public, excluded, mine_attempts, opp_attempts, asked)]
        for qi, q in self._informative(public, asked):
            total = 0.0
            for cls in q.classes:
                sub = cls & mine
                if sub:
                    child = cls & public
                    wait = self.value(child, excluded, mine_attempts, opp_attempts, True, asked | (1 << qi))
                    guess = self._opp_guess_value(child, excluded, mine_attempts, opp_attempts, asked | (1 << qi))
                    total += sub.bit_count() / mine.bit_count() * min(wait, guess)
            options.append(total)
        return min(options)


class DG2Policy:
    """A seeded policy suitable for the referee protocol in ``selfplay``.

    Exact search is attempted only for a bounded public universe.  Outside
    that range DG2 asks the public question with the most balanced reachable
    partition; it never makes an early, threshold-based proposal.
    """

    def __init__(self, *, seed: int = 0, exact_n_max: int = 12, node_budget: int = 80_000) -> None:
        self.rng = random.Random(seed)
        self.exact_n_max = exact_n_max
        self.node_budget = node_budget

    def _broad_question(self, solver: DigitcodeSolver, clue: Clue) -> dict | None:
        """Race-aware question choice before the exact endgame.

        ``enumerate_all_questions`` exposes outcome counts capped at three;
        treating those as branch sizes made the former DG2 fallback nearly
        blind on broad boards.  Here every candidate question is re-counted
        with an independent, much higher cap.  We minimize the expected
        surviving fraction (sum p²), and break close calls by preferring the
        question with more genuinely reachable answers.  Counts which hit
        the cap are deliberately treated as large rather than as exact.
        """
        cap = 200
        scored: list[tuple[float, int, dict]] = []
        for question in solver.enumerate_all_questions(clue):
            if len(question["outcomes"]) < 2:
                continue
            branches = []
            for outcome in question["outcomes"]:
                child_clue = solver._apply_answer_to_clue(clue, question, outcome["answer"])
                child = DigitcodeSolver()
                child.domains = {p: set(values) for p, values in solver.domains.items()}
                try:
                    child.propagate(child_clue)
                except ValueError:
                    continue
                n = child.count_solutions_capped(child_clue, cap=cap)
                if n:
                    branches.append((n, child, child_clue))
            if len(branches) < 2:
                continue
            counts = [branch[0] for branch in branches]
            total = sum(counts)
            concentration = sum((n / total) ** 2 for n in counts)
            # A saturated outcome is only a lower bound. Penalize it slightly
            # so a provably balanced split wins over an unknown huge branch.
            saturation = sum(n >= cap for n in counts) / len(counts)
            scored.append((concentration + .03 * saturation, -len(counts), question))
        if not scored:
            return None
        best = min(score[0] for score in scored)
        tied = [entry for entry in scored if abs(entry[0] - best) < 1e-12]
        best_answers = min(entry[1] for entry in tied)
        return self.rng.choice([entry[2] for entry in tied if entry[1] == best_answers])

    @staticmethod
    def _solver(clue: Clue) -> DigitcodeSolver:
        solver = DigitcodeSolver()
        solver.propagate(clue)
        return solver

    @staticmethod
    def _mask_for(candidates, failed: frozenset[Candidate]) -> int:
        return sum(1 << i for i, candidate in enumerate(candidates) if candidate in failed)

    def recommend(self, observation: Observation) -> DG2Recommendation:
        solver = self._solver(observation.clue)
        if observation.my_attempts <= 0:
            return DG2Recommendation(EndTurn(), 0.0, True)
        sols = solver.enumerate_solutions(observation.clue, limit=self.exact_n_max + 1)
        if not sols:
            return DG2Recommendation(EndTurn(), 0.0, False)
        if len(sols) > self.exact_n_max:
            # One question has already been consumed this turn.  DG2 may
            # either propose or pass now, never ask a second question.  The
            # broad-board policy deliberately preserves both attempts for a
            # later exact position instead of fabricating a threshold guess.
            if observation.after_question:
                return DG2Recommendation(EndTurn(), 0.5, False)
            question = self._broad_question(solver, observation.clue)
            if question is None:
                return DG2Recommendation(EndTurn(), 0.5, False)
            return DG2Recommendation(Ask(question), 0.5, False)

        candidates = [tuple(sol[p] for p in POSITIONS) for sol in sols]
        _, questions = universe_from_solutions(sols, observation.clue)
        planner = _Planner(candidates, questions, node_budget=self.node_budget)
        public = (1 << len(candidates)) - 1
        excluded = self._mask_for(candidates, observation.my_failed_guesses)
        asked = 0  # clues already entered were excluded by universe_from_solutions
        try:
            if observation.after_question:
                wait = planner.value(public, excluded, observation.my_attempts, observation.opponent_attempts, False, asked)
                guess_value, guesses = planner.best_guess(public, excluded, observation.my_attempts, observation.opponent_attempts, asked)
                if guess_value >= wait:
                    return DG2Recommendation(Guess(candidates[self.rng.choice(guesses)]), guess_value, True)
                return DG2Recommendation(EndTurn(), wait, True)

            direct, guesses = planner.best_guess(public, excluded, observation.my_attempts, observation.opponent_attempts, asked)
            mine = public & ~excluded
            options: list[tuple[float, Optional[int]]] = [(direct, None)]
            for qi, q in planner._informative(public, asked):
                value = sum(
                    (cls & mine).bit_count() / mine.bit_count() * planner._mine_after_question(
                        cls & public, excluded, observation.my_attempts, observation.opponent_attempts, 1 << qi,
                    ) for cls in q.classes if cls & mine
                )
                options.append((value, qi))
            best = max(value for value, _ in options)
            choices = [qi for value, qi in options if abs(value - best) < 1e-12]
            chosen = self.rng.choice(choices)
            if chosen is None:
                return DG2Recommendation(Guess(candidates[self.rng.choice(guesses)]), best, True)
            question = next(q for qi, q in planner._informative(public, asked) if qi == chosen)
            raw = next(q for q in solver.enumerate_all_questions(observation.clue) if q["label"] == question.label)
            return DG2Recommendation(Ask(raw), best, True)
        except _BudgetExceeded:
            return DG2Recommendation(EndTurn(), 0.5, False)

    def choose(self, observation: Observation) -> Action:
        return self.recommend(observation).action
