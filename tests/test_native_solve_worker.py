from digitcode.game_state import GameState
from digitcode.native.solve_worker import SolveWorker


def test_run_emits_finished_ok_with_the_expected_payload(qapp):
    gs = GameState()
    gs.apply_clue("row_total", row="J", value=3)
    worker = SolveWorker(gs.clue, gs.a_me, gs.a_opp, gs.my_excluded, generation=1)

    received = []
    worker.finished_ok.connect(lambda payload, gen: received.append((payload, gen)))
    # Calling run() directly (not start()) executes it on the test thread
    # itself -- deterministic, no real OS thread involved.
    worker.run()

    assert len(received) == 1
    payload, generation = received[0]
    assert generation == 1
    expected = gs.payload()
    assert expected.pop("result") is None
    assert payload == expected


def test_run_emits_nothing_when_cancelled_before_starting(qapp):
    gs = GameState()
    worker = SolveWorker(gs.clue, gs.a_me, gs.a_opp, gs.my_excluded, generation=1)
    worker.cancel()

    ok_received = []
    failed_received = []
    worker.finished_ok.connect(lambda payload, gen: ok_received.append((payload, gen)))
    worker.failed.connect(lambda message, gen: failed_received.append((message, gen)))
    worker.run()

    assert ok_received == []
    assert failed_received == []


def test_run_emits_failed_on_an_unexpected_exception(qapp, monkeypatch):
    gs = GameState()
    worker = SolveWorker(gs.clue, gs.a_me, gs.a_opp, gs.my_excluded, generation=7)

    def boom(*args, **kwargs):
        raise TypeError("boom")

    monkeypatch.setattr(GameState, "build_payload_from", staticmethod(boom))

    failed_received = []
    worker.failed.connect(lambda message, gen: failed_received.append((message, gen)))
    worker.run()

    assert len(failed_received) == 1
    message, generation = failed_received[0]
    assert "boom" in message
    assert generation == 7
