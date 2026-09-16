from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ...game_state import GameState
from ...mapping import POSITIONS
from ..widgets.chip_button import ChipButton
from ..widgets.segment_digit import SEGMENTS, SegmentDigit


def _current_relation(comparisons, left, right):
    for a, rel, b in comparisons:
        if a == left and b == right:
            return rel
        if a == right and b == left:
            return ">" if rel == "<" else "<"
    return None


def _find_stored_comparison(comparisons, left, right):
    for entry in comparisons:
        a, _, b = entry
        if (a == left and b == right) or (a == right and b == left):
            return entry
    return None


def _parity_label(current):
    if current == "Pair":
        return "P"
    if current == "Impair":
        return "I"
    return "?"


class ComparaisonsPanel(QWidget):
    """Volet 2: Comparaisons, Parité & segments -- the web layout's
    col-digits block."""

    def __init__(self, game_state: GameState, run: Callable[[Callable[[], dict]], None], parent=None) -> None:
        super().__init__(parent)
        self.game_state = game_state
        self._run = run
        self._last_payload: dict | None = None

        layout = QVBoxLayout(self)

        layout.addWidget(QLabel("Comparaisons"))
        self.cmp_grid = QGridLayout()
        layout.addLayout(self.cmp_grid)
        self.cmp_chip_pairs: dict[tuple[str, str], tuple[ChipButton, ChipButton]] = {}
        self._build_comparison_grid()

        layout.addWidget(QLabel("Parité & segments"))
        self.pos_grid = QGridLayout()
        self.pos_grid.setVerticalSpacing(2)
        self.pos_grid.setHorizontalSpacing(8)
        layout.addLayout(self.pos_grid)
        self.segment_widgets: dict[str, SegmentDigit] = {}
        self.parity_chips: dict[str, ChipButton] = {}
        positions_layout = [("T", 0, 0), ("U", 0, 1), ("V", 0, 2), ("W", 1, 0), ("X", 1, 1), ("Y", 1, 2)]
        for pos, row, col in positions_layout:
            cell = QVBoxLayout()
            cell.setContentsMargins(0, 0, 0, 0)
            cell.setSpacing(2)
            cell.addWidget(QLabel(f"<b>{pos}</b>"), alignment=Qt.AlignHCenter)
            digit = SegmentDigit(pos)
            digit.segment_clicked.connect(
                lambda seg, current, p=pos: self._on_segment_clicked(p, seg, current)
            )
            self.segment_widgets[pos] = digit
            cell.addWidget(digit, alignment=Qt.AlignHCenter)
            chip = ChipButton("?")
            chip.clicked.connect(lambda _checked=False, p=pos: self._on_parity_clicked(p))
            self.parity_chips[pos] = chip
            cell.addWidget(chip, alignment=Qt.AlignHCenter)
            wrapper = QWidget()
            wrapper.setLayout(cell)
            self.pos_grid.addWidget(wrapper, row, col)

        layout.addStretch(1)

    def _build_comparison_grid(self) -> None:
        self.cmp_grid.setHorizontalSpacing(4)
        self.cmp_grid.setVerticalSpacing(2)

        def letter_label(pos, row, col):
            label = QLabel(f"<b>{pos}</b>")
            self.cmp_grid.addWidget(label, row, col, alignment=Qt.AlignCenter)

        def connector(left, right, row, col):
            lt_chip = ChipButton("<")
            gt_chip = ChipButton(">")
            lt_chip.clicked.connect(lambda: self._on_comparison_clicked(left, right, "<"))
            gt_chip.clicked.connect(lambda: self._on_comparison_clicked(left, right, ">"))
            pair_row = QHBoxLayout()
            pair_row.setContentsMargins(0, 0, 0, 0)
            pair_row.setSpacing(2)
            pair_row.addWidget(lt_chip)
            pair_row.addWidget(gt_chip)
            wrapper = QWidget()
            wrapper.setLayout(pair_row)
            self.cmp_grid.addWidget(wrapper, row, col, alignment=Qt.AlignCenter)
            self.cmp_chip_pairs[(left, right)] = (lt_chip, gt_chip)

        letter_label("T", 0, 0)
        connector("T", "U", 0, 1)
        letter_label("U", 0, 2)
        connector("U", "V", 0, 3)
        letter_label("V", 0, 4)

        connector("T", "W", 1, 0)
        connector("U", "X", 1, 2)
        connector("V", "Y", 1, 4)

        letter_label("W", 2, 0)
        connector("W", "X", 2, 1)
        letter_label("X", 2, 2)
        connector("X", "Y", 2, 3)
        letter_label("Y", 2, 4)

    def _on_comparison_clicked(self, left: str, right: str, want: str) -> None:
        rel = _current_relation(self._last_payload["comparisons"], left, right)
        if rel == want:
            stored = _find_stored_comparison(self._last_payload["comparisons"], left, right)
            self._run(lambda: self.game_state.apply_clue(
                "comparison", left=stored[0], rel=stored[1], right=stored[2], remove=True,
            ))
        else:
            self._run(lambda: self.game_state.apply_clue("comparison", left=left, rel=want, right=right))

    def _on_parity_clicked(self, pos: str) -> None:
        current = self._last_payload["parity"].get(pos)
        if current is None:
            attempts = [{"pos": pos, "value": "Pair"}, {"pos": pos, "value": "Impair"}]
        elif current == "Pair":
            attempts = [{"pos": pos, "value": "Impair"}, {"pos": pos, "value": None}]
        else:
            attempts = [{"pos": pos, "value": None}]
        self._run(lambda: self.game_state.apply_clue_with_fallback("parity", attempts))

    def _on_segment_clicked(self, pos: str, seg: str, current) -> None:
        if current is None:
            attempts = [{"pos": pos, "seg": seg, "value": True}, {"pos": pos, "seg": seg, "value": False}]
        elif current is True:
            attempts = [{"pos": pos, "seg": seg, "value": False}, {"pos": pos, "seg": seg, "value": None}]
        else:
            attempts = [{"pos": pos, "seg": seg, "value": None}]
        self._run(lambda: self.game_state.apply_clue_with_fallback("segment", attempts))

    def refresh(self, payload: dict) -> None:
        self._last_payload = payload

        for (left, right), (lt_chip, gt_chip) in self.cmp_chip_pairs.items():
            rel = _current_relation(payload["comparisons"], left, right)
            lt_chip.set_state(selected=(rel == "<"))
            gt_chip.set_state(selected=(rel == ">"))

        for pos in POSITIONS:
            segment_state = {seg: payload["segment_state"].get(f"{pos}{seg}") for seg in SEGMENTS}
            self.segment_widgets[pos].set_segment_state(segment_state)
            self.parity_chips[pos].setText(_parity_label(payload["parity"].get(pos)))
