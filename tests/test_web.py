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


def test_post_clue_col_total():
    app = create_app()
    client = app.test_client()
    r = client.post("/api/clue", json={"type": "col_total", "col": "A", "value": 2})
    assert r.status_code == 200
    assert r.get_json()["col_totals"]["A"] == 2


def test_post_clue_comparison():
    app = create_app()
    client = app.test_client()
    r = client.post("/api/clue", json={"type": "comparison", "left": "T", "rel": ">", "right": "U"})
    assert r.status_code == 200
    assert ["T", ">", "U"] in r.get_json()["comparisons"]


def test_post_clue_segment():
    app = create_app()
    client = app.test_client()
    r = client.post("/api/clue", json={"type": "segment", "pos": "T", "seg": "a", "value": True})
    assert r.status_code == 200
    assert r.get_json()["segment_state"]["Ta"] is True


def test_post_clue_unknown_type_returns_400():
    app = create_app()
    client = app.test_client()
    r = client.post("/api/clue", json={"type": "bogus"})
    assert r.status_code == 400


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
