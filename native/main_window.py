from __future__ import annotations

import sys
from typing import Callable

from PySide6.QtCore import QEvent, QThread, Qt
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..endgame import ENDGAME_N_MAX
from ..game_state import GameState, clone_clue
from .endgame_worker import EndgameWorker
from .panels.chiffres_panel import ChiffresPanel
from .panels.comparaisons_panel import ComparaisonsPanel
from .panels.endgame_format import ENDGAME_PENDING_TEXT, format_endgame
from .panels.solutions_panel import SolutionsPanel
from .solve_worker import SolveWorker

WINDOW_WIDTH = 380

OPACITY_STEP = 0.05
OPACITY_MIN = 0.2
OPACITY_MAX = 1.0

# Order matches the spec's volet 1/2/3 mapping of the web layout's
# col-sums / col-digits / col-advice blocks.
TAB_TITLES = ["Chiffres", "Comparaisons", "Solutions"]


class MainWindow(QMainWindow):
    def __init__(self, game_state: GameState | None = None) -> None:
        super().__init__()
        self.game_state = game_state or GameState()
        self._generation = 0
        self._worker: SolveWorker | None = None
        # Last full payload rendered (from _run or a finished worker), kept
        # so _mutate can synthesize an immediate "quick" render (see
        # build_quick_payload_from) by overlaying fresh clue-derived fields
        # on top of it, without needing to wait for the next full payload
        # just to show a chip as newly set.
        self._last_payload: dict | None = None
        # Workers superseded by a newer move: cancelled but not necessarily
        # stopped yet. Kept alive here on purpose -- PySide6 does not keep a
        # started QThread alive on its own once its last Python reference is
        # dropped, so simply reassigning self._worker to the next worker
        # destroys the previous one's C++ object out from under its still-
        # running thread ("QThread: Destroyed while thread is still
        # running", observed crash, not a theoretical concern). Each entry
        # removes itself via _cleanup_worker once its own `finished` fires.
        self._retired_workers: list[QThread] = []
        # Exact endgame search (endgame.py), run on its own worker after each
        # full payload once the board is small enough. Its own generation
        # counter: bumped by _cancel_endgame, so a result from a superseded
        # search is ignored.
        self._endgame_worker: EndgameWorker | None = None
        self._endgame_generation = 0

        self.setWindowTitle("Digitcode")
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.setFixedWidth(WINDOW_WIDTH)

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        self.error_label = QLabel()
        self.error_label.setStyleSheet(
            "background: #fdd; color: #900; padding: 4px; border-radius: 4px;"
        )
        self.error_label.setWordWrap(True)
        self.error_label.hide()
        layout.addWidget(self.error_label)

        tabs_row = QHBoxLayout()
        self.tab_buttons: list[QPushButton] = []
        self.tab_group = QButtonGroup(self)
        self.tab_group.setExclusive(True)
        for i, title in enumerate(TAB_TITLES):
            btn = QPushButton(title)
            btn.setCheckable(True)
            self.tab_group.addButton(btn, i)
            tabs_row.addWidget(btn)
            self.tab_buttons.append(btn)
        self.tab_buttons[0].setChecked(True)
        self.tab_group.idClicked.connect(self._on_tab_clicked)
        layout.addLayout(tabs_row)

        self.solutions_label = QLabel()
        layout.addWidget(self.solutions_label)

        self.busy_label = QLabel("Calcul en cours…")
        self.busy_label.setStyleSheet("color: #888; font-style: italic;")
        self.busy_label.hide()
        layout.addWidget(self.busy_label)

        self.stack = QStackedWidget()
        layout.addWidget(self.stack)
        self.solutions_panel = SolutionsPanel(self.game_state, self._run)
        self.panels: list[QWidget] = [
            # Clue entry (row/col totals, comparisons, parity, segments) goes
            # through _mutate: instant, cancellable-background-recompute --
            # see _mutate/_schedule_refresh. Undo/reset/miss-tracking
            # (SolutionsPanel) stay on the original synchronous _run: rare
            # actions where a brief block is acceptable, deliberately left
            # out of scope (see the plan doc).
            ChiffresPanel(self.game_state, self._mutate),
            ComparaisonsPanel(self.game_state, self._mutate),
            self.solutions_panel,
        ]
        for panel in self.panels:
            self.stack.addWidget(panel)

        self._run(self.game_state.payload)

        # Application-wide filter, not a wheelEvent override: Qt delivers
        # wheel events to the widget under the cursor, so a handler on the
        # window itself would never fire when scrolling over a button/panel.
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, obj: QWidget, event: QEvent) -> bool:
        if event.type() == QEvent.Wheel and event.modifiers() & Qt.ControlModifier:
            step = OPACITY_STEP if event.angleDelta().y() > 0 else -OPACITY_STEP
            opacity = min(OPACITY_MAX, max(OPACITY_MIN, self.windowOpacity() + step))
            self.setWindowOpacity(opacity)
            return True
        return super().eventFilter(obj, event)

    def _on_tab_clicked(self, index: int) -> None:
        self.stack.setCurrentIndex(index)

    def _run(self, fn: Callable[[], dict]) -> None:
        """Apply one GameState mutation (or a plain payload() refresh) and
        re-render. Disables the window and forces a repaint first so the
        "busy" state is visible even though the call itself is synchronous
        (see the design spec: race-strategy computation can take up to
        ~1.5s, same budget the web app uses). Drains the event queue before
        re-enabling so clicks made while disabled are dropped, not replayed
        -- matching the web's runMutation, which deliberately ignores input
        that arrives while a request is in flight. try/finally guarantees
        the window can never be left permanently disabled, even if fn()
        raises something other than ValueError."""
        self.centralWidget().setEnabled(False)
        QApplication.processEvents()
        try:
            payload = fn()
        except ValueError as e:
            self.error_label.setText("⚠️ " + str(e))
            self.error_label.show()
            return
        except Exception as e:
            self.error_label.setText(f"⚠️ Erreur inattendue : {e}")
            self.error_label.show()
            raise
        else:
            self.error_label.hide()
            self._render(payload)
            self._schedule_endgame(payload)
        finally:
            QApplication.processEvents()
            self.centralWidget().setEnabled(True)

    def _render(self, payload: dict) -> None:
        self._last_payload = payload
        self.solutions_label.setText(f"Solutions restantes : {payload['n_solutions_total']}")
        for panel in self.panels:
            panel.refresh(payload)

    def _render_quick(self) -> None:
        """Immediate, cheap re-render right after a fast mutation: overlays
        the just-mutated clue's own fields (already-set totals/comparisons/
        parity/segments, plus a fresh domain snapshot -- all derivable from
        a bare propagate(), no solution counting/race strategy) on top of
        the last full payload. Without this, a click registers correctly
        (the clue IS mutated instantly) but nothing on screen shows it
        until the much slower background worker eventually delivers the
        full payload -- which reads as an unresponsive window even though
        it technically isn't one. See GameState.build_quick_payload_from."""
        quick = GameState.build_quick_payload_from(self.game_state.clue)
        merged = {**self._last_payload, **quick} if self._last_payload is not None else quick
        self._render(merged)

    def _mutate(self, fn_fast: Callable[[], None]) -> None:
        """Apply one fast GameState mutation (see GameState.apply_clue_fast /
        apply_clue_with_fallback_fast: validated via a cheap propagate()
        call, no display payload computed) synchronously -- it's cheap, so
        the window is never disabled for it -- render immediately so the
        move visibly registers on screen (_render_quick), then hand the
        expensive display recomputation (solution count, race strategy,
        reachable sums) to a cancellable background worker. This is the
        clue-entry counterpart of `_run`: unlike `_run`, the window stays
        interactive and visibly up to date the whole time, including while
        a previous worker is still winding down."""
        try:
            fn_fast()
        except ValueError as e:
            self.error_label.setText("⚠️ " + str(e))
            self.error_label.show()
            return
        self.error_label.hide()
        self._render_quick()
        self._schedule_refresh()

    def _schedule_refresh(self) -> None:
        """(Re)start the background computation of the display payload for
        the current game_state.clue. Cancels whatever the previous worker
        was doing without waiting for it to actually stop -- always safe,
        since an additional clue can only shrink the remaining solution
        space, so a stale in-flight computation is never worth blocking on
        (see native/solve_worker.py and the plan doc). A late result from a
        cancelled worker is simply ignored via the generation check in
        _on_worker_finished/_on_worker_failed."""
        self._cancel_endgame()
        self.solutions_panel.hide_endgame()
        if self._worker is not None:
            self._worker.cancel()
            self._retired_workers.append(self._worker)
        self._generation += 1
        worker = SolveWorker(
            clone_clue(self.game_state.clue), self.game_state.a_me, self.game_state.a_opp,
            self.game_state.my_excluded, self._generation,
        )
        worker.finished_ok.connect(self._on_worker_finished)
        worker.failed.connect(self._on_worker_failed)
        # QThread.finished (not our own finished_ok/failed) fires once the
        # thread has truly stopped -- only then is it safe to drop it.
        worker.finished.connect(lambda w=worker: self._cleanup_worker(w))
        self._worker = worker
        self.busy_label.show()
        worker.start()

    def _cleanup_worker(self, worker: SolveWorker) -> None:
        if worker in self._retired_workers:
            self._retired_workers.remove(worker)
        # A worker that finished normally (not superseded/retired) still
        # sits in self._worker / self._endgame_worker; drop the reference
        # here too, or the next _cancel_endgame/_schedule_refresh would
        # append this already-finished wrapper to _retired_workers, where
        # it would never be removed (its `finished` already fired).
        if self._worker is worker:
            self._worker = None
        if self._endgame_worker is worker:
            self._endgame_worker = None
        worker.deleteLater()

    def _on_worker_finished(self, payload: dict, generation: int) -> None:
        if generation != self._generation:
            return  # stale: a newer move has already superseded this result
        self.busy_label.hide()
        self._render(payload)
        self._schedule_endgame(payload)

    def _on_worker_failed(self, message: str, generation: int) -> None:
        if generation != self._generation:
            return
        self.busy_label.hide()
        self.error_label.setText(f"⚠️ Erreur inattendue : {message}")
        self.error_label.show()

    def _cancel_endgame(self) -> None:
        if self._endgame_worker is not None:
            self._endgame_worker.cancel()
            self._retired_workers.append(self._endgame_worker)
            self._endgame_worker = None
        self._endgame_generation += 1

    def _schedule_endgame(self, payload: dict) -> None:
        """Start the exact endgame search for the state `payload` was just
        rendered from -- only after a FULL render (never _render_quick),
        and only when the board is small enough to be worth it."""
        self._cancel_endgame()
        if payload["n_solutions_total"] > ENDGAME_N_MAX:
            self.solutions_panel.hide_endgame()
            return
        gs = self.game_state
        worker = EndgameWorker(
            clone_clue(gs.clue), gs.a_me, gs.a_opp, gs.my_excluded, gs.opp_fail_pool_size,
            self._endgame_generation,
        )
        worker.finished_ok.connect(self._on_endgame_finished)
        worker.failed.connect(self._on_endgame_failed)
        worker.finished.connect(lambda w=worker: self._cleanup_worker(w))
        self._endgame_worker = worker
        self.solutions_panel.show_endgame_text(ENDGAME_PENDING_TEXT)
        worker.start()

    def _on_endgame_finished(self, result, generation: int) -> None:
        if generation != self._endgame_generation:
            return
        if result is None:
            self.solutions_panel.hide_endgame()
        else:
            self.solutions_panel.show_endgame_text(format_endgame(result))

    def _on_endgame_failed(self, message: str, generation: int) -> None:
        if generation != self._endgame_generation:
            return
        self.solutions_panel.show_endgame_text(f"Fin de partie : erreur ({message})")

    def closeEvent(self, event) -> None:
        workers = list(self._retired_workers)
        if self._worker is not None:
            workers.append(self._worker)
        if self._endgame_worker is not None:
            workers.append(self._endgame_worker)
        for worker in workers:
            try:
                worker.cancel()
                worker.wait(2000)
            except RuntimeError:
                pass  # already finished and cleaned up via deleteLater
        super().closeEvent(event)


def run() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
