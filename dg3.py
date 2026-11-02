"""DG3: the released tempo endgame engine, used on both sides of a turn.

DG1 only calls the strong, tempo-aware, opponent-exclusion-aware exact
engine (``endgame_tempo.TempoEndgameSolver``, exact up to N <= 20) *after*
its question is answered.  Before asking, it falls back to the much older
``strategy.py`` model: truly exact only up to N <= 5, beam-limited to
N <= 12, and -- even there -- blind to the opponent's own already-failed
guess (``strategy._exact_value`` always simulates the opponent's guess with
a fresh ``frozenset()``, by design; only ``endgame.py``'s
``opp_hit_probability`` tracks that exclusion).

DG3 asks a narrow question: can the stronger engine simply decide BOTH
turn phases, every time the public board is small enough for it to run?
Above that size it defers to DG1's own pre-question model verbatim, so DG3
is never worse than DG1 on a wide board -- only better once the board
narrows into the engine's exact range, which every game eventually
reaches on the way to its finish.

See docs/superpowers/specs/2026-11-02-dg3-engine-design.md.
"""
from __future__ import annotations

from .endgame_tempo import ENDGAME_N_MAX, PHASE_MY_POST_QUESTION, PHASE_MY_TURN, evaluate_endgame
from .selfplay import Action, Ask, EndTurn, Guess, Observation, _solver_for, race_strategy_action
from .solver import Clue, DigitcodeSolver

# Measured directly against this engine (scratch benchmark, 2026-11-02, 24
# random mid-game boards at N 14-20): worst case 8.0 s at N=19, typically
# well under 1 s. 10 s leaves comfortable headroom without being
# open-ended -- a decision that still overruns it degrades to DG1's own
# model below, never to a crash or an unbounded wait.
ENDGAME_TIME_BUDGET_S = 10.0


def _null_question_action(qtype: str, label: str, entry: dict) -> Ask:
    """The one concrete action for a tempo "null" question: ask any still-
    unasked question whose answer the current public pool already
    determines, spending none of the shared reserve's information but
    preserving tempo parity (see the endgame_tempo.py module docstring).

    ``entry`` is the structured clue entry ``endgame_tempo.question_entry``
    already computed for this question.  Reusing it is simpler and more
    robust than re-deriving the answer string from the board, and -- unlike
    a label lookup through ``solver.enumerate_all_questions`` -- doesn't
    depend on that method covering the null case: it silently drops
    already-determined segment questions (solver.py), the most common null
    type on a mid-sized board.
    """
    if qtype in ("row", "col"):
        answer = str(entry["value"])
    elif qtype == "parity":
        answer = entry["value"]
    elif qtype == "seg":
        answer = "on" if entry["value"] else "off"
    elif qtype == "cmp":
        answer = f"{entry['left']}{entry['rel']}{entry['right']}"
    else:  # pragma: no cover - the engine only emits the five types above
        raise ValueError(f"Type de question inconnu : {qtype}")
    return Ask({"qtype": qtype, "label": label, "outcomes": [{"answer": answer}]})


def _question_action(solver: DigitcodeSolver, clue: Clue, formatted_question: dict) -> Action | None:
    """The real action for one of ``evaluate_endgame``'s ranked questions.

    A null question is built directly; an informative one is looked up by
    label among the solver's own questions, the same mechanism DG1 already
    relies on for its own pre-question choice -- sound here because
    ``enumerate_all_questions`` only ever drops the already-determined
    (null) case, handled separately above.
    """
    if formatted_question["is_null"]:
        return _null_question_action(
            formatted_question["qtype"], formatted_question["label"], formatted_question["entry"],
        )
    label = formatted_question["label"]
    question = next((q for q in solver.enumerate_all_questions(clue) if q["label"] == label), None)
    return Ask(question) if question is not None else None


class DG3Policy:
    """Plays the tempo endgame engine whenever the public board fits it,
    before asking a question as well as after; defers to DG1's released
    pre-question model otherwise.
    """

    def __init__(
        self, *, time_budget_s: float = 0.25,
        endgame_time_budget_s: float = ENDGAME_TIME_BUDGET_S, endgame_n_max: int = ENDGAME_N_MAX,
    ) -> None:
        self.time_budget_s = time_budget_s
        self.endgame_time_budget_s = endgame_time_budget_s
        self.endgame_n_max = endgame_n_max

    @staticmethod
    def _solver(clue: Clue) -> DigitcodeSolver:
        return _solver_for(clue)

    def _endgame(self, solver: DigitcodeSolver, observation: Observation, phase: str) -> dict | None:
        return evaluate_endgame(
            solver, observation.clue, observation.my_attempts, observation.opponent_attempts,
            observation.my_failed_guesses, phase=phase,
            n_max=self.endgame_n_max, time_budget_s=self.endgame_time_budget_s,
        )

    def choose(self, observation: Observation) -> Action:
        solver = self._solver(observation.clue)
        if observation.my_attempts == 0:
            return EndTurn()

        if observation.after_question:
            result = self._endgame(solver, observation, PHASE_MY_POST_QUESTION)
            if result and result.get("complete") and result["decision"] == "guess_now":
                code = tuple(int(c) for c in result["guess_now"]["code"].replace(" ", ""))
                return Guess(code)
            return EndTurn()

        result = self._endgame(solver, observation, PHASE_MY_TURN)
        if result and result.get("complete"):
            if result["decision"] == "guess_now":
                code = tuple(int(c) for c in result["guess_now"]["code"].replace(" ", ""))
                return Guess(code)
            if result.get("best_question") is not None:
                action = _question_action(solver, observation.clue, result["best_question"])
                if action is not None:
                    return action

        return race_strategy_action(
            solver, observation.clue, observation.my_attempts, observation.opponent_attempts,
            observation.my_failed_guesses, time_budget_s=self.time_budget_s,
        )
