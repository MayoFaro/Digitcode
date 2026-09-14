from __future__ import annotations

from typing import Callable

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...game_state import GameState

# Below the threshold, every distinct reachable solution count is listed
# exactly -- that's precisely the zone where it matters whether a question
# can leave 2-4 solutions versus jumping straight to 1. Mirrors
# web/static/app.js's SOLUTION_COUNT_EXACT_THRESHOLD.
SOLUTION_COUNT_EXACT_THRESHOLD = 4
MAX_ALTERNATIVES_SHOWN = 10


def _format_solution_counts(entry: dict) -> str:
    counts = entry.get("solution_counts")
    if not counts:
        return "?"
    small = [c["n"] for c in counts if c["n"] <= SOLUTION_COUNT_EXACT_THRESHOLD]
    has_large = any(c["n"] > SOLUTION_COUNT_EXACT_THRESHOLD for c in counts)
    parts = [str(n) for n in small]
    if has_large:
        parts.append(f">{SOLUTION_COUNT_EXACT_THRESHOLD}")
    if len(parts) == 1:
        singular = len(small) == 1 and small[0] == 1
        return f"{parts[0]} solution" + ("" if singular else "s")
    return f"{', '.join(parts[:-1])} ou {parts[-1]} solutions"


def _format_question_label(entry: dict) -> str:
    prefix = ""
    if entry.get("near_finish"):
        prefix += "\U0001f534 "  # mirrors the web's red .near-finish styling
    if entry.get("lookahead_risk"):
        prefix += "⚠️ "  # mirrors the web's amber .lookahead-risk styling
    return f"{prefix}{entry['label']} — {_format_solution_counts(entry)}"


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

        self.p_win_label = QLabel()
        layout.addWidget(self.p_win_label)
        self.best_question_label = QLabel()
        self.best_question_label.setWordWrap(True)
        layout.addWidget(self.best_question_label)
        self.guess_now_label = QLabel()
        layout.addWidget(self.guess_now_label)

        layout.addWidget(QLabel("Alternatives"))
        self.alternatives_list = QListWidget()
        self.alternatives_list.setMaximumHeight(120)
        layout.addWidget(self.alternatives_list)

        attempts_row = QHBoxLayout()
        self.a_me_label = QLabel()
        attempts_row.addWidget(self.a_me_label)
        self.a_opp_label = QLabel()
        attempts_row.addWidget(self.a_opp_label)
        self.opp_miss_btn = QPushButton("il a raté")
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

    def refresh(self, payload: dict) -> None:
        self._solutions = payload["solutions"]

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
            "Meilleure question : " + (_format_question_label(best) if best else "(aucune)")
        )
        self.guess_now_label.setText(
            "OUI — proposez une solution !" if race["guess_now"] else "Non, attendez."
        )

        self.alternatives_list.clear()
        for alt in race["ranked_alternatives"][:MAX_ALTERNATIVES_SHOWN]:
            self.alternatives_list.addItem(_format_question_label(alt))

        self.a_me_label.setText(f"Moi : {payload['a_me']}/2")
        self.a_opp_label.setText(f"Adversaire : {payload['a_opp']}/2")

        self.my_miss_combo.clear()
        self.my_miss_combo.addItems(self._solutions)

        self.trace_view.setPlainText("\n".join(payload["trace"]))
