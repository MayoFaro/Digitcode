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

from ..game_state import GameState, clone_clue
from .endgame_worker import EndgameWorker
from .pre_endgame_worker import PreEndgameWorker
from .panels.chiffres_panel import ChiffresPanel
from .panels.comparaisons_panel import ComparaisonsPanel
from .panels.endgame_format import ENDGAME_PENDING_TEXT
from .panels.solutions_panel import SolutionsPanel
from .panels.ev_panel import EVPanel
from .solve_worker import SolveWorker

WINDOW_WIDTH = 380

OPACITY_STEP = 0.05
OPACITY_MIN = 0.2
OPACITY_MAX = 1.0

TAB_TITLES = ["Chiffres", "Comparaisons", "Solutions", "EV"]


def _add_tabs(owner, layout, titles):
    row = QHBoxLayout()
    buttons = []
    group = QButtonGroup(owner)
    group.setExclusive(True)
    for index, title in enumerate(titles):
        button = QPushButton(title)
        button.setCheckable(True)
        group.addButton(button, index)
        row.addWidget(button)
        buttons.append(button)
    buttons[0].setChecked(True)
    layout.addLayout(row)
    stack = QStackedWidget()
    layout.addWidget(stack)
    group.idClicked.connect(stack.setCurrentIndex)
    return buttons, stack


def _risk_label():
    label = QLabel()
    label.setWordWrap(True)
    label.setTextFormat(Qt.PlainText)
    label.setStyleSheet("background: #b71c1c; color: white; font-weight: bold; padding: 7px; border-radius: 4px;")
    label.hide()
    return label


class _RiskOverlay(QLabel):
    """Translucent red band pinned to the bottom of its parent, outside the
    layout flow. Unlike the inline alert, showing/hiding it never reflows
    the widgets above it -- the input window used an inline label that
    pushed the tab row and the chip grids down while the user was clicking
    on them. Carries no text on purpose and ignores mouse events, so it
    can never intercept a click even while visible."""

    HEIGHT = 22

    def __init__(self, parent):
        super().__init__(parent)
        self.setStyleSheet("background-color: rgba(183, 28, 28, 0.55);")
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.hide()

    def setText(self, text):
        pass

    def reposition(self) -> None:
        parent = self.parentWidget()
        if parent is None:
            return
        self.setGeometry(0, parent.height() - self.HEIGHT, parent.width(), self.HEIGHT)


class AnalysisWindow(QMainWindow):
    def __init__(self, controller):
        # No Qt parent: both windows have the same stacking priority.
        super().__init__()
        self.controller = controller
        self.setWindowTitle("Digitcode — Analyse")
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.resize(580, 700)
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        self.solutions_label = QLabel()
        layout.addWidget(self.solutions_label)
        self.risk_alert = _risk_label()
        layout.addWidget(self.risk_alert)
        self.busy_label = QLabel("Calcul en cours… La saisie reste disponible.")
        self.busy_label.setStyleSheet("color: #888; font-style: italic;")
        self.busy_label.hide()
        layout.addWidget(self.busy_label)
        self.tab_buttons, self.stack = _add_tabs(self, layout, TAB_TITLES[2:])

    def closeEvent(self, event):
        if not self.controller._closing:
            self.controller.close()
        super().closeEvent(event)


