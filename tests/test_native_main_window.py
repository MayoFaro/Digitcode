import pytest
from PySide6.QtCore import Qt

from digitcode.native.main_window import MainWindow, TAB_TITLES


def test_window_is_always_on_top(qapp):
    window = MainWindow()
    assert window.windowFlags() & Qt.WindowStaysOnTopHint


def test_window_has_three_tabs(qapp):
    window = MainWindow()
    assert len(window.tab_buttons) == 3
    assert [b.text() for b in window.tab_buttons] == TAB_TITLES


def test_clicking_a_tab_switches_the_stack_page(qapp):
    window = MainWindow()
    assert window.stack.currentIndex() == 0
    window.tab_buttons[2].click()
    assert window.stack.currentIndex() == 2


def test_solutions_label_reflects_the_fresh_board_count(qapp):
    window = MainWindow()
    expected = window.game_state.payload()["n_solutions_total"]
    assert str(expected) in window.solutions_label.text()


def test_run_on_contradiction_shows_error_and_keeps_previous_render(qapp):
    window = MainWindow()
    # isVisible() reflects the whole ancestor chain, not just this widget's
    # own show()/hide() calls -- the window itself must be shown for the
    # assertion below to mean anything (offscreen platform, so no real
    # window appears on screen).
    window.show()
    window.game_state.apply_clue("parity", pos="T", value="Pair")
    window.game_state.apply_clue("segment", pos="T", seg="b", value=False)
    window._run(window.game_state.payload)
    before = window.solutions_label.text()

    window._run(lambda: window.game_state.apply_clue("segment", pos="T", seg="a", value=False))

    assert window.error_label.isVisible()
    assert window.solutions_label.text() == before


def test_run_on_unexpected_exception_reenables_window_shows_error_and_reraises(qapp):
    """Regression test: fn() raising something other than ValueError used
    to leave the window disabled forever with no error shown (a silently
    frozen window) -- reachable in practice via a panel's click handler
    dereferencing an already-contradictory payload. The fixed _run must
    re-enable the window (via its try/finally) and show an error banner
    on ANY exception, not just ValueError, while still re-raising so a
    real programming error is never silently swallowed."""
    window = MainWindow()
    window.show()
    assert window.centralWidget().isEnabled()

    def boom():
        raise TypeError("boom")

    with pytest.raises(TypeError, match="boom"):
        window._run(boom)

    assert window.centralWidget().isEnabled()
    assert window.error_label.isVisible()
    assert "boom" in window.error_label.text()


def test_run_drains_event_queue_before_reenabling_the_window(qapp, monkeypatch):
    """Regression test for the replayed-click bug: a click made while the
    window is disabled queues in Qt's event queue, and used to be
    delivered (and processed) right after setEnabled(True) re-enabled the
    widget on the success path, because processEvents() ran only at the
    very start of _run. The fix drains the queue (via processEvents())
    while the window is STILL disabled, immediately before the final
    setEnabled(True) -- matching the web app's runMutation, which
    deliberately drops input that arrives mid-request. This spies on the
    two calls to assert that ordering directly, since a full empirical
    repro (posting a real queued click and checking it never fires) is
    hard to make reliable headless."""
    window = MainWindow()
    window.show()

    call_order = []
    central = window.centralWidget()
    real_set_enabled = central.setEnabled

    def spy_set_enabled(value):
        call_order.append(("setEnabled", value))
        return real_set_enabled(value)

    from PySide6.QtWidgets import QApplication
    real_process_events = QApplication.processEvents

    def spy_process_events(*args, **kwargs):
        call_order.append(("processEvents",))
        return real_process_events(*args, **kwargs)

    monkeypatch.setattr(central, "setEnabled", spy_set_enabled)
    monkeypatch.setattr(QApplication, "processEvents", staticmethod(spy_process_events))

    window._run(window.game_state.payload)

    # Find the final setEnabled(True) call and confirm a processEvents()
    # call immediately precedes it, while the window was still disabled.
    assert call_order[-1] == ("setEnabled", True)
    assert call_order[-2] == ("processEvents",)
