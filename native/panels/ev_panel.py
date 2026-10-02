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
            "Meilleure : chances après la réponse la plus favorable. "
            "Probabilités du modèle, avec choix de proposer ou de terminer le tour après la réponse."
        )
        explanation.setWordWrap(True)
        layout.addWidget(explanation)
        self.favorable = QLabel()
        self.favorable.setWordWrap(True)
        layout.addWidget(self.favorable)
        self.sort_order = QComboBox()
        self.sort_order.addItems(["Classer par EV moyenne", "Classer par pire issue", "Classer par meilleure issue"])
        self.sort_order.currentIndexChanged.connect(self._render)
        layout.addWidget(self.sort_order)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Question", "Moyenne", "Pire", "Meilleure"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        for column in (1, 2, 3):
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
        self._selected_label = None
        self.status.setText("Aucune analyse EV disponible pour cette position.")
        self._render()

    def set_pre_endgame_result(self, result):
        self._questions = [dict(q) for q in result['questions'] if q.get('ev') is not None
                           or any(b.get('p_win') is not None for b in q.get('branches', []))]
        complete = sum(q.get('ev') is not None for q in result['questions'])
        incomplete = sum(q.get('ev') is None for q in result['questions'])
        state = "Calcul terminé" if result['finished'] else "Calcul en cours"
        self.status.setText(
            f"{state} — {complete} questions entièrement évaluées, "
            f"{incomplete} incomplètes parmi les questions repérées. "
            "Classement partiel de mes prochaines questions, même si ce n’est pas mon tour. "
            "Les branches à plus de 20 candidats restent inconnues."
            " * : extrême provisoire, certaines réponses restent à calculer."
            + (" Repérage incomplet." if not result['discovery_complete'] else "")
        )
        self._render()

    def set_endgame_result(self, result):
        if not result.get('complete') and not result.get('progressive'):
            self.clear()
            self.status.setText("Calcul de fin de partie incomplet : classement indisponible.")
            return
        self._questions = [dict(q, ev=q['p_win']) for q in result.get('ranked_questions', [])]
        self.status.setText(
            f"Calcul en cours — {len(self._questions)} questions entièrement évaluées."
            if result.get('progressive') else
            "Fin de partie — classement des questions à mon tour."
            if self._questions else
            "Pas de prochaine question à classer dans cette phase du tour. "
            f"EV de la position : {result['p_win']:.1%}."
        )
        self._render()

    def _render(self, *_):
        selected = self.table.currentRow()
        # Rows refer to the previous ordering while a progressive result
        # replaces the list; keep the selected question by its label.
        selected_label = getattr(self, '_selected_label', None)
        for q in self._questions:
            q.setdefault('ev', None)
            values = [b.get('p_win', b.get('value')) for b in q.get('branches', [])
                      if b.get('p_win', b.get('value')) is not None]
            if q.get('best') is None:
                q['best'] = max(values) if values else q['ev']
            if q.get('worst') is None:
                q['worst'] = min(values) if values else None
        key = ('ev', 'worst', 'best')[self.sort_order.currentIndex()]
        self._questions.sort(key=lambda q: (-(q[key] if q[key] is not None else -1),
                                            -(q['ev'] if q['ev'] is not None else -1), q['label']))
        good = [q for q in self._questions if q['ev'] is not None and q['worst'] > .55 + 1e-12]
        self.favorable.setText(
            "Toutes les réponses >55 % : " + "; ".join(q['label'] for q in good)
            if good else "Aucune question certifiée avec toutes les réponses >55 % parmi les résultats disponibles."
        )
        self.table.blockSignals(True)
        self.table.setRowCount(0)
        for q in self._questions:
            row = self.table.rowCount()
            self.table.insertRow(row)
            label = q['label'] + (" ★" if q in good else "")
            if q.get('status') == 'blacklisted':
                label += ' (exclue)'
            elif q['worst'] is not None and q['worst'] < .5 - 1e-12:
                label += ' (à risque)'
            def percentage(value, extreme=False):
                if value is None:
                    return "…"
                suffix = " *" if extreme and q['ev'] is None else ""
                return f"{value:.1%}" + suffix
            for col, text in enumerate((label, percentage(q['ev']), percentage(q['worst'], True),
                                        percentage(q['best'], True))):
                self.table.setItem(row, col, QTableWidgetItem(text))
            if q['label'] == selected_label:
                selected = row
        self.table.resizeRowsToContents()
        self.details.setText("Sélectionner une question pour voir ses réponses.")
        if selected_label and any(q['label'] == selected_label for q in self._questions):
            self.table.selectRow(selected)
        else:
            self._selected_label = None
        self.table.blockSignals(False)
        self._show_details()

    def _show_details(self):
        row = self.table.currentRow()
        if not 0 <= row < len(self._questions):
            return
        q = self._questions[row]
        self._selected_label = q['label']
        branches = q.get('branches', [])
        total = sum(b.get('n_mine') or b['n'] for b in branches)
        lines = [q['label']]
        for b in branches:
            value = b.get('p_win', b.get('value'))
            probability = b.get('prob', (b.get('n_mine') or b['n']) / total if total else 0)
            victory = f"{value:.1%}" if value is not None else "non calculée"
            response = "inconnue" if any(b2.get('capped') for b2 in branches) else f"{probability:.1%}"
            lines.append(f"{b['answer']} : victoire {victory} · réponse {response}")
        self.details.setText('\n'.join(lines))
