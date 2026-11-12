"""What's going on right now that mustn't be cut short: a game being moved, a stick being formatted,
repaired or given a new password. Shutting down, restarting, sleeping, leaving gaming mode and locking
look here first (MainWindow.when_nothing_runs / panic_lock).

A job is ``Job(text, fraction, cancel)``: what it is as a person says it ("Moving Celeste to GAMES"),
how far it is (0..1, or None) and how to stop it safely - None where it can't be stopped (a format is
finished, not left half way)."""

from __future__ import annotations

import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Iterator


@dataclass(eq=False)
class Job:
    text: str
    fraction: Callable[[], float | None] = lambda: None
    cancel: Callable[[], None] | None = None

    def describe(self) -> str:
        try:
            part = self.fraction()
        except Exception:  # noqa: BLE001 - (only for the text)
            part = None
        return f"{self.text} ({part * 100:.0f} %)" if part is not None else self.text


_jobs: list[Job] = []
_lock = threading.Lock()


def start(job: Job) -> Job:
    with _lock:
        _jobs.append(job)
    return job


def end(job: Job) -> None:
    with _lock:
        if job in _jobs:
            _jobs.remove(job)


@contextmanager
def running(text: str, fraction: Callable[[], float | None] = lambda: None,
            cancel: Callable[[], None] | None = None) -> Iterator[Job]:
    job = start(Job(text, fraction, cancel))
    try:
        yield job
    finally:
        end(job)


def jobs() -> list[Job]:
    with _lock:
        return list(_jobs)


def busy() -> bool:
    return bool(jobs())


def summary() -> str:
    """One line per job: "Moving Celeste to GAMES (62 %)"."""
    return "\n".join(job.describe() for job in jobs())


def cancel_what_can_stop() -> list[Job]:
    """Stop every job that can be stopped safely (a move: its copy is deleted, the game stays where it
    was); the ones left are those to wait for."""
    left = []
    for job in jobs():
        if job.cancel is not None:
            try:
                job.cancel()
            except Exception:  # noqa: BLE001
                left.append(job)
        else:
            left.append(job)
    return left


def clear() -> None:
    """Tests: nothing going on."""
    with _lock:
        _jobs.clear()
