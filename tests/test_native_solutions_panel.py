from digitcode.game_state import GameState
from digitcode.native.panels.solutions_panel import SolutionsPanel


def _n4_game_state() -> GameState:
    # Same fixture as tests/test_web.py's _n4_clue_client: narrows the
    # board to a fixed N=4 so the solutions list is short enough to render
    # inline and the combo box is easy to assert on.
    gs = GameState()
    for row, val in (("K", 6), ("S", 1)):
        gs.apply_clue("row_total", row=row, value=val)
    for col, val in (("H", 3), ("C", 3), ("E", 1)):
        gs.apply_clue("col_total", col=col, value=val)
    for pos, par in (("T", "Pair"), ("W", "Pair"), ("Y", "Pair"), ("X", "Impair")):
        gs.apply_clue("parity", pos=pos, value=par)
    return gs


def test_refresh_lists_all_solutions_when_total_is_small(qapp):
    gs = _n4_game_state()
    payload = gs.payload()
    panel = SolutionsPanel(gs, run=lambda fn: fn())
    panel.refresh(payload)
    assert panel.my_miss_combo.count() == 4
    assert panel.solutions_list_label.text() == "; ".join(payload["solutions"])


def test_undo_button_calls_game_state_undo(qapp):
    gs = _n4_game_state()
    panel = SolutionsPanel(gs, run=lambda fn: fn())
    panel.refresh(gs.payload())
    history_len_before = len(gs.history)
    panel.undo_btn.click()
    assert len(gs.history) == history_len_before - 1


def test_opp_miss_button_decrements_a_opp(qapp):
    gs = GameState()
    panel = SolutionsPanel(gs, run=lambda fn: fn())
    panel.refresh(gs.payload())
    panel.opp_miss_btn.click()
    assert gs.a_opp == 1


def test_my_miss_button_excludes_the_selected_candidate(qapp):
    gs = _n4_game_state()
    payload = gs.payload()
    panel = SolutionsPanel(gs, run=lambda fn: fn())
    panel.refresh(payload)
    panel.my_miss_combo.setCurrentIndex(0)
    panel.my_miss_btn.click()
    assert gs.a_me == 1
    assert len(gs.my_excluded) == 1


def test_refresh_shows_the_attempts_counts(qapp):
    gs = GameState()
    panel = SolutionsPanel(gs, run=lambda fn: fn())
    panel.refresh(gs.payload())
    assert "2" in panel.a_me_label.text()
    assert "2" in panel.a_opp_label.text()
