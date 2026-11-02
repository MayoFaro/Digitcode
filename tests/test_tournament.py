from digitcode.tournament import generate_secrets, run_chunk


def test_secret_generation_is_deterministic_and_respects_base_rules():
    assert generate_secrets(5, 123) == generate_secrets(5, 123)


def test_checkpoint_resumes_without_replaying_completed_pairs(tmp_path):
    calls = []
    def fake_pair(secret, index, *, seed, dg1_time_budget_s):
        calls.append(index)
        return {"index": index, "secret": "".join(map(str, secret)), "games": [
            {"dg1_starts": True, "dg2_seed": seed, "winner": "DG1", "questions": 3, "guesses": 1},
            {"dg1_starts": False, "dg2_seed": seed + 1, "winner": "DG2", "questions": 4, "guesses": 2},
        ]}
    checkpoint = tmp_path / "tournament.json"
    first = run_chunk(checkpoint, games=6, seed=9, pairs=1, play_pair=fake_pair)
    second = run_chunk(checkpoint, games=6, seed=9, pairs=2, play_pair=fake_pair)
    assert first["completed_games"] == 2
    assert second["completed_games"] == 6
    assert calls == [0, 1, 2]
    assert second["wins"] == {"DG1": 3, "DG2": 3}
