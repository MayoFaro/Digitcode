from __future__ import annotations

import sys
import threading
import traceback
from typing import FrozenSet

from PySide6.QtCore import QThread, Signal

from ..game_state import GameState
from ..solver import Cancelled, Clue


class SolveWorker(QThread):
    """Computes `GameState.build_payload_from(...)` on a background thread
    so the native UI's event loop keeps processing clicks while the
    expensive count / race-strategy / per-question annotation pipeline
    runs on a fixed `Clue` snapshot.

    Cooperatively cancellable: `MainWindow` calls `cancel()` and starts a
    fresh worker as soon as a newer move arrives, instead of waiting for
    this one to finish. That's always safe -- an extra clue can only
    shrink the remaining solution space, so a stale in-flight computation
    is never worth letting run to completion once a newer one has been
    requested."""

    finished_ok = Signal(dict, int)
    failed = Signal(str, int)

    def __init__(
        self, clue: Clue, a_me: int, a_opp: int, excluded: FrozenSet, generation: int, parent=None,
    ) -> None:
        super().__init__(parent)
        self._clue = clue
        self._a_me = a_me
        self._a_opp = a_opp
        self._excluded = excluded
        self.generation = generation
        self._cancel_event = threading.Event()

    def cancel(self) -> None:
        """Ask the computation to abort at its next cooperative checkpoint.
        Does not block -- the caller starts the next worker immediately
        rather than waiting for this one to actually stop."""
        self._cancel_event.set()

    def run(self) -> None:
        try:
            payload = GameState.build_payload_from(
                self._clue, self._a_me, self._a_opp, self._excluded,
                should_cancel=self._cancel_event.is_set,
            )
        except Cancelled:
            return
        except Exception as e:
            traceback.print_exc(file=sys.stderr)
            self.failed.emit(str(e), self.generation)
            return
        self.finished_ok.emit(payload, self.generation)
