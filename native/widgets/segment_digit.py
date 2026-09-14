from __future__ import annotations

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtWidgets import QWidget

SEGMENTS = ["a", "b", "c", "d", "e", "f", "g"]

# Trapezoid outlines for each of the 7 segments on a 0..60 x 0..100 grid --
# same coordinates as web/static/app.js's SEGMENT_POINTS, so the shape
# matches the web version exactly. A recognizable seven-segment digit,
# not a pixel-perfect replica of the real game's glyph.
_SEGMENT_POINTS = {
    "a": [(16, 4), (44, 4), (40, 12), (20, 12)],
    "f": [(8, 12), (16, 16), (16, 46), (8, 50)],
    "b": [(52, 12), (44, 16), (44, 46), (52, 50)],
    "g": [(16, 46), (40, 46), (44, 50), (40, 54), (16, 54), (12, 50)],
    "e": [(8, 52), (16, 56), (16, 86), (8, 90)],
    "c": [(52, 52), (44, 56), (44, 86), (52, 90)],
    "d": [(20, 88), (40, 88), (44, 96), (16, 96)],
}

_SCALE = 2.0
_GRID_WIDTH = 60
_GRID_HEIGHT = 100

_COLOR_ON = QColor("#333333")
_COLOR_OFF_HATCH = QColor("#cc6666")
_COLOR_UNKNOWN = QColor(0, 0, 0, 0)
_STROKE = QColor("#999999")
_STROKE_HOVER = QColor("#333333")


class SegmentDigit(QWidget):
    """A clickable seven-segment digit for one board position, cycling
    each segment through on / off / unknown on click -- the native
    equivalent of buildDigitSvg in web/static/app.js. Emits
    `segment_clicked(seg, current)` and leaves the actual GameState
    transition (with its fallback retries) to the owning panel, same
    separation as ChipButton.
    """

    segment_clicked = Signal(str, object)  # (segment, current value: True/False/None)

    def __init__(self, pos: str, parent=None) -> None:
        super().__init__(parent)
        self.pos = pos
        self._segment_state: dict[str, bool | None] = {s: None for s in SEGMENTS}
        self._paths: dict[str, QPainterPath] = {}
        self._hovered: str | None = None
        self.setFixedSize(int(_GRID_WIDTH * _SCALE), int(_GRID_HEIGHT * _SCALE))
        self.setMouseTracking(True)
        self._build_paths()

    def _build_paths(self) -> None:
        for seg, points in _SEGMENT_POINTS.items():
            polygon = QPolygonF([QPointF(x * _SCALE, y * _SCALE) for x, y in points])
            path = QPainterPath()
            path.addPolygon(polygon)
            path.closeSubpath()
            self._paths[seg] = path

    def set_segment_state(self, state: dict[str, bool | None]) -> None:
        """`state` maps segment letter -> True/False/None (unknown)."""
        self._segment_state = dict(state)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        for seg, path in self._paths.items():
            current = self._segment_state.get(seg)
            if current is True:
                brush = QBrush(_COLOR_ON)
            elif current is False:
                brush = QBrush(_COLOR_OFF_HATCH, Qt.BDiagPattern)
            else:
                brush = QBrush(_COLOR_UNKNOWN)
            painter.setBrush(brush)
            pen = QPen(_STROKE_HOVER if seg == self._hovered else _STROKE)
            pen.setWidthF(1.5 if seg == self._hovered else 1.0)
            painter.setPen(pen)
            painter.drawPath(path)

    def _segment_at(self, pos: QPointF) -> str | None:
        for seg, path in self._paths.items():
            if path.contains(pos):
                return seg
        return None

    def mouseMoveEvent(self, event) -> None:
        seg = self._segment_at(event.position())
        if seg != self._hovered:
            self._hovered = seg
            self.update()

    def mousePressEvent(self, event) -> None:
        seg = self._segment_at(event.position())
        if seg is not None:
            self.segment_clicked.emit(seg, self._segment_state.get(seg))
