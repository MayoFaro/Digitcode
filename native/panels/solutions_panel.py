from __future__ import annotations

from typing import Callable

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...endgame import PHASE_MY_POST_QUESTION, PHASE_OPP_TURN
from ...game_state import GameState
from .question_format import format_ev_question_label, format_question_label

MAX_ALTERNATIVES_SHOWN = 10

TURN_LABELS = {
    PHASE_OPP_TURN: "Tour : à l'adversaire",
    PHASE_MY_POST_QUESTION: "Tour : à moi — question posée, proposer ou finir le tour",
}
MY_TURN_LABEL = "Tour : à moi"


class SolutionsPanel(QWidget):
    """Volet 3: solutions restantes, recommandation, essais, historique --
    the web layout's col-advice block."""

    def __init__(self, game_state: GameState, run: Callable[[Callable[[], dict]], None], parent=None) -> None:
        super().__init__(parent)
        self.game_state = game_state
        self._run = run
        self._solutions: list[str] = []
        layout = QVBoxLayout(self)

        self.solutions_list_label = QLabel()
        self.solutions_list_label.setWordWrap(True)
        layout.addWidget(self.solutions_list_label)

        # Who moves (GameState.turn_phase): counted from the questions
        # entered, alternating from the starting player. Editable mid-game,
        # which is also how to resync a miscounted turn.
        turn_row = QHBoxLayout()
        self.turn_label = QLabel()
        turn_row.addWidget(self.turn_label)
        self.opp_starts_checkbox = QCheckBox("L'adversaire débute")
        self.opp_starts_checkbox.toggled.connect(
            lambda checked: self._run(lambda: self.game_state.set_opp_starts(checked))
        )
        turn_row.addWidget(self.opp_starts_checkbox)
        layout.addLayout(turn_row)

        self.p_win_label = QLabel()
        layout.addWidget(self.p_win_label)
        self.best_question_label = QLabel()
        self.best_question_label.setWordWrap(True)
        layout.addWidget(self.best_question_label)
        self.guess_now_label = QLabel()
        layout.addWidget(self.guess_now_label)

        # "Fin de partie" block: filled asynchronously by MainWindow's
        # EndgameWorker once the board is small enough (see endgame.py).
        self.endgame_label = QLabel()
        self.endgame_label.setWordWrap(True)
        self.endgame_label.setStyleSheet(
            "background: #eef6ee; padding: 4px; border-radius: 4px;"
        )
        self.endgame_label.hide()
        layout.addWidget(self.endgame_label)

        layout.addWidget(QLabel("Alternatives"))
        self.alternatives_list = QListWidget()
        self.alternatives_list.setMaximumHeight(120)
        layout.addWidget(self.alternatives_list)

        layout.addWidget(QLabel("Coups à solution unique"))
        self.ev_plus_list = QListWidget()
        self.ev_plus_list.setMaximumHeight(80)
        layout.addWidget(self.ev_plus_list)

        attempts_row = QHBoxLayout()
        self.a_me_label = QLabel()
        attempts_row.addWidget(self.a_me_label)
        self.a_opp_label = QLabel()
        attempts_row.addWidget(self.a_opp_label)
        self.opp_miss_btn = QPushButton("il a raté")
        self.opp_miss_btn.setToolTip(
            "Saisir d'abord la réponse à sa question de ce tour, puis cliquer ici."
        )
        self.opp_miss_btn.clicked.connect(
            lambda: self._run(lambda: self.game_state.guess_failed({"who": "opponent"}))
        )
        attempts_row.addWidget(self.opp_miss_btn)
        layout.addLayout(attempts_row)

        my_miss_row = QHBoxLayout()
        self.my_miss_combo = QComboBox()
        my_miss_row.addWidget(self.my_miss_combo)
        self.my_miss_btn = QPushButton("j'ai tenté celle-ci, raté")
        self.my_miss_btn.clicked.connect(self._on_my_miss)
        my_miss_row.addWidget(self.my_miss_btn)
        layout.addLayout(my_miss_row)

        layout.addWidget(QLabel("Historique"))
        self.trace_view = QPlainTextEdit()
        self.trace_view.setReadOnly(True)
        self.trace_view.setMaximumHeight(120)
        layout.addWidget(self.trace_view)

        buttons_row = QHBoxLayout()
        self.undo_btn = QPushButton("Annuler (undo)")
        self.undo_btn.clicked.connect(lambda: self._run(self.game_state.undo))
        buttons_row.addWidget(self.undo_btn)
        self.reset_btn = QPushButton("Réinitialiser")
        self.reset_btn.clicked.connect(lambda: self._run(self.game_state.reset))
        buttons_row.addWidget(self.reset_btn)
        layout.addLayout(buttons_row)

    def _on_my_miss(self) -> None:
        index = self.my_miss_combo.currentIndex()
        if index < 0 or index >= len(self._solutions):
            return
        sol = self._solutions[index]
        digits = [int(c) for c in sol.replace(" ", "")]
        self._run(lambda: self.game_state.guess_failed({"who": "me", "candidate": digits}))

    def show_endgame_text(self, text: str) -> None:
        self.endgame_label.setText(text)
        self.endgame_label.show()

    def hide_endgame(self) -> None:
        self.endgame_label.hide()

    def refresh(self, payload: dict) -> None:
        self._solutions = payload["solutions"]

        self.turn_label.setText(TURN_LABELS.get(self.game_state.turn_phase(), MY_TURN_LABEL))
        self.opp_starts_checkbox.blockSignals(True)
        self.opp_starts_checkbox.setChecked(self.game_state.opp_starts)
        self.opp_starts_checkbox.blockSignals(False)

        n_total = payload["n_solutions_total"]
        self.solutions_list_label.setText(
            "; ".join(self._solutions) if n_total <= 6 else f"{n_total} solutions possibles"
        )

        race = payload["race"]
        race_aware = race.get("race_aware", race["exact"])
        label = "P(je gagne)" if race_aware else "Qualité de réduction"
        tag = "(exact)" if race["exact"] else ("(estimation course)" if race_aware else "(estimation)")
        self.p_win_label.setText(f"{label} = {race['p_win'] * 100:.1f}% {tag}")

        best = race.get("best_question")
        self.best_question_label.setText(
            "Meilleure question : " + (format_question_label(best) if best else "(aucune)")
        )
        self.guess_now_label.setText(
            "OUI — proposez une solution !" if race["guess_now"] else "Non, attendez."
        )

        self.alternatives_list.clear()
        for alt in race["ranked_alternatives"][:MAX_ALTERNATIVES_SHOWN]:
            self.alternatives_list.addItem(format_question_label(alt))

        self.ev_plus_list.clear()
        for entry in payload.get("ev_plus_questions") or []:
            self.ev_plus_list.addItem(format_ev_question_label(entry))

        self.a_me_label.setText(f"Moi : {payload['a_me']}/2")
        self.a_opp_label.setText(f"Adversaire : {payload['a_opp']}/2")

        self.my_miss_combo.clear()
        self.my_miss_combo.addItems(self._solutions)

        self.trace_view.setPlainText("\n".join(payload["trace"]))
