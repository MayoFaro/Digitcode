from digitcode.game_state import GameState
from digitcode.native.endgame_worker import EndgameWorker

from tests.test_game_state import _n4_state


def _worker(gs, generation=1):
    return EndgameWorker(gs.clue, gs.a_me, gs.a_opp, gs.my_excluded, gs.opp_fail_pool_size, generation)


def test_run_emits_the_endgame_result(qapp):
    gs = _n4_state()
    worker = _worker(gs, generation=3)
    received = []
    worker.finished_ok.connect(lambda res, gen: received.append((res, gen)))
    worker.run()  # direct call: runs on the test thread, deterministic
    assert len(received) == 1
    res, gen = received[0]
    assert gen == 3
    assert res == gs.endgame()


def test_run_emits_none_on_a_wide_board(qapp):
    gs = GameState()
    worker = _worker(gs)
    received = []
    worker.finished_ok.connect(lambda res, gen: received.append(res))
    worker.run()
    assert received == [None]


def test_run_emits_nothing_when_cancelled_before_starting(qapp):
    gs = _n4_state()
    worker = _worker(gs)
    worker.cancel()
    ok, failed = [], []
    worker.finished_ok.connect(lambda res, gen: ok.append(res))
    worker.failed.connect(lambda msg, gen: failed.append(msg))
    worker.run()
    assert ok == [] and failed == []


def test_run_emits_failed_on_an_unexpected_exception(qapp, monkeypatch):
    gs = _n4_state()
    worker = _worker(gs, generation=9)

    def boom(*args, **kwargs):
        raise TypeError("boom")

    monkeypatch.setattr(GameState, "build_endgame_from", staticmethod(boom))
    failed = []
    worker.failed.connect(lambda msg, gen: failed.append((msg, gen)))
    worker.run()
    assert failed == [("boom", 9)]
