"""Save states of RetroArch games: nine slots, each with a picture of the moment it was saved.

RetroArch names a state after the game ("Game.state", "Game.state1" …) and writes its picture
next to it ("Game.state1.png"); GamingCrypt adds how long was played up to it ("Game.state1.time").
It can load any slot (LOAD_STATE_SLOT), but saves only into "the current one" - and RetroArch
puts that back to 0 whenever a game starts (its slot keys are switched off: it stays there).
So RetroArch's slot 0 ("Game.state") is where it saves, and GamingCrypt then moves what it
wrote into the slot that was picked: the nine slots are RetroArch's 1-9. Nothing else is
touched - no other state is moved or deleted while saving, and nothing is ever deleted on its own.
"""

from __future__ import annotations

import glob
import os
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from gamingcrypt.emulation.library import EmulationPaths, RomGame

SLOTS = 9
SPARE = 99  # not one of the nine: the state a game comes back with after its speed was changed
SPARE_KEPT_S = 120
SCRATCH = 0  # RetroArch's own slot: where it saves, before it's moved into the slot picked
ASIDE = ".keep"  # (before 1.0.23: a kept state while RetroArch saved)
WITH_IT = (".png", ".time")  # what belongs to a state: its picture, its play time
_saving = threading.Lock()  # one save at a time, and no tidying up in the middle of one


@dataclass
class State:
    slot: int
    path: Path | None = None
    picture: Path | None = None  # None: saved before there were pictures
    saved_at: float = 0.0
    played: int | None = None  # seconds played up to it; None: saved before that was counted

    @property
    def empty(self) -> bool:
        return self.path is None


def _file_index(slot: int) -> int:
    """The nine slots (0-8) are RetroArch's slots 1-9; the spare one is itself."""
    return slot if slot == SPARE else slot + 1


def _named(paths: EmulationPaths, game: RomGame, index: int) -> Path:
    return paths.states / f"{game.path.stem}.state{index or ''}"


def state_file(paths: EmulationPaths, game: RomGame, slot: int) -> Path:
    return _named(paths, game, _file_index(slot))


def picture_of(state: Path) -> Path:
    return state.with_name(state.name + ".png")


def played_file(state: Path) -> Path:
    return state.with_name(state.name + ".time")


def read_played(state: Path) -> int | None:
    try:
        return max(0, int(played_file(state).read_text().strip()))
    except (OSError, ValueError):
        return None


def load_command(slot: int) -> str:
    return f"LOAD_STATE_SLOT {_file_index(slot)}"


