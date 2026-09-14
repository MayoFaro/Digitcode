from PySide6.QtWidgets import QPushButton

from digitcode.game_state import GameState
from digitcode.native.panels.chiffres_panel import ChiffresPanel


def test_refresh_shows_full_domains_on_a_fresh_board(qapp):
    gs = GameState()
    panel = ChiffresPanel(gs, run=lambda fn: fn())
    panel.refresh(gs.payload())
    assert "0" in panel.domain_labels["T"].text()
    assert "9" in panel.domain_labels["T"].text()


def test_selecting_a_row_letter_then_a_value_sets_the_row_total(qapp):
    gs = GameState()
    panel = ChiffresPanel(gs, run=lambda fn: fn())
    panel.refresh(gs.payload())

    panel._select_row_letter("J")
    reachable = gs.payload()["reachable_row_sums"]["J"]
    target = reachable[0]
    panel._run(lambda: gs.apply_clue("row_total", row="J", value=target))

    assert gs.clue.row_totals["J"] == target


def test_selecting_a_different_letter_does_not_mutate_game_state(qapp):
    gs = GameState()
    panel = ChiffresPanel(gs, run=lambda fn: fn())
    panel.refresh(gs.payload())
    panel._select_row_letter("K")
    assert gs.clue.row_totals == {}


def test_back_to_back_refreshes_leave_no_orphaned_chip_widgets(qapp):
    """Regression test for the _clear_layout bug: deleteLater() alone
    leaves a removed chip parented (and painting) until the event loop
    next processes deferred deletes. Two refresh() calls in a row with no
    intervening QApplication.processEvents() used to leave the first
    call's chips still parented under the panel alongside the second
    call's freshly-created ones. The fix (setParent(None) before
    deleteLater()) unparents immediately, so the widget count right after
    a back-to-back refresh must match a single fresh refresh() landing on
    the same final state -- not the sum of both refreshes' chip counts."""
    gs = GameState()
    payload = gs.payload()

    panel = ChiffresPanel(gs, run=lambda fn: fn())
    panel._selected_row_letter = "J"
    panel.refresh(payload)
    # No QApplication.processEvents() call here -- deliberately, to
    # reproduce the orphaned-widget window.
    panel._selected_row_letter = "K"
    panel.refresh(payload)
    double_refresh_count = len(panel.findChildren(QPushButton))

    fresh_panel = ChiffresPanel(gs, run=lambda fn: fn())
    fresh_panel._selected_row_letter = "K"
    fresh_panel.refresh(payload)
    single_refresh_count = len(fresh_panel.findChildren(QPushButton))

    assert double_refresh_count == single_refresh_count
