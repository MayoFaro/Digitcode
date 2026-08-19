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
