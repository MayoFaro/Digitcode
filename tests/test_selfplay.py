from digitcode.endgame import code_consistent
from digitcode.selfplay import play_dg1_selfplay
from digitcode.solver import Clue, DigitcodeSolver


def _small_public_position():
    clue = Clue(
        row_totals={"K": 6, "S": 1}, col_totals={"H": 3, "C": 3, "E": 1},
        parity={"T": "Pair", "W": "Pair", "Y": "Pair", "X": "Impair"},
    )
    solver = DigitcodeSolver()
    solver.propagate(clue)
    candidates = solver.enumerate_solutions(clue, limit=21)
    # The simulator is intended for arbitrary boards; this fixture merely
    # keeps the DG1 endgame test fast and fully deterministic.
    assert 1 < len(candidates) <= 20
    return clue, tuple(candidates[0][p] for p in "TUVWXY")


def test_dg1_can_play_a_complete_replayable_game_against_itself():
    clue, secret = _small_public_position()
    result = play_dg1_selfplay(secret, starter=0, initial_clue=clue, time_budget_s=1)
    assert result.winner in (0, 1)
    assert result.events
    assert any(event.kind == "guess" for event in result.events)
    assert code_consistent(secret, clue)
