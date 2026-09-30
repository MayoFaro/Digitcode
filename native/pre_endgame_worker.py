"""Cancellable progressive screening, using the same snapshot lifecycle as endgame."""
import sys
import traceback

from PySide6.QtCore import Signal

from .endgame_worker import EndgameWorker
from ..pre_endgame import evaluate_pre_endgame
from ..solver import Cancelled


class PreEndgameWorker(EndgameWorker):
    progress = Signal(object, int)

    def run(self):
        if self._cancel_event.is_set():
            return
        try:
            result = evaluate_pre_endgame(
                self._clue, self._a_me, self._a_opp, self._excluded, self._opp_fail_pool_size,
                should_cancel=self._cancel_event.is_set,
                on_progress=lambda result: self.progress.emit(result, self.generation),
            )
        except Cancelled:
            return
        except Exception as exc:
            traceback.print_exc(file=sys.stderr)
            self.failed.emit(str(exc), self.generation)
            return
        if not self._cancel_event.is_set():
            self.finished_ok.emit(result, self.generation)
