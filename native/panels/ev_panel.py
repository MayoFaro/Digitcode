"""Dedicated view of question EVs, coverage and adverse outcomes."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QLabel, QScrollArea, QTableWidget, QTableWidgetItem,
    QHeaderView, QVBoxLayout, QWidget,
)


class EVPanel(QWidget):
    def __init__(self, risk_group, parent=None):
        super().__init__(parent)
        self._questions = []
        outer = QVBoxLayout(self)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout(content)
        scroll.setWidget(content)
        outer.addWidget(scroll)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        explanation = QLabel(
            "Moyenne : chances de victoire pondérées par les réponses possibles. "
            "Pire : chances après la réponse la plus défavorable. "
            "Probabilités du modèle, avec choix de proposer ou de terminer le tour après la réponse."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        self.favorable = QLabel()
        self.favorable.setWordWrap(True)
        layout.addWidget(self.favorable)
        self.sort_order = QComboBox()
        self.sort_order.addItems(["Classer par EV moyenne", "Classer par pire issue"])
        self.sort_order.currentIndexChanged.connect(self._render)
        layout.addWidget(self.sort_order)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Question", "Moyenne", "Pire"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for column in (1, 2):
            self.table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setMinimumHeight(220)
        layout.addWidget(self.table)
        self.details = QLabel("Sélectionner une question pour voir ses réponses.")
        self.details.setWordWrap(True)
        self.details.setTextFormat(Qt.PlainText)
        layout.addWidget(self.details)
        self.table.itemSelectionChanged.connect(self._show_details)
        layout.addWidget(risk_group)
        layout.addStretch()
        self.clear()

    def refresh(self, payload):
        self.clear()

    def clear(self):
        self._questions = []
        self.status.setText("Aucune analyse EV disponible pour cette position.")
        self._render()

    def set_pre_endgame_result(self, result):
        self._questions = [q for q in result['questions'] if q.get('ev') is not None]
        incomplete = sum(q.get('ev') is None for q in result['questions'])
        state = "Calcul terminé" if result['finished'] else "Calcul en cours"
        self.status.setText(
            f"{state} — {len(self._questions)} questions entièrement évaluées, "
            f"{incomplete} incomplètes parmi les questions repérées. "
            "Classement partiel de mes prochaines questions, même si ce n’est pas mon tour. "
            "Les branches à plus de 20 candidats restent inconnues."
            + (" Repérage incomplet." if not result['discovery_complete'] else "")
        )
        self._render()

    def set_endgame_result(self, result):
        if not result.get('complete'):
            self.clear()
            self.status.setText("Calcul de fin de partie incomplet : classement indisponible.")
            return
        self._questions = [dict(q, ev=q['p_win']) for q in result.get('ranked_questions', [])]
        self.status.setText(
            "Fin de partie — classement des questions à mon tour."
            if self._questions else
            "Pas de prochaine question à classer dans cette phase du tour. "
            f"EV de la position : {result['p_win']:.1%}."
        )
        self._render()

    def _render(self, *_):
        key = 'worst' if self.sort_order.currentIndex() else 'ev'
        self._questions.sort(key=lambda q: (-q[key], -q['ev'], q['label']))
        good = [q for q in self._questions if q['worst'] > .55 + 1e-12]
        self.favorable.setText(
            "Toutes les réponses >55 % : " + "; ".join(q['label'] for q in good)
            if good else "Aucune question certifiée avec toutes les réponses >55 % parmi les résultats disponibles."
        )
        self.table.setRowCount(0)
        for q in self._questions:
            row = self.table.rowCount()
            self.table.insertRow(row)
            label = q['label'] + (" ★" if q in good else "")
            if q.get('status') == 'blacklisted':
                label += ' (exclue)'
            elif q['worst'] < .5 - 1e-12:
                label += ' (à risque)'
            for col, text in enumerate((label, f"{q['ev']:.1%}", f"{q['worst']:.1%}")):
                self.table.setItem(row, col, QTableWidgetItem(text))
        self.table.resizeRowsToContents()
        self.details.setText("Sélectionner une question pour voir ses réponses.")

    def _show_details(self):
        row = self.table.currentRow()
        if not 0 <= row < len(self._questions):
            return
        q = self._questions[row]
        branches = q.get('branches', [])
        total = sum(b.get('n_mine', b['n']) for b in branches)
        lines = [q['label']]
        for b in branches:
            value = b.get('p_win', b.get('value'))
            probability = b.get('prob', b.get('n_mine', b['n']) / total if total else 0)
            lines.append(f"{b['answer']} : victoire {value:.1%} · réponse {probability:.1%}")
        self.details.setText('\n'.join(lines))
