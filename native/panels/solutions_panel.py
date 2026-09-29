from __future__ import annotations

from typing import Callable

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QGroupBox,
    QLabel,
    QListWidget,
    QLineEdit,
    QPlainTextEdit,
    QScrollArea,
    QSizePolicy,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...endgame import ENDGAME_N_MAX, PHASE_MY_TURN, PHASE_MY_POST_QUESTION, PHASE_OPP_TURN
from ...endgame_tempo import PHASE_OPP_POST_QUESTION, PHASES
from ...game_state import GameState
from .question_format import format_ev_question_label, format_question_label

MAX_ALTERNATIVES_SHOWN = 10

TURN_LABELS = {
    PHASE_OPP_TURN: "Tour : à l'adversaire",
    PHASE_OPP_POST_QUESTION: "Tour : adversaire — question posée, proposer ou finir le tour",
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
        self._endgame_display = False
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        content = QWidget()
        self.scroll_area.setWidget(content)
        outer.addWidget(self.scroll_area)
        layout = QVBoxLayout(content)

        self.solutions_list_label = QLabel()
        self.solutions_list_label.setWordWrap(True)
        layout.addWidget(self.solutions_list_label)

        # Who moves (GameState.turn_phase): counted from the questions
        # entered, alternating from the starting player. Editable mid-game,
        # which is also how to resync a miscounted turn.
        turn_row = QHBoxLayout()
        self.turn_label = QLabel()
        self.turn_label.setWordWrap(True)
        turn_row.addWidget(self.turn_label)
        self.opp_starts_checkbox = QCheckBox("L'adversaire débute")
        self.opp_starts_checkbox.setToolTip(
            "Recalcule le suivi automatique depuis le joueur initial. "
            "Une phase de tour explicitement corrigée reste prioritaire."
        )
        self.opp_starts_checkbox.toggled.connect(
            lambda checked: self._run(lambda: self.game_state.set_opp_starts(checked))
        )
        turn_row.addWidget(self.opp_starts_checkbox)
        layout.addLayout(turn_row)

        # "Fin de partie" block: filled asynchronously by MainWindow's
        # EndgameWorker once the board is small enough (see endgame.py).
        self.endgame_label = QLabel()
        self.endgame_label.setWordWrap(True)
        self.endgame_label.setStyleSheet(
            "background: #eef6ee; padding: 4px; border-radius: 4px;"
        )
        self.endgame_label.hide()
        layout.addWidget(self.endgame_label)

        self.endgame_details_toggle = QCheckBox("Détails des probabilités")
        self.endgame_details_label = QLabel()
        self.endgame_details_label.setWordWrap(True)
        self.endgame_details_toggle.toggled.connect(self._toggle_endgame_details)
        self.endgame_details_toggle.hide()
        self.endgame_details_label.hide()
        layout.addWidget(self.endgame_details_toggle)
        layout.addWidget(self.endgame_details_label)

        self.endgame_controls = QWidget()
        controls = QVBoxLayout(self.endgame_controls)
        controls.setContentsMargins(0, 0, 0, 0)
        hint = QLabel("Corriger le tour courant ; le suivi reprend ensuite automatiquement.")
        hint.setWordWrap(True)
        controls.addWidget(hint)
        self.turn_override_combo = QComboBox()
        for phase, label in zip(PHASES, (
            "Moi — avant question",
            "Moi — question déjà posée",
            "Adversaire — avant question",
            "Adversaire — question déjà posée",
        )):
            self.turn_override_combo.addItem(label, phase)
        self.turn_override_combo.activated.connect(self._on_turn_override)
        controls.addWidget(self.turn_override_combo)
        self.end_turn_btn = QPushButton("Terminer le tour sans proposition")
        self.end_turn_btn.clicked.connect(lambda: self._run(self.game_state.end_endgame_turn))
        controls.addWidget(self.end_turn_btn)
        self.null_questions_combo = QComboBox()
        self.null_questions_combo.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        controls.addWidget(self.null_questions_combo)
        self.record_null_btn = QPushButton("Enregistrer cette question nulle")
        self.record_null_btn.setToolTip("À utiliser après avoir réellement posé cette question. La réponse est déjà connue.")
        self.record_null_btn.clicked.connect(self._on_null_question)
        controls.addWidget(self.record_null_btn)
        self.endgame_controls.hide()
        layout.addWidget(self.endgame_controls)

        self.analysis_group = QGroupBox("Comparaisons des questions")
        analysis = QVBoxLayout(self.analysis_group)
        self.analysis_context = QLabel()
        self.analysis_context.setWordWrap(True)
        analysis.addWidget(self.analysis_context)
        layout.addWidget(self.analysis_group)
        self.p_win_label = QLabel()
        analysis.addWidget(self.p_win_label)
        self.best_question_label = QLabel()
        self.best_question_label.setWordWrap(True)
        analysis.addWidget(self.best_question_label)
        self.guess_now_label = QLabel()
        self.guess_now_label.setWordWrap(True)
        analysis.addWidget(self.guess_now_label)

        analysis.addWidget(QLabel("Alternatives"))
        self.alternatives_list = QListWidget()
        self.alternatives_list.setMaximumHeight(120)
        analysis.addWidget(self.alternatives_list)

        analysis.addWidget(QLabel("Coups à solution unique"))
        self.ev_plus_list = QListWidget()
        self.ev_plus_list.setMaximumHeight(80)
        analysis.addWidget(self.ev_plus_list)

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

        result_group = QGroupBox("Résultat de la partie — historique")
        result_layout = QVBoxLayout(result_group)
        self.result_who = QComboBox()
        self.result_who.addItem("J’ai trouvé la solution", "me")
        self.result_who.addItem("L’adversaire a trouvé la solution", "opponent")
        result_layout.addWidget(self.result_who)
        self.result_code = QLineEdit()
        self.result_code.setPlaceholderText("Code final, exemple : 064 147")
        result_layout.addWidget(self.result_code)
        self.result_save_btn = QPushButton("Enregistrer / corriger le résultat")
        self.result_save_btn.clicked.connect(lambda: self._run(lambda: self.game_state.record_result({
            "who": self.result_who.currentData(), "code": self.result_code.text(),
        })))
        result_layout.addWidget(self.result_save_btn)
        self.result_label = QLabel()
        self.result_label.setWordWrap(True)
        result_layout.addWidget(self.result_label)
        self.result_clear_btn = QPushButton("Effacer le résultat saisi")
        self.result_clear_btn.clicked.connect(lambda: self._run(self.game_state.clear_result))
        result_layout.addWidget(self.result_clear_btn)
        layout.addWidget(result_group)
        self._shown_result = None
        self._shown_started_at = game_state.started_at

        layout.addWidget(QLabel("Historique"))
        self.trace_view = QPlainTextEdit()
        self.trace_view.setReadOnly(True)
        self.trace_view.setMaximumHeight(120)
        layout.addWidget(self.trace_view)

        self.archive_label = QLabel()
        self.archive_label.setWordWrap(True)
        self.archive_label.hide()
        layout.addWidget(self.archive_label)

        buttons_row = QHBoxLayout()
        self.undo_btn = QPushButton("Annuler (undo)")
        self.undo_btn.clicked.connect(lambda: self._run(self.game_state.undo))
        buttons_row.addWidget(self.undo_btn)
        self.reset_btn = QPushButton("Réinitialiser")
        self.reset_btn.setToolTip("Sauvegarde automatiquement la partie avant de la réinitialiser.")
        self.reset_btn.clicked.connect(lambda: self._run(self.game_state.reset))
        buttons_row.addWidget(self.reset_btn)
        layout.addLayout(buttons_row)
        layout.addStretch(1)

    def _toggle_endgame_details(self, checked: bool) -> None:
        self.endgame_details_label.setVisible(checked and bool(self.endgame_details_label.text()))
        if self._endgame_display:
            self.analysis_group.setVisible(checked)

    def _on_turn_override(self, index: int) -> None:
        phase = self.turn_override_combo.itemData(index)
        self._run(lambda: self.game_state.set_endgame_phase(phase))

    def _on_null_question(self) -> None:
        entry = self.null_questions_combo.currentData()
        if entry is not None:
            self._run(lambda: self.game_state.record_null_question(entry))

    def set_endgame_result(self, result: dict) -> None:
        from .endgame_format import format_endgame, format_endgame_details
        self.show_endgame_text(format_endgame(result))
        details = format_endgame_details(result)
        self.endgame_details_label.setText(details)
        self.endgame_details_toggle.setVisible(bool(details) or self._endgame_display)
        self.null_questions_combo.clear()
        for q in result.get("null_questions", []):
            self.null_questions_combo.addItem(f"{q['label']} → {q['answer']}", q["entry"])
        self.record_null_btn.setEnabled(self.null_questions_combo.count() > 0
                                        and self.game_state.a_me > 0 and self.game_state.a_opp > 0)

    def _on_my_miss(self) -> None:
        index = self.my_miss_combo.currentIndex()
        if index < 0 or index >= len(self._solutions):
            return
        sol = self._solutions[index]
        digits = [int(c) for c in sol.replace(" ", "")]
        self._run(lambda: self.game_state.guess_failed({"who": "me", "candidate": digits}))

    def show_endgame_text(self, text: str) -> None:
        self.endgame_details_toggle.setChecked(False)
        self.endgame_details_toggle.setVisible(self._endgame_display)
        self.endgame_details_label.hide()
        self.endgame_details_label.clear()
        self.endgame_label.setText(text)
        self.endgame_label.show()

    def hide_endgame(self) -> None:
        self.endgame_label.hide()
        self.endgame_details_toggle.setChecked(False)
        self.endgame_details_toggle.hide()
        self.endgame_details_label.hide()
        self.null_questions_combo.clear()
        self.record_null_btn.setEnabled(False)

    def refresh(self, payload: dict) -> None:
        self._solutions = payload["solutions"]
        result = self.game_state.result
        if self._shown_started_at != self.game_state.started_at or (self._shown_result and not result):
            self.result_code.clear()
            self.result_who.setCurrentIndex(0)
        if result and result != self._shown_result:
            self.result_who.setCurrentIndex(self.result_who.findData(result["winner"]))
            self.result_code.setText(result["code"])
        self._shown_result = result
        self._shown_started_at = self.game_state.started_at
        self.result_clear_btn.setEnabled(result is not None)
        if result:
            winner = "Moi" if result["winner"] == "me" else "Adversaire"
            code = result["code"]
            self.result_label.setText(f"Résultat enregistré : {winner} — {code[:3]} {code[3:]}. Archivé à la réinitialisation.")
        else:
            self.result_label.setText("Résultat non renseigné. À enregistrer avant de réinitialiser.")

        archive = self.game_state.last_archive_path
        self.archive_label.setVisible(archive is not None)
        self.archive_label.setText(f"Dernière partie sauvegardée : {archive}" if archive else "")

        endgame = (0 < payload["n_solutions_total"] <= ENDGAME_N_MAX
                   and self.game_state.is_endgame())
        self._endgame_display = endgame
        self.analysis_group.setVisible(not endgame or self.endgame_details_toggle.isChecked())
        phase = self.game_state.endgame_turn_phase() if endgame else self.game_state.turn_phase()
        self.turn_label.setText(TURN_LABELS.get(phase, MY_TURN_LABEL))
        self.endgame_controls.setVisible(endgame)
        self.turn_override_combo.setCurrentIndex(self.turn_override_combo.findData(phase))
        post = phase in (PHASE_MY_POST_QUESTION, PHASE_OPP_POST_QUESTION)
        playing = self.game_state.a_me > 0 and self.game_state.a_opp > 0
        self.end_turn_btn.setEnabled(endgame and post and playing)
        self.end_turn_btn.setText("Terminer mon tour sans proposer" if phase in (PHASE_MY_TURN, PHASE_MY_POST_QUESTION)
                                 else "L'adversaire termine sans proposer")
        next_question_is_mine = phase in (PHASE_MY_TURN, PHASE_OPP_POST_QUESTION)
        self.record_null_btn.setText("Enregistrer ma question nulle" if next_question_is_mine
                                     else "Enregistrer la question nulle adverse")
        self.record_null_btn.setToolTip(
            "À enregistrer après l'avoir jouée. "
            + ("Le tour courant se termine sans proposition ; cette question appartient au joueur suivant."
               if post else "La réponse est déjà connue, mais la question est consommée.")
        )
        self.analysis_context.setVisible(endgame)
        self.analysis_context.setText(
            "Hypothèse d'une nouvelle question : ces comparaisons ne sont pas des coups jouables ce tour."
            if post else "Analyse rapide sans questions nulles ; le conseil de fin de partie ci-dessus est prioritaire."
        )
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
            ("Comparaison rapide : proposition directe privilégiée" if race["guess_now"]
             else "Comparaison rapide : question privilégiée") if endgame else
            ("OUI — proposez une solution !" if race["guess_now"] else "Non, attendez.")
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
