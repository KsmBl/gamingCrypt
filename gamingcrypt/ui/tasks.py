"""Run blocking work (VeraCrypt, network, disk) off the UI thread."""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal


class _Signals(QObject):
    done = Signal(object)
    failed = Signal(object)


class _Task(QRunnable):
    def __init__(self, fn: Callable[[], Any]):
        super().__init__()
        self.fn = fn
        self.signals = _Signals()

    def run(self) -> None:
        try:
            result = self.fn()
        except Exception as exc:  # noqa: BLE001 - forwarded to the UI
            self.signals.failed.emit(exc)
        else:
            self.signals.done.emit(result)


# Keep the signal objects alive until the task finished.
_alive: set[_Signals] = set()


def run_async(
    fn: Callable[[], Any],
    on_done: Callable[[Any], None] | None = None,
    on_error: Callable[[Exception], None] | None = None,
) -> None:
    task = _Task(fn)
    signals = task.signals
    _alive.add(signals)
    if on_done:
        signals.done.connect(on_done)
    if on_error:
        signals.failed.connect(on_error)
    signals.done.connect(lambda _r: _alive.discard(signals))
    signals.failed.connect(lambda _e: _alive.discard(signals))
    QThreadPool.globalInstance().start(task)
