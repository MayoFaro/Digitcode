from __future__ import annotations

from PySide6.QtWidgets import QPushButton


class ChipButton(QPushButton):
    """A small pill-shaped clickable button reflecting two independent
    flags: `selected` (the option currently in effect, e.g. a picked
    parity or comparison relation) and `is_set` (a value already stored on
    the board, e.g. a fixed row/col total). Mirrors the web frontend's
    `.chip` / `.chip-selected` / `.chip-set` classes
    (web/static/style.css) -- pure display, no cycling logic of its own.
    """

    # min-width/min-height matter for single-character labels like "<"/">":
    # a button narrower than roughly 2x border-radius lets the rounded
    # corners eat the entire content rect under Qt's stylesheet-based
    # QPushButton painting, rendering the glyph invisible even though it's
    # still technically drawn -- reproduced on a real display, not just a
    # headless/offscreen rendering artifact.
    _BASE_STYLE = (
        "QPushButton {"
        " border: 1px solid #bbb; border-radius: 12px; padding: 2px 4px;"
        " min-width: 22px; min-height: 20px;"
        " background: #fff; color: #333; }"
        "QPushButton:hover { border-color: #888; }"
    )
    _SET_STYLE = "QPushButton { background: #dde9ff; border-color: #7fa8e8; font-weight: bold; }"
    _SELECTED_STYLE = "QPushButton { background: #333; color: #fff; border-color: #333; }"

    def __init__(self, text: str, selected: bool = False, is_set: bool = False, parent=None) -> None:
        super().__init__(text, parent)
        self.set_state(selected=selected, is_set=is_set)

    def set_state(self, selected: bool = False, is_set: bool = False) -> None:
        style = self._BASE_STYLE
        if is_set:
            style += self._SET_STYLE
        if selected:
            style += self._SELECTED_STYLE
        self.setStyleSheet(style)
