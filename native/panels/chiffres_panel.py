from __future__ import annotations

from typing import Callable

from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ...game_state import GameState
from ...mapping import COLS, POSITIONS, ROW_BOTTOM, ROW_TOP
from ..widgets.chip_button import ChipButton

ROW_LETTERS = ROW_TOP + ROW_BOTTOM
COL_LETTERS = COLS


class ChiffresPanel(QWidget):
    """Volet 1: Chiffres (domaines), Sommes ligne, Sommes colonne -- the
    web layout's col-sums block."""

    def __init__(self, game_state: GameState, run: Callable[[Callable[[], dict]], None], parent=None) -> None:
        super().__init__(parent)
        self.game_state = game_state
        self._run = run
        self._selected_row_letter: str | None = None
        self._selected_col_letter: str | None = None
        self._last_payload: dict | None = None

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Chiffres"))
        self.domains_grid = QGridLayout()
        layout.addLayout(self.domains_grid)
        self.domain_labels: dict[str, QLabel] = {}
        for i, pos in enumerate(POSITIONS):
            label = QLabel()
            self.domain_labels[pos] = label
            self.domains_grid.addWidget(label, i // 3, i % 3)

        layout.addWidget(QLabel("Sommes ligne"))
        self.row_letters_row = QHBoxLayout()
        layout.addLayout(self.row_letters_row)
        self.row_values_row = QHBoxLayout()
        layout.addLayout(self.row_values_row)

        layout.addWidget(QLabel("Sommes colonne"))
        self.col_letters_row = QHBoxLayout()
        layout.addLayout(self.col_letters_row)
        self.col_values_row = QHBoxLayout()
        layout.addLayout(self.col_values_row)

        layout.addStretch(1)

    def _clear_layout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    def _render_letters(self, layout, letters, totals, selected, on_select) -> None:
        self._clear_layout(layout)
        for letter in letters:
            value = totals.get(letter)
            text = f"{letter}={value}" if value is not None else letter
            chip = ChipButton(text, selected=(letter == selected), is_set=(value is not None))
            chip.clicked.connect(lambda _checked=False, l=letter: on_select(l))
            layout.addWidget(chip)

    def _render_values(self, layout, letter, totals, reachable, clue_type, field_name) -> None:
        self._clear_layout(layout)
        if letter is None:
            layout.addWidget(QLabel("— choisissez une lettre ci-dessus —"))
            return
        current = totals.get(letter)
        options = [current] if current is not None else reachable.get(letter, [])
        for value in options:
            chip = ChipButton(str(value), selected=(value == current))
            chip.clicked.connect(
                lambda _checked=False, v=value: self._run(
                    lambda: self.game_state.apply_clue(clue_type, **{field_name: letter, "value": v})
                )
            )
            layout.addWidget(chip)
        raz = ChipButton("RAZ")
        raz.clicked.connect(
            lambda _checked=False: self._run(
                lambda: self.game_state.apply_clue(clue_type, **{field_name: letter, "value": None})
            )
        )
        layout.addWidget(raz)

    def _select_row_letter(self, letter: str) -> None:
        self._selected_row_letter = letter
        if self._last_payload is not None:
            self.refresh(self._last_payload)

    def _select_col_letter(self, letter: str) -> None:
        self._selected_col_letter = letter
        if self._last_payload is not None:
            self.refresh(self._last_payload)

    def refresh(self, payload: dict) -> None:
        self._last_payload = payload
        for pos in POSITIONS:
            values = ",".join(str(v) for v in payload["domains"][pos])
            self.domain_labels[pos].setText(f"<b>{pos}</b><br>{{{values}}}")

        self._render_letters(
            self.row_letters_row, ROW_LETTERS, payload["row_totals"], self._selected_row_letter,
            self._select_row_letter,
        )
        self._render_values(
            self.row_values_row, self._selected_row_letter, payload["row_totals"],
            payload["reachable_row_sums"], "row_total", "row",
        )

        self._render_letters(
            self.col_letters_row, COL_LETTERS, payload["col_totals"], self._selected_col_letter,
            self._select_col_letter,
        )
        self._render_values(
            self.col_values_row, self._selected_col_letter, payload["col_totals"],
            payload["reachable_col_sums"], "col_total", "col",
        )
