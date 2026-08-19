from digitcode.web.app import create_app


def test_get_state_on_fresh_board_returns_full_domains():
    app = create_app()
    client = app.test_client()
    r = client.get("/api/state")
    assert r.status_code == 200
    body = r.get_json()
    assert set(body["domains"].keys()) == {"T", "U", "V", "W", "X", "Y"}
    assert all(len(v) == 10 for v in body["domains"].values())
    assert body["a_me"] == 2
    assert body["a_opp"] == 2
    assert "race" in body and "p_win" in body["race"]


def test_post_clue_parity_narrows_domain():
    app = create_app()
    client = app.test_client()
    r = client.post("/api/clue", json={"type": "parity", "pos": "T", "value": "Pair"})
    assert r.status_code == 200
    assert all(d % 2 == 0 for d in r.get_json()["domains"]["T"])


def test_post_clue_parity_null_value_unsets():
    app = create_app()
    client = app.test_client()
    client.post("/api/clue", json={"type": "parity", "pos": "T", "value": "Pair"})
    r = client.post("/api/clue", json={"type": "parity", "pos": "T", "value": None})
    assert r.status_code == 200
    assert len(r.get_json()["domains"]["T"]) == 10


def test_post_clue_row_total():
    app = create_app()
    client = app.test_client()
    r = client.post("/api/clue", json={"type": "row_total", "row": "J", "value": 3})
    assert r.status_code == 200
    assert r.get_json()["row_totals"]["J"] == 3


def test_post_clue_row_total_null_value_unsets():
    app = create_app()
    client = app.test_client()
    client.post("/api/clue", json={"type": "row_total", "row": "J", "value": 3})
    r = client.post("/api/clue", json={"type": "row_total", "row": "J", "value": None})
    assert r.status_code == 200
    assert "J" not in r.get_json()["row_totals"]


def test_post_clue_col_total():
    app = create_app()
    client = app.test_client()
    r = client.post("/api/clue", json={"type": "col_total", "col": "A", "value": 2})
    assert r.status_code == 200
    assert r.get_json()["col_totals"]["A"] == 2


def test_post_clue_col_total_null_value_unsets():
    app = create_app()
    client = app.test_client()
    client.post("/api/clue", json={"type": "col_total", "col": "A", "value": 2})
    r = client.post("/api/clue", json={"type": "col_total", "col": "A", "value": None})
    assert r.status_code == 200
    assert "A" not in r.get_json()["col_totals"]


def test_post_clue_comparison():
    app = create_app()
    client = app.test_client()
    r = client.post("/api/clue", json={"type": "comparison", "left": "T", "rel": ">", "right": "U"})
    assert r.status_code == 200
    assert ["T", ">", "U"] in r.get_json()["comparisons"]


def test_post_clue_comparison_remove():
    app = create_app()
    client = app.test_client()
    client.post("/api/clue", json={"type": "comparison", "left": "T", "rel": ">", "right": "U"})
    r = client.post("/api/clue", json={"type": "comparison", "left": "T", "rel": ">", "right": "U", "remove": True})
    assert r.status_code == 200
    assert ["T", ">", "U"] not in r.get_json()["comparisons"]


def test_post_clue_segment():
    app = create_app()
    client = app.test_client()
    r = client.post("/api/clue", json={"type": "segment", "pos": "T", "seg": "a", "value": True})
    assert r.status_code == 200
    assert r.get_json()["segment_state"]["Ta"] is True


def test_post_clue_segment_null_value_unsets():
    app = create_app()
    client = app.test_client()
    client.post("/api/clue", json={"type": "segment", "pos": "T", "seg": "a", "value": True})
    r = client.post("/api/clue", json={"type": "segment", "pos": "T", "seg": "a", "value": None})
    assert r.status_code == 200
    assert "Ta" not in r.get_json()["segment_state"]


def test_post_clue_unknown_type_returns_400():
    app = create_app()
    client = app.test_client()
    r = client.post("/api/clue", json={"type": "bogus"})
    assert r.status_code == 400


def test_post_clue_row_total_missing_row_returns_400():
    app = create_app()
    client = app.test_client()
    r = client.post("/api/clue", json={"type": "row_total", "value": 3})
    assert r.status_code == 400
    assert "error" in r.get_json()


