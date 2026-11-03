"""Deterministic, rules-owning matches used to benchmark game engines.

This first version deliberately adapts the shipped strategy as ``DG1``.  It
does not share a :class:`GameState` with either player: public clues are held
by the referee and each player receives only its own failed guesses.  DG2
will implement the same small policy interface in this module.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from .endgame import Candidate, code_consistent, code_to_string
from .endgame_tempo import PHASE_MY_POST_QUESTION, evaluate_endgame
from .mapping import POSITIONS
from .solver import Clue, DigitcodeSolver
from .strategy import evaluate_race_strategy

Player = Literal[0, 1]


@dataclass(frozen=True)
class Ask:
    question: dict


@dataclass(frozen=True)
class Guess:
    code: Candidate


@dataclass(frozen=True)
class EndTurn:
    pass


Action = Ask | Guess | EndTurn


class Policy(Protocol):
    def choose(self, observation: "Observation") -> Action: ...


@dataclass(frozen=True)
class Observation:
    """Information visible to exactly one player at a decision point."""
    clue: Clue
    my_attempts: int
    opponent_attempts: int
    my_failed_guesses: frozenset[Candidate]
    after_question: bool = False


@dataclass(frozen=True)
class MatchEvent:
    player: Player
    kind: str
    detail: str


@dataclass(frozen=True)
class MatchResult:
    secret: Candidate
    starter: Player
    winner: Player
    events: tuple[MatchEvent, ...]


def _copy_clue(clue: Clue) -> Clue:
    return Clue(
        row_totals=dict(clue.row_totals), col_totals=dict(clue.col_totals),
        parity=dict(clue.parity), comparisons=list(clue.comparisons),
        segment_state=dict(clue.segment_state), max_two=clue.max_two,
        forbid_equal_adjacent=clue.forbid_equal_adjacent,
    )


def _solver_for(clue: Clue) -> DigitcodeSolver:
    solver = DigitcodeSolver()
    solver.propagate(clue)
    return solver


def _first_candidate(solver: DigitcodeSolver, clue: Clue, excluded: frozenset[Candidate]) -> Candidate:
    sols = solver.enumerate_solutions(clue, limit=1, excluded=excluded)
    if not sols:
        raise RuntimeError("Aucun candidat public à proposer")
    sol = sols[0]
    return tuple(sol[p] for p in POSITIONS)


def race_strategy_action(
    solver: DigitcodeSolver, clue: Clue, my_attempts: int, opponent_attempts: int,
    my_failed_guesses: frozenset[Candidate], *, time_budget_s: float,
) -> Action:
    """DG1's released pre-question model: exact search only up to N <= 5, a
    beam-limited race search up to N <= 12, a 1-ply heuristic above that.

    Shared by ``DG1Policy`` and, as its fallback on boards too wide for the
    stronger tempo endgame engine, by DG3 (see ``dg3.py``).
    """
    result = evaluate_race_strategy(
        solver, clue, my_attempts, opponent_attempts, my_failed_guesses, time_budget_s=time_budget_s,
    )
    if result["guess_now"]:
        return Guess(_first_candidate(solver, clue, my_failed_guesses))
    label = result.get("best_question", {}).get("label") if result.get("best_question") else None
    if label is not None:
        question = next((q for q in solver.enumerate_all_questions(clue) if q["label"] == label), None)
        if question is not None:
            return Ask(question)
    return Guess(_first_candidate(solver, clue, my_failed_guesses))


class DG1Policy:
    """Adapter around the current strategy and endgame engines.

    Before a question it uses the released race strategy.  The old strategy
    does not expose its post-question action above the endgame threshold, so
    DG1 ends that turn there; at <= 20 public candidates it delegates to the
    released tempo endgame model, which does expose that action.  This is an
    intentional, documented baseline rather than a hidden improvement.
    """

    def __init__(self, *, time_budget_s: float = 0.25) -> None:
        self.time_budget_s = time_budget_s

    @staticmethod
    def _solver(clue: Clue) -> DigitcodeSolver:
        return _solver_for(clue)

    def choose(self, observation: Observation) -> Action:
        solver = self._solver(observation.clue)
        if observation.my_attempts == 0:
            return EndTurn()

        if observation.after_question:
            result = evaluate_endgame(
                solver, observation.clue, observation.my_attempts,
                observation.opponent_attempts, observation.my_failed_guesses,
                phase=PHASE_MY_POST_QUESTION, time_budget_s=self.time_budget_s,
            )
            if result and result.get("complete") and result["decision"] == "guess_now":
                code = tuple(int(c) for c in result["guess_now"]["code"].replace(" ", ""))
                return Guess(code)
            return EndTurn()

        return race_strategy_action(
            solver, observation.clue, observation.my_attempts, observation.opponent_attempts,
            observation.my_failed_guesses, time_budget_s=self.time_budget_s,
        )


def _answer_question(question: dict, clue: Clue, secret: Candidate) -> tuple[str, Clue]:
    """Let the referee answer a public question without revealing ``secret``."""
    solver = DigitcodeSolver()
    for outcome in question["outcomes"]:
        child = solver._apply_answer_to_clue(clue, question, outcome["answer"])
        if code_consistent(secret, child):
            return outcome["answer"], child
    raise RuntimeError("Question légale sans réponse pour le code secret")


def play_match(
    secret: Candidate, policy_zero: Policy, policy_one: Policy, *, starter: Player = 0,
    initial_clue: Clue | None = None, max_turns: int = 200,
) -> MatchResult:
    """Play a complete match under the public/private referee protocol.

    ``secret`` is held solely by the referee.  A second failed guess is an
    immediate loss, per the game rule, so the opponent wins without another
    simulated question.  The returned immutable event list is a replay log.
    """
    clue = _copy_clue(initial_clue or Clue())
    if not code_consistent(secret, clue):
        raise ValueError("Le code secret doit respecter les indices initiaux et les règles du jeu.")
    policies = (policy_zero, policy_one)
    attempts = [2, 2]
    failed: list[set[Candidate]] = [set(), set()]
    events: list[MatchEvent] = []
    player: Player = starter

    for _ in range(max_turns):
        other: Player = 1 - player  # type: ignore[assignment]
        observation = Observation(clue, attempts[player], attempts[other], frozenset(failed[player]))
        action = policies[player].choose(observation)
        if isinstance(action, Ask):
            answer, clue = _answer_question(action.question, clue, secret)
            events.append(MatchEvent(player, "ask", f"{action.question['label']} → {answer}"))
            observation = Observation(clue, attempts[player], attempts[other], frozenset(failed[player]), True)
            action = policies[player].choose(observation)

        if isinstance(action, Guess):
            if action.code == secret:
                events.append(MatchEvent(player, "guess", f"{code_to_string(action.code)} → correct"))
                return MatchResult(secret, starter, player, tuple(events))
            attempts[player] -= 1
            failed[player].add(action.code)
            # The attempted code is private after a miss.  In particular do
            # not put it in this public replay stream: future policies will
            # receive the same event log as their opponent, not the referee's
            # hidden state.
            events.append(MatchEvent(player, "guess", "proposition ratée"))
            if attempts[player] == 0:
                events.append(MatchEvent(other, "win", "deux essais adverses ratés"))
                return MatchResult(secret, starter, other, tuple(events))
        elif isinstance(action, EndTurn):
            events.append(MatchEvent(player, "end_turn", "sans proposition"))
        else:  # pragma: no cover - protects future engine adapters
            raise TypeError(f"Action inconnue : {action!r}")
        player = other
    raise RuntimeError(f"Match non terminé après {max_turns} tours")


def play_dg1_selfplay(
    secret: Candidate, *, starter: Player = 0, initial_clue: Clue | None = None,
    time_budget_s: float = 0.25, max_turns: int = 200,
) -> MatchResult:
    """Compatibility wrapper for a DG1-vs-DG1 match."""
    return play_match(
        secret, DG1Policy(time_budget_s=time_budget_s), DG1Policy(time_budget_s=time_budget_s),
        starter=starter, initial_clue=initial_clue, max_turns=max_turns,
    )


def play_dg3_selfplay(
    secret: Candidate, *, starter: Player = 0, initial_clue: Clue | None = None,
    max_turns: int = 200,
) -> MatchResult:
    """DG3-vs-DG3 through the same referee; imported lazily to avoid a cycle."""
    from .dg3 import DG3Policy
    return play_match(
        secret, DG3Policy(), DG3Policy(),
        starter=starter, initial_clue=initial_clue, max_turns=max_turns,
    )


def play_dg2_selfplay(
    secret: Candidate, *, starter: Player = 0, initial_clue: Clue | None = None,
    seed_zero: int = 0, seed_one: int = 1, max_turns: int = 200,
) -> MatchResult:
    """DG2-vs-DG2 through the same referee; imported lazily to avoid a cycle."""
    from .dg2 import DG2Policy
    return play_match(
        secret, DG2Policy(seed=seed_zero), DG2Policy(seed=seed_one),
        starter=starter, initial_clue=initial_clue, max_turns=max_turns,
    )
