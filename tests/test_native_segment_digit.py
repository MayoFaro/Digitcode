from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QMouseEvent

from digitcode.native.widgets.segment_digit import SegmentDigit


def _click_at(widget, x, y):
    event = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress, QPointF(x, y),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
    )
    widget.mousePressEvent(event)


def test_click_inside_segment_a_emits_its_letter_and_current_value(qapp):
    widget = SegmentDigit("T")
    received = []
    widget.segment_clicked.connect(lambda seg, current: received.append((seg, current)))
    _click_at(widget, 60, 16)  # (30, 8) in the 60x100 grid, scaled x2 -- inside segment "a"
    assert received == [("a", None)]


def test_click_outside_every_segment_emits_nothing(qapp):
    widget = SegmentDigit("T")
    received = []
    widget.segment_clicked.connect(lambda seg, current: received.append((seg, current)))
    _click_at(widget, 1, 1)  # top-left corner, outside every polygon
    assert received == []


def test_set_segment_state_is_reported_on_the_next_click(qapp):
    widget = SegmentDigit("T")
    widget.set_segment_state({"a": True})
    received = []
    widget.segment_clicked.connect(lambda seg, current: received.append((seg, current)))
    _click_at(widget, 60, 16)
    assert received == [("a", True)]