def test_post_clue_col_total_missing_col_returns_400():
    app = create_app()
    client = app.test_client()
    r = client.post("/api/clue", json={"type": "col_total", "value": 2})
    assert r.status_code == 400
    assert "error" in r.get_json()


def test_post_clue_parity_missing_pos_returns_400():
    app = create_app()
    client = app.test_client()
    r = client.post("/api/clue", json={"type": "parity", "value": "Pair"})
    assert r.status_code == 400
    assert "error" in r.get_json()


def test_post_clue_comparison_missing_field_returns_400():
    app = create_app()
    client = app.test_client()
    r = client.post("/api/clue", json={"type": "comparison", "left": "T", "rel": ">"})
    assert r.status_code == 400
    assert "error" in r.get_json()


def test_post_clue_segment_missing_seg_returns_400():
    app = create_app()
    client = app.test_client()
    r = client.post("/api/clue", json={"type": "segment", "pos": "T", "value": True})
    assert r.status_code == 400
    assert "error" in r.get_json()


def test_post_clue_missing_field_does_not_leave_orphaned_history_entry():
    app = create_app()
    client = app.test_client()
    client.post("/api/clue", json={"type": "row_total", "value": 3})  # missing "row" -> 400
    r = client.post("/api/clue", json={"type": "row_total", "row": "J", "value": 3})
    assert r.status_code == 200
    assert r.get_json()["row_totals"]["J"] == 3


def test_post_clue_row_total_non_numeric_value_returns_400_without_orphaning_history():
    app = create_app()
    client = app.test_client()
    r = client.post("/api/clue", json={"type": "row_total", "row": "J", "value": "abc"})
    assert r.status_code == 400
    assert "error" in r.get_json()
    # the rejected request must not have written a partial entry ...
    assert client.get("/api/state").get_json()["row_totals"] == {}
    # ... nor pushed an undo entry: the next undo must be a no-op, so the
    # following real clue survives it being applied then undone once.
    r = client.post("/api/clue", json={"type": "row_total", "row": "J", "value": 3})
    assert r.status_code == 200
    assert r.get_json()["row_totals"]["J"] == 3
    r = client.post("/api/undo")
    assert r.get_json()["row_totals"] == {}
    r = client.post("/api/undo")
    assert r.get_json()["row_totals"] == {}


def test_post_clue_col_total_non_numeric_value_returns_400():
    app = create_app()
    client = app.test_client()
    r = client.post("/api/clue", json={"type": "col_total", "col": "A", "value": "abc"})
    assert r.status_code == 400
    assert "error" in r.get_json()
    assert client.get("/api/state").get_json()["col_totals"] == {}


def test_get_state_includes_my_excluded():
    app = create_app()
    client = app.test_client()
    assert client.get("/api/state").get_json()["my_excluded"] == []
    client.post("/api/guess-failed", json={"who": "me", "candidate": [0, 1, 2, 3, 4, 5]})
    assert client.get("/api/state").get_json()["my_excluded"] == ["012 345"]


def test_post_clue_contradiction_rolls_back_and_returns_400():
    app = create_app()
    client = app.test_client()
    client.post("/api/clue", json={"type": "parity", "pos": "T", "value": "Pair"})
    client.post("/api/clue", json={"type": "segment", "pos": "T", "seg": "b", "value": False})
    r = client.post("/api/clue", json={"type": "segment", "pos": "T", "seg": "a", "value": False})
    assert r.status_code == 400
    # state must have rolled back to the pre-contradiction (parity + b=off) state
    r2 = client.get("/api/state")
    assert r2.get_json()["domains"]["T"] == [6]


def test_post_guess_failed_opponent_decrements_a_opp():
    app = create_app()
    client = app.test_client()
    r = client.post("/api/guess-failed", json={"who": "opponent"})
    assert r.status_code == 200
    assert r.get_json()["a_opp"] == 1


def test_post_guess_failed_opponent_floors_at_zero():
    app = create_app()
    client = app.test_client()
    client.post("/api/guess-failed", json={"who": "opponent"})
    client.post("/api/guess-failed", json={"who": "opponent"})
    r = client.post("/api/guess-failed", json={"who": "opponent"})
    assert r.get_json()["a_opp"] == 0


