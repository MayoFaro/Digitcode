from digitcode.dg2 import DG2Policy
from digitcode.selfplay import DG1Policy, EndTurn, Guess, Observation, play_dg2_selfplay, play_match
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


def test_dg2_returns_a_legal_exact_endgame_action():
    policy = DG2Policy(seed=7)
    recommendation = policy.recommend(_n4_observation())
    assert recommendation.exact
    assert recommendation.value >= 0


def test_dg2_only_uses_private_failed_codes_from_its_observation():
    observation = _n4_observation(after_question=True)
    policy = DG2Policy(seed=1)
    action = policy.choose(observation)
    assert action.__class__.__name__ in {"Guess", "EndTurn"}
    if isinstance(action, Guess):
        assert action.code not in observation.my_failed_guesses


def test_dg2_never_asks_twice_in_the_same_turn_on_a_wide_board():
    action = DG2Policy(seed=2).choose(Observation(Clue(), 2, 2, frozenset(), after_question=True))
    assert isinstance(action, EndTurn)


def test_dg2_plays_a_complete_match_through_the_neutral_referee():
    observation = _n4_observation()
    solver = DigitcodeSolver()
    solver.propagate(observation.clue)
    secret = tuple(solver.enumerate_solutions(observation.clue, limit=1)[0][p] for p in "TUVWXY")
    result = play_dg2_selfplay(secret, initial_clue=observation.clue, seed_zero=4, seed_one=9)
    assert result.winner in (0, 1)
    assert any(event.kind == "guess" for event in result.events)
    assert all("ratée" not in event.detail or len(event.detail.split()) == 2 for event in result.events)


class _TwoWrongGuesses:
    def __init__(self, codes):
        self.codes = iter(codes)
        self.observations = []

    def choose(self, observation):
        self.observations.append(observation)
        return Guess(next(self.codes))


class _Pass:
    def choose(self, observation):
        return EndTurn()


def test_referee_keeps_failed_codes_private_and_second_failure_is_terminal():
    observation = _n4_observation()
    solver = DigitcodeSolver()
    solver.propagate(observation.clue)
    codes = [tuple(sol[p] for p in "TUVWXY") for sol in solver.enumerate_solutions(observation.clue, limit=4)]
    # The final candidate is the secret; player 0 deliberately loses two
    # private attempts. Player 1 must win without being told either code.
    policy = _TwoWrongGuesses(codes[:2])
    result = play_match(codes[-1], policy, _Pass(), initial_clue=observation.clue)
    assert result.winner == 1
    misses = [event for event in result.events if event.kind == "guess"]
    assert [event.detail for event in misses] == ["proposition ratée", "proposition ratée"]
    assert policy.observations[1].my_failed_guesses == frozenset({codes[0]})


def test_dg1_and_dg2_share_the_same_referee_contract():
    observation = _n4_observation()
    solver = DigitcodeSolver()
    solver.propagate(observation.clue)
    secret = tuple(solver.enumerate_solutions(observation.clue, limit=1)[0][p] for p in "TUVWXY")
    result = play_match(secret, DG1Policy(time_budget_s=1), DG2Policy(seed=3), initial_clue=observation.clue)
    assert result.winner in (0, 1)
