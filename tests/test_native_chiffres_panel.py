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
