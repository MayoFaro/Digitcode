"""Unlimited, progressive exact endgame analysis in an isolated process."""
from ..endgame import PHASE_MY_TURN
from ..game_state import GameState
from .process_worker import ProcessWorker


def _compute_endgame(args, should_cancel, publish):
    clue, a_me, a_opp, excluded, pool_size, phase = args
    return GameState.build_endgame_from(
        clue, a_me, a_opp, excluded, pool_size, phase=phase,
        time_budget_s=None, should_cancel=should_cancel, on_progress=publish,
    )


class EndgameWorker(ProcessWorker):
    def __init__(self, clue, a_me, a_opp, excluded, opp_fail_pool_size, generation,
                 phase=PHASE_MY_TURN, parent=None):
        super().__init__(_compute_endgame,
                         (clue, a_me, a_opp, excluded, opp_fail_pool_size, phase), generation, parent)
