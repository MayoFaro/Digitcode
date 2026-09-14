from digitcode.game_state import GameState
from digitcode.native.panels.comparaisons_panel import ComparaisonsPanel


def test_refresh_reflects_an_existing_comparison(qapp):
    gs = GameState()
    gs.apply_clue("comparison", left="T", rel=">", right="U")
    panel = ComparaisonsPanel(gs, run=lambda fn: fn())
    panel.refresh(gs.payload())
    lt_chip, gt_chip = panel.cmp_chip_pairs[("T", "U")]
    assert gt_chip.styleSheet() != lt_chip.styleSheet()


def test_clicking_a_comparison_chip_sets_the_relation(qapp):
    gs = GameState()
    panel = ComparaisonsPanel(gs, run=lambda fn: fn())
    panel.refresh(gs.payload())
    panel._on_comparison_clicked("T", "U", ">")
    assert ("T", ">", "U") in gs.clue.comparisons


def test_clicking_the_same_comparison_chip_again_clears_it(qapp):
    gs = GameState()
    panel = ComparaisonsPanel(gs, run=lambda fn: fn())
    panel.refresh(gs.payload())
    panel._on_comparison_clicked("T", "U", ">")
    panel.refresh(gs.payload())
    panel._on_comparison_clicked("T", "U", ">")
    assert gs.clue.comparisons == []


def test_clicking_a_parity_chip_cycles_through_pair_impair_unset(qapp):
    gs = GameState()
    panel = ComparaisonsPanel(gs, run=lambda fn: fn())
    panel.refresh(gs.payload())

    panel._on_parity_clicked("T")
    assert gs.clue.parity["T"] == "Pair"

    panel.refresh(gs.payload())
    panel._on_parity_clicked("T")
    assert gs.clue.parity["T"] == "Impair"

    panel.refresh(gs.payload())
    panel._on_parity_clicked("T")
    assert "T" not in gs.clue.parity


def test_clicking_a_segment_cycles_through_on_off_unset(qapp):
    gs = GameState()
    panel = ComparaisonsPanel(gs, run=lambda fn: fn())
    panel.refresh(gs.payload())

    panel._on_segment_clicked("T", "a", None)
    assert gs.clue.segment_state[("T", "a")] is True

    panel.refresh(gs.payload())
    panel._on_segment_clicked("T", "a", True)
    assert gs.clue.segment_state[("T", "a")] is False

    panel.refresh(gs.payload())
    panel._on_segment_clicked("T", "a", False)
    assert ("T", "a") not in gs.clue.segment_state
