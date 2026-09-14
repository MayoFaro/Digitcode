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