def _age(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _written(paths: EmulationPaths, game: RomGame) -> list[tuple[Path, int]]:
    """(file, RetroArch's slot) of every state of the game right in states/."""
    name = re.compile(re.escape(game.path.stem) + r"\.state(\d*)$")
    try:
        files = [f for f in paths.states.glob(glob.escape(game.path.stem) + ".state*") if f.is_file()]
    except OSError:
        return []
    return sorted((f, int(m.group(1) or 0)) for f in files if (m := name.match(f.name)))


def _with(state: Path) -> list[Path]:
    return [state.with_name(state.name + suffix) for suffix in WITH_IT]


def _move(state: Path, target: Path) -> None:
    """The state with its picture and play time - those of what was there before must not stay."""
    os.replace(state, target)
    for extra, target_extra in zip(_with(state), _with(target)):
        if extra.is_file():
            os.replace(extra, target_extra)
        else:
            target_extra.unlink(missing_ok=True)


def _delete(state: Path) -> None:
    for f in (state, *_with(state)):
        try:
            f.unlink(missing_ok=True)
        except OSError:
            pass


def _free_index(paths: EmulationPaths, game: RomGame) -> int:
    """A file name nothing has: one of the nine slots if there's one, else one above them
    (kept on the drive, not shown)."""
    taken = {index for _f, index in _written(paths, game)}
    for index in [*range(SLOTS, 0, -1), *range(SLOTS + 1, SPARE), *range(SPARE + 1, 10000)]:
        if index not in taken:
            return index
    raise OSError("no free save state name")


def _put_back(paths: EmulationPaths, game: RomGame) -> None:
    """States put aside by GamingCrypt before 1.0.23 (cut off in the middle of a save): back -
    under a free name when one was saved there meanwhile. Never deleted."""
    try:
        aside = sorted(f for f in paths.states.glob(glob.escape(game.path.stem) + ".state*" + ASIDE) if f.is_file())
    except OSError:
        return
    states = [f for f in aside if not any(f.name.endswith(s + ASIDE) for s in WITH_IT)]
    for f in states:
        target = f.with_name(f.name[: -len(ASIDE)])
        try:
            if target.exists():
                target = _named(paths, game, _free_index(paths, game))
            os.replace(f, target)
            for suffix in WITH_IT:
                extra = f.with_name(f.name[: -len(ASIDE)] + suffix + ASIDE)
                if extra.is_file():
                    os.replace(extra, target.with_name(target.name + suffix))
        except OSError:
            pass


def _adopt_scratch(paths: EmulationPaths, game: RomGame) -> bool:
    """A state in RetroArch's own slot 0 - one from before 1.0.23 (its slot 1), or one a save
    left there when it was cut off - into a free slot. False: it couldn't be moved."""
    scratch = _named(paths, game, SCRATCH)
    if not scratch.is_file():
        return True
    try:
        _move(scratch, _named(paths, game, _free_index(paths, game)))
    except OSError:
        return False
    return True


def tidy(paths: EmulationPaths, game: RomGame, clock: Callable[[], float] = time.time) -> None:
    """States that aren't where they belong into a free slot; the spare one once it's old.
    (Not while a save is going on: its state isn't finished yet.)"""
    if not _saving.acquire(blocking=False):
        return
    try:
        _tidy(paths, game, clock)
    finally:
        _saving.release()


def _tidy(paths: EmulationPaths, game: RomGame, clock: Callable[[], float] = time.time) -> bool:
    _put_back(paths, game)
    spare = _named(paths, game, SPARE)
    if spare.is_file() and clock() - _age(spare) > SPARE_KEPT_S:
        _delete(spare)
    return _adopt_scratch(paths, game)


def slots(paths: EmulationPaths, game: RomGame) -> list[State]:
    """The nine slots, in order - tidied up first."""
    tidy(paths, game)
    found = []
    for slot in range(SLOTS):
        state = state_file(paths, game, slot)
        if state.is_file():
            picture = picture_of(state)
            found.append(State(slot, state, picture if picture.is_file() else None, _age(state),
                               read_played(state)))
        else:
            found.append(State(slot))
    return found


def newest(paths: EmulationPaths, game: RomGame, count: int) -> list[State]:
    """The states last saved, the newest first."""
    saved = [s for s in slots(paths, game) if not s.empty]
    return sorted(saved, key=lambda s: s.saved_at, reverse=True)[:count]


def _wait_for_state(scratch: Path, timeout: float, sleep, clock) -> bool:
    """RetroArch wrote its state completely (the same size twice) - and its picture, which may
    take a moment longer."""
    deadline = clock() + timeout
    seen = -1
    while clock() < deadline:
        sleep(0.15)
        size = _size(scratch)
        if size and size == seen:
            break
        seen = size
    else:
        return False
    deadline, size = clock() + 3, -1
    while clock() < deadline:
        now = _size(picture_of(scratch))
        if now and now == size:
            break
        size = now
        sleep(0.15)
    return True


def capture(paths: EmulationPaths, game: RomGame, slot: int, send: Callable[[str], bool], timeout: float = 15.0,
            sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic,
            played: int | None = None) -> bool:
    """Save the running game into the slot. False: RetroArch wrote nothing (a core without save
    states) - what was in the slot is still there then. played: seconds played up to now."""
    with _saving:
        if not _tidy(paths, game):
            return False  # RetroArch's slot 0 isn't free: its save would replace a state
        scratch = _named(paths, game, SCRATCH)
        try:
            for f in _with(scratch):
                f.unlink(missing_ok=True)  # a picture without its state
            if not send("SAVE_STATE"):
                return False
            if not _wait_for_state(scratch, timeout, sleep, clock):
                return False  # (should it still come: the next look at the slots puts it in a free one)
            target = state_file(paths, game, slot)
            _move(scratch, target)
            if played is not None:
                played_file(target).write_text(f"{int(played)}\n")
            return True
        except OSError:
            return False


def rescue(paths: EmulationPaths, game: RomGame) -> int | None:
    """The spare state into a free slot (the game didn't come back with it by itself) - the slot,
    None when all nine are taken or there's no spare one."""
    spare = state_file(paths, game, SPARE)
    free = next((s.slot for s in slots(paths, game) if s.empty), None)
    if free is None or not spare.is_file():
        return None
    try:
        _move(spare, state_file(paths, game, free))
    except OSError:
        return None
    return free
