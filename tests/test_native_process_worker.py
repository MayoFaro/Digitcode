"""Real spawned-process checks: isolation, UI responsiveness and shutdown."""
import os
import time

from PySide6.QtCore import QEventLoop, QTimer

from digitcode.native.process_worker import ProcessWorker


def cpu_analysis(args, should_cancel, publish):
    publish({'pid': os.getpid()})
    started = time.monotonic()
    value = 0
    while args is None or time.monotonic() - started < args:
        if should_cancel():
            return None
        for _ in range(2000):
            value = (value + 17) % 100003
    publish({'pid': os.getpid(), 'value': value})
    return {'pid': os.getpid(), 'value': value}


def test_cpu_search_has_its_own_pid_and_keeps_qt_heartbeat_running(qapp):
    worker = ProcessWorker(cpu_analysis, .8, 42)
    seen, results, errors, beats = [], [], [], []
    loop = QEventLoop()
    heartbeat = QTimer()
    heartbeat.setInterval(10)
    heartbeat.timeout.connect(lambda: beats.append(time.monotonic()))
    worker.progress.connect(lambda r, g: seen.append((r, g)))
    worker.finished_ok.connect(lambda r, g: results.append((r, g)))
    worker.failed.connect(lambda *a: errors.append(a))
    worker.finished.connect(loop.quit)
    timeout = QTimer()
    timeout.setSingleShot(True)
    timeout.timeout.connect(loop.quit)
    try:
        heartbeat.start()
        timeout.start(10000)
        worker.start()
        loop.exec()
        assert not errors
        assert results and results[0][1] == 42
        assert results[0][0]['pid'] != os.getpid()
        assert seen and seen[0][1] == 42
        assert len(beats) >= 30
        assert max(b - a for a, b in zip(beats, beats[1:])) < .3
    finally:
        heartbeat.stop()
        timeout.stop()
        worker.cancel()
        worker.wait()


def test_cancelling_unlimited_search_reaps_the_child(qapp):
    worker = ProcessWorker(cpu_analysis, None, 1)
    loop = QEventLoop()
    seen, results = [], []
    worker.progress.connect(lambda r, g: (seen.append(r), loop.quit()))
    worker.finished_ok.connect(lambda *a: results.append(a))
    timeout = QTimer()
    timeout.setSingleShot(True)
    timeout.timeout.connect(loop.quit)
    try:
        timeout.start(10000)
        worker.start()
        loop.exec()
        assert seen and seen[0]['pid'] != os.getpid()
        worker.cancel()
        assert worker.wait(3000)
        assert worker._process is None
        assert not results
    finally:
        timeout.stop()
        worker.cancel()
        worker.wait()