def test_post_guess_failed_me_decrements_a_me_and_excludes_candidate():
    app = create_app()
    client = app.test_client()
    r = client.post("/api/guess-failed", json={"who": "me", "candidate": [0, 1, 2, 3, 4, 5]})
    assert r.status_code == 200
    assert r.get_json()["a_me"] == 1


def test_post_guess_failed_invalid_who_returns_400():
    app = create_app()
    client = app.test_client()
    r = client.post("/api/guess-failed", json={"who": "nobody"})
    assert r.status_code == 400


def test_post_guess_failed_me_missing_candidate_returns_400():
    app = create_app()
    client = app.test_client()
    r = client.post("/api/guess-failed", json={"who": "me"})
    assert r.status_code == 400
    assert "error" in r.get_json()
    assert "candidate" in r.get_json()["error"]


def test_post_undo_restores_previous_clue():
    app = create_app()
    client = app.test_client()
    client.post("/api/clue", json={"type": "row_total", "row": "J", "value": 3})
    r = client.post("/api/undo")
    assert r.status_code == 200
    assert r.get_json()["row_totals"] == {}


def test_post_reset_clears_everything():
    app = create_app()
    client = app.test_client()
    client.post("/api/clue", json={"type": "row_total", "row": "J", "value": 3})
    client.post("/api/guess-failed", json={"who": "opponent"})
    r = client.post("/api/reset")
    body = r.get_json()
    assert body["row_totals"] == {}
    assert body["a_me"] == 2
    assert body["a_opp"] == 2


def test_index_serves_the_frontend_page():
    app = create_app()
    client = app.test_client()
    r = client.get("/")
    assert r.status_code == 200
    assert b"Digitcode" in r.data


def test_static_assets_are_served():
    app = create_app()
    client = app.test_client()
    assert client.get("/app.js").status_code == 200
    assert client.get("/style.css").status_code == 200


def test_get_state_includes_reachable_row_and_col_sums_for_unset_lines():
    app = create_app()
    client = app.test_client()
    r = client.get("/api/state")
    body = r.get_json()
    assert set(body["reachable_row_sums"].keys()) == set("JKLMNOPQRS")
    assert set(body["reachable_col_sums"].keys()) == set("ABCDEFGHI")
    # On a fresh board every row/col has at least one reachable sum.
    assert all(len(v) >= 1 for v in body["reachable_row_sums"].values())
    assert all(len(v) >= 1 for v in body["reachable_col_sums"].values())


def test_get_state_reachable_sums_excludes_already_set_lines():
    app = create_app()
    client = app.test_client()
    client.post("/api/clue", json={"type": "row_total", "row": "J", "value": 3})
    client.post("/api/clue", json={"type": "col_total", "col": "A", "value": 2})
    r = client.get("/api/state")
    body = r.get_json()
    assert "J" not in body["reachable_row_sums"]
    assert "A" not in body["reachable_col_sums"]
    assert "K" in body["reachable_row_sums"]
    assert "B" in body["reachable_col_sums"]


def test_post_clue_comparison_replaces_existing_opposite_relation_same_order():
    app = create_app()
    client = app.test_client()
    client.post("/api/clue", json={"type": "comparison", "left": "T", "rel": ">", "right": "U"})
    r = client.post("/api/clue", json={"type": "comparison", "left": "T", "rel": "<", "right": "U"})
    comparisons = r.get_json()["comparisons"]
    assert ["T", ">", "U"] not in comparisons
    assert ["T", "<", "U"] in comparisons
    assert len(comparisons) == 1


def test_post_clue_comparison_replaces_existing_relation_reversed_order():
    app = create_app()
    client = app.test_client()
    client.post("/api/clue", json={"type": "comparison", "left": "T", "rel": ">", "right": "U"})
    # Submitting U<T is a different literal request but the same logical
    # claim as T>U already on file -- must not create a duplicate entry.
    r = client.post("/api/clue", json={"type": "comparison", "left": "U", "rel": "<", "right": "T"})
    comparisons = r.get_json()["comparisons"]
    assert len(comparisons) == 1
    # Submitting the logically opposite claim (U>T, i.e. T<U) must replace it.
    r = client.post("/api/clue", json={"type": "comparison", "left": "U", "rel": ">", "right": "T"})
    comparisons = r.get_json()["comparisons"]
    assert len(comparisons) == 1
    assert ["T", ">", "U"] not in comparisons and ["U", ">", "T"] in comparisons
