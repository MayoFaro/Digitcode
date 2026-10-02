"""Qt signal bridge to a spawned computation process, isolated from the UI GIL."""
from __future__ import annotations

import multiprocessing
import os
import threading
import time
import traceback

from PySide6.QtCore import QThread, Signal

from ..solver import Cancelled


def _process_main(compute, args, connection, cancelled):
    try:
        # Leave interactive work ahead of CPU-heavy analysis on Linux.
        if hasattr(os, "nice"):
            os.nice(5)
        last_publication = 0.0

        def publish(result):
            nonlocal last_publication
            now = time.monotonic()
            if now - last_publication >= 0.1:
                connection.send(("progress", result))
                last_publication = now

        result = compute(args, cancelled.is_set, publish)
        if not cancelled.is_set():
            connection.send(("result", result))
    except Cancelled:
        pass
    except Exception as exc:
        traceback.print_exc()
        connection.send(("error", str(exc)))
    finally:
        connection.close()


class ProcessWorker(QThread):
    finished_ok = Signal(object, int)
    progress = Signal(object, int)
    failed = Signal(str, int)

    def __init__(self, compute, args, generation, parent=None):
        super().__init__(parent)
        self._compute = compute
        self._args = args
        self.generation = generation
        self._cancel_event = threading.Event()
        self._process = None

    def cancel(self):
        self._cancel_event.set()

    def run(self):
        if self._cancel_event.is_set():
            return
        # Direct invocation is useful for deterministic unit tests. start()
        # always takes the isolated process path used by the application.
        if not self.isRunning():
            try:
                result = self._compute(
                    self._args, self._cancel_event.is_set,
                    lambda r: self.progress.emit(r, self.generation),
                )
                if not self._cancel_event.is_set():
                    self.finished_ok.emit(result, self.generation)
            except Cancelled:
                pass
            except Exception as exc:
                self.failed.emit(str(exc), self.generation)
            return
        context = multiprocessing.get_context("spawn")
        receiver, sender = context.Pipe(duplex=False)
        cancelled = context.Event()
        process = context.Process(target=_process_main, args=(self._compute, self._args, sender, cancelled))
        self._process = process
        received_result = False
        try:
            process.start()
            sender.close()
            while not self._cancel_event.is_set():
                if receiver.poll(0.03):
                    try:
                        kind, value = receiver.recv()
                    except EOFError:
                        break
                    if kind == "progress":
                        self.progress.emit(value, self.generation)
                    elif kind == "result":
                        received_result = True
                        self.finished_ok.emit(value, self.generation)
                        break
                    else:
                        received_result = True
                        self.failed.emit(value, self.generation)
                        break
                elif not process.is_alive():
                    break
            if not self._cancel_event.is_set() and not received_result:
                self.failed.emit("Le processus de calcul s’est arrêté sans résultat.", self.generation)
        except Exception as exc:
            if not self._cancel_event.is_set():
                self.failed.emit(str(exc), self.generation)
        finally:
            cancelled.set()
            if process.pid is not None:
                process.join(0.1)
                if process.is_alive():
                    process.terminate()
                    process.join(1)
                if process.is_alive():
                    process.kill()
                    process.join()
                process.close()
            sender.close()
            receiver.close()
            self._process = None
