"""Run blocking work (VeraCrypt, network, disk) off the UI thread."""

from __future__ import annotations

from typing import Any, Callable

import shiboken6
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
            self._emit(self.signals.failed, exc)
        else:
            self._emit(self.signals.done, result)

    @staticmethod
    def _emit(signal, value) -> None:
        try:
            signal.emit(value)
        except RuntimeError:
            pass  # the app is shutting down, nobody is listening any more


# Keep the signal objects alive until the task finished.
_alive: set[_Signals] = set()


def run_async(
    fn: Callable[[], Any],
    on_done: Callable[[Any], None] | None = None,
    on_error: Callable[[Exception], None] | None = None,
    owner: QObject | None = None,
) -> None:
    """Run ``fn`` in the thread pool, deliver the result on the UI thread.

    If ``owner`` is given and got deleted meanwhile (page closed), the callbacks are skipped.
    """

    def guard(callback):
        if callback is None or owner is None:
            return callback
        return lambda value: callback(value) if shiboken6.isValid(owner) else None

    on_done, on_error = guard(on_done), guard(on_error)
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
