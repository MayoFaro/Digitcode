from __future__ import annotations

import sys
from typing import Callable

from PySide6.QtCore import QEvent, Qt
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

from ..game_state import GameState
from .panels.chiffres_panel import ChiffresPanel
from .panels.comparaisons_panel import ComparaisonsPanel
from .panels.solutions_panel import SolutionsPanel

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

        self.stack = QStackedWidget()
        layout.addWidget(self.stack)
        self.panels: list[QWidget] = [
            ChiffresPanel(self.game_state, self._run),
            ComparaisonsPanel(self.game_state, self._run),
            SolutionsPanel(self.game_state, self._run),
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
        finally:
            QApplication.processEvents()
            self.centralWidget().setEnabled(True)

    def _render(self, payload: dict) -> None:
        self.solutions_label.setText(f"Solutions restantes : {payload['n_solutions_total']}")
        for panel in self.panels:
            panel.refresh(payload)


def run() -> None:
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
