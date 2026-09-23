from __future__ import annotations

import sys
import threading
import traceback
from typing import FrozenSet

from PySide6.QtCore import QThread, Signal

from ..endgame import PHASE_MY_TURN
from ..game_state import GameState
from ..solver import Cancelled, Clue


class EndgameWorker(QThread):
    """Runs `GameState.build_endgame_from(...)` (the exact endgame search,
    up to endgame.ENDGAME_TIME_BUDGET_S) on a background thread, after the
    fast payload is already on screen. Same cooperative-cancellation
    contract as SolveWorker: MainWindow cancels it and moves on without
    waiting as soon as the board changes."""

    finished_ok = Signal(object, int)  # result dict, or None above ENDGAME_N_MAX
    failed = Signal(str, int)

    def __init__(
        self, clue: Clue, a_me: int, a_opp: int, excluded: FrozenSet, opp_fail_pool_size: int,
        generation: int, phase: str = PHASE_MY_TURN, parent=None,
    ) -> None:
        super().__init__(parent)
        self._clue = clue
        self._a_me = a_me
        self._a_opp = a_opp
        self._excluded = excluded
        self._opp_fail_pool_size = opp_fail_pool_size
        self.generation = generation
        self._phase = phase
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        self._cancel_event.set()

    def run(self) -> None:
        if self._cancel_event.is_set():
            return
        try:
            result = GameState.build_endgame_from(
                self._clue, self._a_me, self._a_opp, self._excluded, self._opp_fail_pool_size,
                should_cancel=self._cancel_event.is_set, phase=self._phase,
            )
        except Cancelled:
            return
        except Exception as e:
            traceback.print_exc(file=sys.stderr)
            self.failed.emit(str(e), self.generation)
            return
        self.finished_ok.emit(result, self.generation)
