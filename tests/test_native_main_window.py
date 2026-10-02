import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication

from digitcode.native.main_window import MainWindow, TAB_TITLES


def _window(gs=None):
    window = MainWindow(gs)
    window._worker.wait()
    QApplication.processEvents()
    return window


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
    window = _window()
    assert window.windowFlags() & Qt.WindowStaysOnTopHint


def test_windows_have_two_tabs_each(qapp):
    window = _window()
    assert [b.text() for b in window.tab_buttons] == TAB_TITLES[:2]
    assert [b.text() for b in window.analysis_window.tab_buttons] == TAB_TITLES[2:]
    assert window.analysis_window.windowFlags() & Qt.WindowStaysOnTopHint
    assert window.analysis_window.parent() is None


def test_clicking_a_tab_switches_the_stack_page(qapp):
    window = _window()
    assert window.stack.currentIndex() == 0
    window.tab_buttons[1].click()
    assert window.stack.currentIndex() == 1
    window.analysis_window.tab_buttons[1].click()
    assert window.analysis_window.stack.currentIndex() == 1
    assert window.stack.currentIndex() == 1


def test_solutions_label_reflects_the_fresh_board_count(qapp):
    window = _window()
    expected = window.game_state.payload()["n_solutions_total"]
    assert str(expected) in window.solutions_label.text()


def test_run_on_contradiction_shows_error_and_keeps_previous_render(qapp):
    window = _window()
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
    window = _window()
    window.show()
    assert window.centralWidget().isEnabled()

    def boom():
        raise TypeError("boom")

    with pytest.raises(TypeError, match="boom"):
        window._run(boom)

    assert window.centralWidget().isEnabled()
    assert window.error_label.isVisible()
    assert "boom" in window.error_label.text()


def test_actions_do_not_disable_input_or_compute_payload_in_gui(qapp, monkeypatch):
    window = _window()
    calls = []
    monkeypatch.setattr(window.centralWidget(), 'setEnabled', calls.append)
    monkeypatch.setattr(window.game_state, 'build_payload_from',
                        lambda *a, **k: pytest.fail('Expensive payload in GUI thread'))
    window._run(window.game_state.undo)
    assert calls == []
    assert window.centralWidget().isEnabled()
    assert window._last_payload['analysis_pending']


def test_mutate_keeps_the_window_enabled_and_renders_after_the_worker_finishes(qapp):
    """_mutate is the async, clue-entry counterpart of _run: the fast
    mutation is instant and the window must never be disabled for it, even
    though the display payload is still being computed on a background
    worker."""
    window = _window()
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
    window = _window()
    window.show()
    chiffres = window.panels[0]

    window._mutate(lambda: window.game_state.apply_clue_fast("row_total", row="K", value=5))

    assert window._worker.isRunning()
    assert chiffres._last_payload["row_totals"] == {"K": 5}
    assert window.game_state.clue.row_totals == {"K": 5}

    window._worker.wait()
    QApplication.processEvents()


def test_mutate_on_contradiction_shows_error_and_does_not_schedule_a_worker(qapp):
    window = _window()
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
    window = _window()
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
    window = _window()
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
    window = _window()
    before = window.solutions_label.text()
    window._generation = 5
    window._on_worker_finished({"n_solutions_total": 999999}, generation=3)
    assert window.solutions_label.text() == before


def test_on_worker_failed_ignores_a_stale_generation(qapp):
    window = _window()
    window._generation = 5
    window._on_worker_failed("boom", generation=3)
    assert not window.error_label.isVisible()


def test_ctrl_wheel_up_increases_opacity(qapp):
    # abs tolerance covers the offscreen QPA's 8-bit opacity quantization,
    # which truncates windowOpacity() to steps of 1/255 (~0.004).
    window = _window()
    window.setWindowOpacity(0.8)
    window.eventFilter(window, _ctrl_wheel_event(120))
    assert window.windowOpacity() == pytest.approx(0.85, abs=0.005)


def test_ctrl_wheel_down_decreases_opacity(qapp):
    window = _window()
    window.setWindowOpacity(0.8)
    window.eventFilter(window, _ctrl_wheel_event(-120))
    assert window.windowOpacity() == pytest.approx(0.75, abs=0.005)


def test_ctrl_wheel_opacity_is_clamped_between_20_and_100_percent(qapp):
    window = _window()
    window.setWindowOpacity(0.22)
    window.eventFilter(window, _ctrl_wheel_event(-120))
    assert window.windowOpacity() == pytest.approx(0.2)

    window.setWindowOpacity(1.0)
    window.eventFilter(window, _ctrl_wheel_event(120))
    assert window.windowOpacity() == pytest.approx(1.0)


def test_wheel_without_ctrl_does_not_change_opacity(qapp):
    window = _window()
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
    window = _window()
    window.show()
    assert window._endgame_worker is None
    assert not window.solutions_panel.endgame_label.isVisible()


def test_small_board_schedules_the_endgame_and_renders_its_result(qapp):
    window = _window(_n4_state())
    window.show()
    window.analysis_window.stack.setCurrentIndex(0)
    assert window._endgame_worker is not None
    assert window.solutions_panel.endgame_label.text() == ENDGAME_PENDING_TEXT

    window._endgame_worker.wait()
    QApplication.processEvents()  # deliver the cross-thread finished_ok signal

    expected = format_endgame(window.game_state.endgame())
    assert window.solutions_panel.endgame_label.text() == expected
    assert window.solutions_panel.endgame_label.isVisible()


def test_schedule_refresh_cancels_the_endgame_and_hides_the_block(qapp):
    window = _window(_n4_state())
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
    window = _window()
    window._endgame_generation = 5
    window._on_endgame_finished({"complete": False, "n_public": 3}, generation=4)
    assert not window.solutions_panel.endgame_label.isVisible()


def test_on_endgame_failed_shows_the_error(qapp):
    window = _window()
    window.show()
    window.analysis_window.stack.setCurrentIndex(0)
    window._on_endgame_failed("boom", generation=window._endgame_generation)
    assert "boom" in window.solutions_panel.endgame_label.text()


def test_endgame_worker_reference_is_cleared_once_it_finishes(qapp):
    window = _window(_n4_state())
    window.show()
    window.analysis_window.stack.setCurrentIndex(0)
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


def test_startup_never_builds_expensive_payload_in_gui(qapp, monkeypatch):
    from digitcode.game_state import GameState
    monkeypatch.setattr(GameState, 'build_payload_from',
                        lambda *a, **k: pytest.fail('Expensive synchronous startup'))
    window = MainWindow()
    assert window._last_payload['n_solutions_total'] is None
    assert window.panels[0]._last_payload['reachable_row_sums']['J']
    assert window.centralWidget().isEnabled()
    window.close()


def test_closing_analysis_closes_both_windows_and_ignores_queued_results(qapp):
    window = MainWindow()
    window.show()
    worker = window._worker
    generation = window._generation
    window.analysis_window.close()
    assert not window.isVisible()
    assert not window.analysis_window.isVisible()
    assert not worker.isRunning()
    window._on_worker_finished({'n_solutions_total': 4}, generation)
    assert window._endgame_worker is None


def test_ctrl_wheel_on_analysis_changes_only_its_opacity(qapp):
    window = MainWindow()
    window.setWindowOpacity(.8)
    window.analysis_window.setWindowOpacity(.8)
    window.eventFilter(window.ev_panel, _ctrl_wheel_event(120))
    assert window.analysis_window.windowOpacity() == pytest.approx(.85, abs=.005)
    assert window.windowOpacity() == pytest.approx(.8, abs=.005)
