import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication

from digitcode.native.main_window import MainWindow, TAB_TITLES


def _ctrl_wheel_event(delta_y: int) -> QWheelEvent:
    return QWheelEvent(
        QPointF(0, 0),
        QPointF(0, 0),
        QPoint(0, 0),
        QPoint(0, delta_y),
        Qt.NoButton,
        Qt.ControlModifier,
        Qt.NoScrollPhase,
        False,
    )


def test_window_is_always_on_top(qapp):
    window = MainWindow()
    assert window.windowFlags() & Qt.WindowStaysOnTopHint


def test_window_has_four_tabs(qapp):
    window = MainWindow()
    assert len(window.tab_buttons) == 4
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


def test_mutate_keeps_the_window_enabled_and_renders_after_the_worker_finishes(qapp):
    """_mutate is the async, clue-entry counterpart of _run: the fast
    mutation is instant and the window must never be disabled for it, even
    though the display payload is still being computed on a background
    worker."""
    window = MainWindow()
    window.show()
    assert window.centralWidget().isEnabled()

    reachable = window.game_state.payload()["reachable_row_sums"]["J"]
    target = reachable[0]
    window._mutate(lambda: window.game_state.apply_clue_fast("row_total", row="J", value=target))

    assert window.game_state.clue.row_totals["J"] == target
    assert window.centralWidget().isEnabled()

    window._worker.wait()
    QApplication.processEvents()  # deliver the cross-thread finished_ok signal

    expected = window.game_state.payload()["n_solutions_total"]
    assert window.solutions_label.text() == f"Solutions restantes : {expected}"
    assert not window.busy_label.isVisible()


def test_mutate_renders_the_new_clue_immediately_before_the_worker_finishes(qapp):
    """Regression test: a real user reported that the window felt
    unresponsive after a click even though it technically wasn't blocked --
    _mutate used to only start the background worker without ever
    re-rendering, so nothing on screen showed the just-entered clue until
    the (much slower) full payload eventually arrived. _render_quick must
    make the panels reflect the new clue state synchronously, before the
    worker has had a chance to finish."""
    window = MainWindow()
    window.show()
    chiffres = window.panels[0]

    window._mutate(lambda: window.game_state.apply_clue_fast("row_total", row="K", value=5))

    assert window._worker.isRunning()
    assert chiffres._last_payload["row_totals"] == {"K": 5}
    assert window.game_state.clue.row_totals == {"K": 5}

    window._worker.wait()
    QApplication.processEvents()


def test_mutate_on_contradiction_shows_error_and_does_not_schedule_a_worker(qapp):
    window = MainWindow()
    window.show()
    window.game_state.apply_clue("parity", pos="T", value="Pair")
    window.game_state.apply_clue("segment", pos="T", seg="b", value=False)
    window._schedule_refresh()
    window._worker.wait()
    QApplication.processEvents()
    generation_before = window._generation

    window._mutate(lambda: window.game_state.apply_clue_fast("segment", pos="T", seg="a", value=False))

    assert window.error_label.isVisible()
    assert window._generation == generation_before


def test_schedule_refresh_cancels_the_previous_worker(qapp):
    window = MainWindow()
    window._schedule_refresh()
    first_worker = window._worker

    window._schedule_refresh()

    assert first_worker._cancel_event.is_set()
    window._worker.wait()
    QApplication.processEvents()


def test_rapid_successive_mutations_do_not_crash_and_settle_on_the_last_state(qapp):
    """Regression test for a real crash found via manual verification:
    superseding a worker by just reassigning window._worker dropped its
    only Python reference while the OS thread could still be running --
    PySide6 aborts the process with "QThread: Destroyed while thread is
    still running" in that case. Firing several mutations back-to-back
    (without waiting for each one's worker to finish first) must survive
    and eventually settle on the payload for the LAST clue state.

    Uses three transitions on the SAME field (each replaces the previous
    parity constraint outright, never compounds it) rather than three
    different row totals: stacking independently-computed row totals can
    legitimately reject a later one for solver reasons unrelated to this
    test (reachable_row_sums reflects only local per-position domains,
    not full joint feasibility once another row is also fixed -- a
    pre-existing solver characteristic, not what's being tested here).
    This test is purely about surviving rapid worker supersession, so it
    deliberately avoids that unrelated edge case."""
    window = MainWindow()
    window.show()

    for value in ["Pair", "Impair", "Pair"]:
        window._mutate(lambda v=value: window.game_state.apply_clue_fast("parity", pos="T", value=v))
        QApplication.processEvents()

    assert window.game_state.clue.parity["T"] == "Pair"

    # Let every superseded worker actually finish before the test process
    # exits -- otherwise a leftover running QThread at interpreter shutdown
    # can itself trigger the same abort.
    for worker in list(window._retired_workers) + [window._worker]:
        worker.wait()
        QApplication.processEvents()

    expected = window.game_state.payload()["n_solutions_total"]
    assert window.solutions_label.text() == f"Solutions restantes : {expected}"


