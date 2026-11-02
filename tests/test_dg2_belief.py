from digitcode.dg2_belief import condition, initial_worlds, opponent_hit_rate


def test_hidden_failure_is_never_the_secret_and_changes_hit_rate():
    worlds = initial_worlds(0b111, 1)
    assert len(worlds) == 6
    assert all(world.secret != world.opponent_failed for world in worlds)
    assert opponent_hit_rate(worlds, 0b111) == 0.5


def test_public_answer_updates_worlds_without_revealing_hidden_failure():
    worlds = condition(initial_worlds(0b111, 1), 0b011)
    assert {world.secret for world in worlds} == {0, 1}
    assert any(world.opponent_failed is None for world in worlds)
