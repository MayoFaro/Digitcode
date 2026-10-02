"""Unlimited progressive screening in an isolated process."""
from ..endgame import PHASE_MY_TURN
from ..pre_endgame import evaluate_pre_endgame
from .process_worker import ProcessWorker


def _compute_pre_endgame(args, should_cancel, publish):
    return evaluate_pre_endgame(*args, time_budget_s=None,
                                should_cancel=should_cancel, on_progress=publish)


class PreEndgameWorker(ProcessWorker):
    def __init__(self, clue, a_me, a_opp, excluded, opp_fail_pool_size, generation,
                 phase=PHASE_MY_TURN, parent=None):
        super().__init__(_compute_pre_endgame,
                         (clue, a_me, a_opp, excluded, opp_fail_pool_size), generation, parent)