def test_on_worker_finished_ignores_a_stale_generation(qapp):
    window = MainWindow()
    before = window.solutions_label.text()
    window._generation = 5
    window._on_worker_finished({"n_solutions_total": 999999}, generation=3)
    assert window.solutions_label.text() == before


def test_on_worker_failed_ignores_a_stale_generation(qapp):
    window = MainWindow()
    window._generation = 5
    window._on_worker_failed("boom", generation=3)
    assert not window.error_label.isVisible()


def test_ctrl_wheel_up_increases_opacity(qapp):
    # abs tolerance covers the offscreen QPA's 8-bit opacity quantization,
    # which truncates windowOpacity() to steps of 1/255 (~0.004).
    window = MainWindow()
    window.setWindowOpacity(0.8)
    window.eventFilter(window, _ctrl_wheel_event(120))
    assert window.windowOpacity() == pytest.approx(0.85, abs=0.005)


def test_ctrl_wheel_down_decreases_opacity(qapp):
    window = MainWindow()
    window.setWindowOpacity(0.8)
    window.eventFilter(window, _ctrl_wheel_event(-120))
    assert window.windowOpacity() == pytest.approx(0.75, abs=0.005)


def test_ctrl_wheel_opacity_is_clamped_between_20_and_100_percent(qapp):
    window = MainWindow()
    window.setWindowOpacity(0.22)
    window.eventFilter(window, _ctrl_wheel_event(-120))
    assert window.windowOpacity() == pytest.approx(0.2)

    window.setWindowOpacity(1.0)
    window.eventFilter(window, _ctrl_wheel_event(120))
    assert window.windowOpacity() == pytest.approx(1.0)


def test_wheel_without_ctrl_does_not_change_opacity(qapp):
    window = MainWindow()
    window.setWindowOpacity(0.8)
    event = QWheelEvent(
        QPointF(0, 0),
        QPointF(0, 0),
        QPoint(0, 0),
        QPoint(0, 120),
        Qt.NoButton,
        Qt.NoModifier,
        Qt.NoScrollPhase,
        False,
    )
    window.eventFilter(window, event)
    assert window.windowOpacity() == pytest.approx(0.8)


from digitcode.native.panels.endgame_format import ENDGAME_PENDING_TEXT, format_endgame

from tests.test_game_state import _n4_state


def test_endgame_block_is_hidden_on_a_fresh_board(qapp):
    window = MainWindow()
    window.show()
    assert window._endgame_worker is None
    assert not window.solutions_panel.endgame_label.isVisible()


def test_small_board_schedules_the_endgame_and_renders_its_result(qapp):
    window = MainWindow(_n4_state())
    window.show()
    window.stack.setCurrentIndex(2)
    assert window._endgame_worker is not None
    assert window.solutions_panel.endgame_label.text() == ENDGAME_PENDING_TEXT

    window._endgame_worker.wait()
    QApplication.processEvents()  # deliver the cross-thread finished_ok signal

    expected = format_endgame(window.game_state.endgame())
    assert window.solutions_panel.endgame_label.text() == expected
    assert window.solutions_panel.endgame_label.isVisible()


def test_schedule_refresh_cancels_the_endgame_and_hides_the_block(qapp):
    window = MainWindow(_n4_state())
    window.show()
    endgame_worker = window._endgame_worker
    window._schedule_refresh()
    assert endgame_worker._cancel_event.is_set()
    assert not window.solutions_panel.endgame_label.isVisible()
    for worker in list(window._retired_workers) + [window._worker]:
        worker.wait()
    QApplication.processEvents()  # the refreshed payload reschedules an endgame search
    if window._endgame_worker is not None:
        window._endgame_worker.wait()
        QApplication.processEvents()


def test_on_endgame_finished_ignores_a_stale_generation(qapp):
    window = MainWindow()
    window._endgame_generation = 5
    window._on_endgame_finished({"complete": False, "n_public": 3}, generation=4)
    assert not window.solutions_panel.endgame_label.isVisible()


def test_on_endgame_failed_shows_the_error(qapp):
    window = MainWindow()
    window.show()
    window.stack.setCurrentIndex(2)
    window._on_endgame_failed("boom", generation=window._endgame_generation)
    assert "boom" in window.solutions_panel.endgame_label.text()


def test_endgame_worker_reference_is_cleared_once_it_finishes(qapp):
    window = MainWindow(_n4_state())
    window.show()
    window.stack.setCurrentIndex(2)
    worker = window._endgame_worker
    assert worker is not None

    worker.wait()
    QApplication.processEvents()  # deliver finished_ok, then QThread.finished -> _cleanup_worker

    assert window._endgame_worker is None
    assert worker not in window._retired_workers

    retired_before = len(window._retired_workers)
    window._cancel_endgame()  # must not resurrect/append the dead worker
    assert len(window._retired_workers) == retired_before

    window._schedule_endgame({"n_solutions_total": 4})  # must not grow _retired_workers either
    assert len(window._retired_workers) == retired_before
    window._endgame_worker.wait()
    QApplication.processEvents()
