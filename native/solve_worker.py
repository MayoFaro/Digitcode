"""Compute the display payload in an isolated process."""
from ..game_state import GameState
from .process_worker import ProcessWorker


def _compute_payload(args, should_cancel, publish):
    return GameState.build_payload_from(*args, should_cancel=should_cancel)


class SolveWorker(ProcessWorker):
    def __init__(self, clue, a_me, a_opp, excluded, generation, parent=None):
        super().__init__(_compute_payload, (clue, a_me, a_opp, excluded), generation, parent)