class MainWindow(QMainWindow):
    def __init__(self, game_state: GameState | None = None) -> None:
        super().__init__()
        self.game_state = game_state or GameState()
        self._generation = 0
        self._worker: SolveWorker | None = None
        # Input is rendered immediately; analysis belongs to a fixed snapshot.
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
        # Separate generations discard both old payloads and old EV updates.
        self._endgame_worker: EndgameWorker | PreEndgameWorker | None = None
        self._endgame_generation = 0

        self.setWindowTitle("Digitcode — Saisie")
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

        self.tab_buttons, self.stack = _add_tabs(self, layout, TAB_TITLES[:2])
        self.tab_group = self.tab_buttons[0].group()
        self.tab_group.idClicked.connect(self._on_tab_clicked)
        self.solutions_label = QLabel()
        layout.insertWidget(1, self.solutions_label)
        self.risk_alert = _RiskOverlay(central)
        self.risk_alert.raise_()
        self.risk_alert.reposition()

        self.analysis_window = AnalysisWindow(self)
        self.busy_label = self.analysis_window.busy_label
        self.solutions_panel = SolutionsPanel(self.game_state, self._run)
        self.ev_panel = EVPanel(self.solutions_panel.pre_endgame_group)
        self.solutions_panel.pre_endgame_status.hide()
        self.panels: list[QWidget] = [
            ChiffresPanel(self.game_state, self._mutate),
            ComparaisonsPanel(self.game_state, self._mutate),
            self.solutions_panel, self.ev_panel,
        ]
        for panel in self.panels[:2]:
            self.stack.addWidget(panel)
        for panel in self.panels[2:]:
            self.analysis_window.stack.addWidget(panel)
        self._closing = False
        self._positioned_analysis = False
        self._render(self.game_state.pending_payload())
        self._schedule_refresh()

        # Application-wide filter, not a wheelEvent override: Qt delivers
        # wheel events to the widget under the cursor, so a handler on the
        # window itself would never fire when scrolling over a button/panel.
        QApplication.instance().installEventFilter(self)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._positioned_analysis:
            self.analysis_window.move(self.x() + self.width() + 12, self.y())
            self._positioned_analysis = True
        self.analysis_window.show()
        self.risk_alert.reposition()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.risk_alert.reposition()

    def eventFilter(self, obj: QWidget, event: QEvent) -> bool:
        if event.type() == QEvent.Wheel and event.modifiers() & Qt.ControlModifier:
            target = obj.window() if isinstance(obj, QWidget) else None
            if target in (self, self.analysis_window):
                step = OPACITY_STEP if event.angleDelta().y() > 0 else -OPACITY_STEP
                opacity = min(OPACITY_MAX, max(OPACITY_MIN, target.windowOpacity() + step))
                target.setWindowOpacity(opacity)
                return True
        return super().eventFilter(obj, event)

    def _on_tab_clicked(self, index: int) -> None:
        self.stack.setCurrentIndex(index)

    def _run(self, fn: Callable[[], dict]) -> None:
        """Apply actions without computing a display payload in the GUI thread."""
        try:
            with self.game_state.defer_payload():
                fn()
        except ValueError as exc:
            self.error_label.setText("⚠️ " + str(exc))
            self.error_label.show()
            return
        except Exception as exc:
            self.error_label.setText(f"⚠️ Erreur inattendue : {exc}")
            self.error_label.show()
            raise
        self.error_label.hide()
        self._render_quick()
        self._schedule_refresh()

    def _render(self, payload: dict) -> None:
        self.risk_alert.hide()
        self.analysis_window.risk_alert.hide()
        self._last_payload = payload
        count = payload['n_solutions_total']
        text = "Solutions restantes : calcul en cours…" if count is None else f"Solutions restantes : {count}"
        self.solutions_label.setText(text)
        self.analysis_window.solutions_label.setText(text)
        for panel in self.panels:
            panel.refresh(payload)

    def _render_quick(self) -> None:
        """Show fresh clues and reachable sums; mark old analysis unavailable."""
        self._render(self.game_state.pending_payload())

    def _mutate(self, fn_fast: Callable[[], None]) -> None:
        """Validate and show a clue immediately, then restart isolated analysis."""
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
        """Restart on a cloned board without waiting for the cancelled process."""
        if self._closing:
            return
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
        self._render({**payload, "result": self.game_state.result})
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
        self.risk_alert.hide()
        self.analysis_window.risk_alert.hide()
        self.solutions_panel.hide_pre_endgame()
        self.ev_panel.clear()

    def _schedule_endgame(self, payload: dict) -> None:
        """After a full render, screen upcoming questions or analyze endgame."""
        if self._closing:
            return
        self._cancel_endgame()
        self.solutions_panel.hide_endgame()
        gs = self.game_state
        if payload["n_solutions_total"] <= 0:
            return
        pre = not gs.is_endgame()
        if pre:
            # No initial question can narrow an empty board to <=20.
            c = gs.clue
            if not (c.row_totals or c.col_totals or c.parity or c.comparisons or c.segment_state):
                return
            worker_type = PreEndgameWorker
        else:
            worker_type = EndgameWorker
        worker = worker_type(
            clone_clue(gs.clue), gs.a_me, gs.a_opp, gs.my_excluded, gs.opp_fail_pool_size,
            self._endgame_generation, phase=gs.endgame_turn_phase(),
        )
        if pre:
            worker.progress.connect(self._on_pre_endgame_finished)
            worker.finished_ok.connect(self._on_pre_endgame_finished)
        else:
            worker.progress.connect(self._on_endgame_progress)
            worker.finished_ok.connect(self._on_endgame_finished)
        worker.failed.connect(self._on_endgame_failed)
        worker.finished.connect(lambda w=worker: self._cleanup_worker(w))
        self._endgame_worker = worker
        if pre:
            self.solutions_panel.show_pre_endgame_pending()
            self.ev_panel.status.setText("Calcul des EV en cours…")
        else:
            self.solutions_panel.show_endgame_text(ENDGAME_PENDING_TEXT)
            self.ev_panel.status.setText("Calcul de fin de partie en cours…")
        worker.start()

    def _on_pre_endgame_finished(self, result, generation: int) -> None:
        if generation == self._endgame_generation:
            self.solutions_panel.set_pre_endgame_result(result)
            self.ev_panel.set_pre_endgame_result(result)
            self.solutions_panel.validated_questions.hide()
            self.solutions_panel.validated_questions_title.hide()
            panel = self.solutions_panel
            self.panels[0].set_pre_endgame_advice(
                panel.best_question_label.text(),
                "\n".join(panel.ev_plus_list.item(i).text() for i in range(panel.ev_plus_list.count())) or "(aucun)",
            )
            values = [b['p_win'] for q in result['questions'] for b in q.get('branches', [])
                      if b.get('p_win') is not None]
            values += [q['danger']['p_win'] for q in result['questions'] if q.get('danger')]
            self._show_risk_alert(values)

    def _show_risk_alert(self, values) -> None:
        low = [p for p in values if p < 0.5 - 1e-12]
        self.risk_alert.setVisible(bool(low))
        self.analysis_window.risk_alert.setVisible(bool(low))
        if low:
            minimum = f"{min(low):.1%}".replace('.', ',')
            text = (f"⚠ Risque détecté : une issue calculée donne moins de 50 % "
                    f"de chances de victoire (minimum : {minimum}).")
            self.risk_alert.setText(text)
            self.analysis_window.risk_alert.setText(text)

    def _on_endgame_progress(self, result, generation: int) -> None:
        if generation == self._endgame_generation:
            self.ev_panel.set_endgame_result(result)
            self._show_risk_alert([b['value'] for q in result.get('ranked_questions', [])
                                   for b in q.get('branches', [])])

    def _on_endgame_finished(self, result, generation: int) -> None:
        if generation != self._endgame_generation:
            return
        if result is None:
            self.solutions_panel.hide_endgame()
        else:
            self.solutions_panel.set_endgame_result(result)
            self.ev_panel.set_endgame_result(result)
            values = [result['p_win']] if result.get('p_win') is not None else []
            for key in ('best_question', 'best_informative_question', 'best_null_question'):
                values.extend(b['value'] for b in (result.get(key) or {}).get('branches', []))
            self._show_risk_alert(values)

    def _on_endgame_failed(self, message: str, generation: int) -> None:
        if generation != self._endgame_generation:
            return
        self.ev_panel.status.setText(f"Analyse incomplète : erreur ({message})")
        if self.solutions_panel.pre_endgame_group.isHidden():
            self.solutions_panel.show_endgame_text(f"Fin de partie : erreur ({message})")
        else:
            self.solutions_panel.pre_endgame_status.setText(f"Analyse incomplète : erreur ({message})")

    def closeEvent(self, event) -> None:
        if self._closing:
            event.accept()
            return
        self._closing = True
        # Results already queued before cancellation must not restart work
        # after these windows have closed.
        self._generation += 1
        self._endgame_generation += 1
        QApplication.instance().removeEventFilter(self)
        self.analysis_window.close()
        workers = list(self._retired_workers)
        if self._worker is not None:
            workers.append(self._worker)
        if self._endgame_worker is not None:
            workers.append(self._endgame_worker)
        for worker in workers:
            try:
                worker.cancel()
            except RuntimeError:
                pass
        for worker in workers:
            try:
                worker.wait()
            except RuntimeError:
                pass  # already finished and cleaned up via deleteLater
        super().closeEvent(event)


def run() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
