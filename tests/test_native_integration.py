from digitcode.native.main_window import MainWindow


def test_setting_a_row_total_from_the_chiffres_panel_updates_every_panel(qapp):
    window = MainWindow()
    chiffres, comparaisons, solutions = window.panels

    chiffres._select_row_letter("J")
    reachable = window.game_state.payload()["reachable_row_sums"]["J"]
    target_value = reachable[0]
    window._run(lambda: window.game_state.apply_clue("row_total", row="J", value=target_value))

    after_payload = window.game_state.payload()
    assert window.solutions_label.text() == f"Solutions restantes : {after_payload['n_solutions_total']}"
    assert solutions.my_miss_combo.count() == len(after_payload["solutions"])
    assert chiffres.domain_labels["T"].text().startswith("<b>T</b>")


def test_a_rejected_clue_leaves_every_panel_unchanged(qapp):
    window = MainWindow()
    # isVisible() reflects the whole ancestor chain, not just this widget's
    # own hide()/show() calls -- it is always False until the top-level
    # window itself is shown (see tests/test_native_main_window.py).
    window.show()
    chiffres, comparaisons, solutions = window.panels

    # Same contradiction fixture as tests/test_web.py's
    # test_post_clue_contradiction_rolls_back_and_returns_400: parity Pair on
    # T plus segment b=False forces T's domain down to {6} (6 is the only
    # even digit whose segments exclude "b"), which needs segment a ON --
    # explicitly setting it OFF is a genuine contradiction, not one a
    # fallback cycle would silently step around.
    window.game_state.apply_clue("parity", pos="T", value="Pair")
    window.game_state.apply_clue("segment", pos="T", seg="b", value=False)
    window._run(window.game_state.payload)
    domains_before = chiffres.domain_labels["T"].text()
    trace_before = solutions.trace_view.toPlainText()

    window._run(lambda: window.game_state.apply_clue("segment", pos="T", seg="a", value=False))

    assert window.error_label.isVisible()
    assert chiffres.domain_labels["T"].text() == domains_before
    assert solutions.trace_view.toPlainText() == trace_before
