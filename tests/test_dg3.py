from digitcode.dg3 import DG3Policy, _null_question_action
from digitcode.endgame_tempo import PHASE_MY_TURN, evaluate_endgame
from digitcode.selfplay import DG1Policy, EndTurn, Guess, Observation, play_dg3_selfplay, play_match
from digitcode.solver import Clue, DigitcodeSolver


def _n4_observation(*, attempts=2, opponent_attempts=2, after_question=False):
    clue = Clue(
        row_totals={"K": 6, "S": 1}, col_totals={"H": 3, "C": 3, "E": 1},
        parity={"T": "Pair", "W": "Pair", "Y": "Pair", "X": "Impair"},
    )
    solver = DigitcodeSolver()
    solver.propagate(clue)
    assert len(solver.enumerate_solutions(clue, limit=10)) == 4
    return Observation(clue, attempts, opponent_attempts, frozenset(), after_question)


def test_dg3_follows_the_tempo_engine_on_a_small_board():
    observation = _n4_observation()
    solver = DigitcodeSolver()
    solver.propagate(observation.clue)
    expected = evaluate_endgame(
        solver, observation.clue, observation.my_attempts, observation.opponent_attempts,
        observation.my_failed_guesses, phase=PHASE_MY_TURN,
    )
    assert expected["complete"]
    action = DG3Policy().choose(observation)
    if expected["decision"] == "guess_now":
        assert isinstance(action, Guess)
        assert "".join(map(str, action.code)) == expected["guess_now"]["code"].replace(" ", "")
    else:
        assert action.__class__.__name__ == "Ask"
        assert action.question["label"] == expected["best_question"]["label"]


def test_dg3_only_uses_private_failed_codes_from_its_observation():
    observation = _n4_observation(after_question=True)
    action = DG3Policy().choose(observation)
    assert action.__class__.__name__ in {"Guess", "EndTurn"}
    if isinstance(action, Guess):
        assert action.code not in observation.my_failed_guesses


def test_dg3_never_asks_twice_in_the_same_turn_on_a_wide_board():
    action = DG3Policy().choose(Observation(Clue(), 2, 2, frozenset(), after_question=True))
    assert isinstance(action, EndTurn)


def test_dg3_falls_back_to_dg1s_model_on_a_wide_board():
    observation = Observation(Clue(), 2, 2, frozenset(), after_question=False)
    solver = DigitcodeSolver()
    solver.propagate(observation.clue)
    assert DG3Policy().choose(observation) == DG1Policy(time_budget_s=0.25).choose(observation)


def test_dg3_plays_a_complete_match_through_the_neutral_referee():
    observation = _n4_observation()
    solver = DigitcodeSolver()
    solver.propagate(observation.clue)
    secret = tuple(solver.enumerate_solutions(observation.clue, limit=1)[0][p] for p in "TUVWXY")
    result = play_dg3_selfplay(secret, initial_clue=observation.clue)
    assert result.winner in (0, 1)
    assert any(event.kind == "guess" for event in result.events)
    assert all("ratée" not in event.detail or len(event.detail.split()) == 2 for event in result.events)


def test_dg1_and_dg3_share_the_same_referee_contract():
    observation = _n4_observation()
    solver = DigitcodeSolver()
    solver.propagate(observation.clue)
    secret = tuple(solver.enumerate_solutions(observation.clue, limit=1)[0][p] for p in "TUVWXY")
    result = play_match(secret, DG1Policy(time_budget_s=1), DG3Policy(), initial_clue=observation.clue)
    assert result.winner in (0, 1)


def test_null_question_action_round_trips_through_apply_answer_to_clue():
    solver = DigitcodeSolver()
    clue = Clue()

    seg = _null_question_action("seg", "T.a on/off ?", {"clue_type": "segment", "pos": "T", "seg": "a", "value": True})
    child = solver._apply_answer_to_clue(clue, seg.question, seg.question["outcomes"][0]["answer"], 0)
    assert child.segment_state[("T", "a")] is True

    parity = _null_question_action("parity", "T pair/impair ?", {"clue_type": "parity", "pos": "T", "value": "Pair"})
    child = solver._apply_answer_to_clue(clue, parity.question, parity.question["outcomes"][0]["answer"], 0)
    assert child.parity["T"] == "Pair"

    row = _null_question_action("row", "Combien en ligne K ?", {"clue_type": "row_total", "row": "K", "value": 7})
    child = solver._apply_answer_to_clue(clue, row.question, row.question["outcomes"][0]["answer"], 0)
    assert child.row_totals["K"] == 7

    col = _null_question_action("col", "Combien en colonne H ?", {"clue_type": "col_total", "col": "H", "value": 3})
    child = solver._apply_answer_to_clue(clue, col.question, col.question["outcomes"][0]["answer"], 0)
    assert child.col_totals["H"] == 3

    comparison = _null_question_action(
        "cmp", "Qui est plus grand, T ou U ?", {"clue_type": "comparison", "left": "T", "rel": ">", "right": "U"},
    )
    child = solver._apply_answer_to_clue(clue, comparison.question, comparison.question["outcomes"][0]["answer"], 0)
    assert ("T", ">", "U") in child.comparisons
