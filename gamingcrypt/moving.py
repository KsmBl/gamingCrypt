"""Moving a game between the encrypted drive and a USB stick, USB drive or SD card - either way.

Emulated games (their files: a ROM, or a game's discs and tracks) and Windows / Linux games (their
folder). Copied first, under a name that isn't seen as a game; only when everything is there it gets
its real name and the original is deleted - a stick pulled out half way loses nothing. The game keeps
its id (it's the file / folder name), so its favorite, play time, saves, covers and settings stay.
"""

from __future__ import annotations

import os
import shutil
import threading
from dataclasses import dataclass, field
from pathlib import Path

from gamingcrypt.emulation import removal
from gamingcrypt.emulation.library import RomGame
from gamingcrypt.wine.library import WindowsGame, folder_size, library_root

MOVING = ".moving-"  # what's still being copied (hidden: not a game)
FAT_LIMIT = 4 * 1024 ** 3 - 1  # FAT32: no file bigger
NO_PERMISSIONS = {"vfat", "exfat", "ntfs", "ntfs3"}  # can't keep a Linux program startable
SPARE_ROOM = 64 * 1024 * 1024  # never fill it to its last byte
CHUNK = 4 * 1024 * 1024


class MoveError(Exception):
    """Not moved - and why, as a person says it."""


@dataclass
class Progress:
    """How far a move is: read by the UI while the copying runs in the background."""

    total: int = 0
    done: int = 0
    cancelled: threading.Event = field(default_factory=threading.Event)

    @property
    def fraction(self) -> float:
        return min(1.0, self.done / self.total) if self.total else 0.0


@dataclass(frozen=True)
class Place:
    """Where a game can go: the encrypted drive (removable None) or one that's in."""

    removable: object | None = None  # system.removable.Removable

    @property
    def name(self) -> str:
        return self.removable.name if self.removable is not None else "the encrypted drive"

    @property
    def fstype(self) -> str:
        return getattr(self.removable, "fstype", "") if self.removable is not None else ""


def files_of(game) -> list[Path]:
    """What's moved: an emulated game's files (not the playlist GamingCrypt wrote on the drive),
    a Windows / Linux game's folder."""
    if isinstance(game, RomGame):
        found = removal.game_files(game)
        return [f for f in found if not (game.discs and f == game.path)]
    return [game.path]


def size_of(game) -> int:
    if isinstance(game, RomGame):
        return removal.Removal.size(files_of(game))
    return folder_size(game.path)


def is_on(game, removable) -> bool:
    """Is the game on that drive (None: the encrypted drive)?"""
    if removable is None:
        return not getattr(game, "removable", "")
    first = files_of(game)[:1] or [game.path]
    return Path(removable.mount) in first[0].parents


def target(game, place: Place, emulation=None) -> Path:
    """The folder its files go to (an emulated game) / its folder (a Windows or Linux game)."""
    drive = place.removable
    if isinstance(game, RomGame):
        if drive is None:
            if emulation is None:
                raise MoveError("The encrypted drive isn't unlocked")
            return emulation.roms_for(game.system)
        mount = Path(drive.mount)
        # where the stick already keeps its ROMs: the short layout (roms/) when only that one is there
        short, full = mount / "roms", mount / "Emulation" / "roms"
        return (short if short.is_dir() and not full.is_dir() else full) / game.system.folder
    if drive is None:
        return library_root(game) / game.path.name
    return Path(getattr(drive, game.KIND)) / game.path.name


def places(game, drives: list, emulation=None) -> list[Place]:
    """Where the game can go from where it is: every other drive that's in, and back onto the
    encrypted one when it's on a stick."""
    found = [Place(d) for d in drives if not is_on(game, d)]
    if getattr(game, "removable", ""):
        if isinstance(game, RomGame) and emulation is None:
            return found
        if isinstance(game, WindowsGame) and game.home is None:
            return found
        found.insert(0, Place(None))
    return found


def _free(path: Path) -> int:
    while not path.exists() and path != path.parent:
        path = path.parent
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return 0


def check(game, place: Place, emulation=None, size: int | None = None) -> Path:
    """Can it go there? The target (MoveError: why not)."""
    folder = target(game, place, emulation)
    files = files_of(game)
    if not files:
        raise MoveError(f"{game.name}'s files aren't there any more")
    fstype = place.fstype
    if getattr(game, "KIND", "") == "linux" and fstype in NO_PERMISSIONS:
        raise MoveError(f"Linux games can't start from {place.name}: it's formatted as {fstype}. "
                        "Format it for Linux (ext4) in Settings → Storage first")
    if isinstance(game, RomGame):
        taken = [f.name for f in files if (folder / f.name).exists()]
        if taken:
            raise MoveError(f"{place.name} already has {taken[0]}")
    elif folder.exists():
        raise MoveError(f"{place.name} already has a folder called {folder.name}")
    if fstype == "vfat":
        big = [f for f in _all_files(files) if f.stat().st_size > FAT_LIMIT]
        if big:
            raise MoveError(f"{big[0].name} is bigger than 4 GB, too big for {place.name} (FAT32). "
                            "Format it as exFAT in Settings → Storage")
    size = size_of(game) if size is None else size
    free = _free(folder)
    if free < size + SPARE_ROOM:
        raise MoveError(f"Not enough room on {place.name}: {game.name} needs {_gb(size)}, {_gb(free)} are free")
    return folder


def _gb(size: int) -> str:
    return f"{size / 1024 ** 3:.1f} GB" if size >= 1024 ** 3 else f"{max(1, size // 1024 ** 2)} MB"


def _all_files(paths: list[Path]) -> list[Path]:
    found = []
    for path in paths:
        if path.is_dir():
            for base, _dirs, names in os.walk(path):
                found += [Path(base) / n for n in names if not os.path.islink(os.path.join(base, n))]
        elif path.is_file():
            found.append(path)
    return found


def _copy_file(source: Path, dest: Path, progress: Progress) -> None:
    with open(source, "rb") as src, open(dest, "wb") as out:
        while True:
            if progress.cancelled.is_set():
                raise MoveError("Cancelled")
            chunk = src.read(CHUNK)
            if not chunk:
                break
            out.write(chunk)
            progress.done += len(chunk)
        out.flush()
        os.fsync(out.fileno())  # really on the stick before the original goes
    try:
        shutil.copystat(source, dest)  # (a start file stays startable - where it can)
    except OSError:
        pass


def _copy_tree(source: Path, dest: Path, progress: Progress, links: bool) -> None:
    dest.mkdir(parents=True)
    for entry in sorted(source.iterdir()):
        into = dest / entry.name
        if entry.is_symlink():
            if links:
                os.symlink(os.readlink(entry), into)
                continue
            if not entry.exists():
                continue  # (points nowhere)
        if entry.is_dir():
            _copy_tree(entry, into, progress, links)
        else:
            _copy_file(entry, into, progress)
    try:
        shutil.copystat(source, dest)
    except OSError:
        pass


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path, ignore_errors=True)
    else:
        path.unlink(missing_ok=True)


def move(game, place: Place, emulation=None, progress: Progress | None = None) -> Path:
    """Copy it there, then delete it here. Where it is now (MoveError: not moved, nothing lost)."""
    progress = progress if progress is not None else Progress()
    files = files_of(game)
    progress.total, progress.done = size_of(game), 0
    folder = check(game, place, emulation, progress.total)
    links = place.fstype not in NO_PERMISSIONS
    made: list[Path] = []
    try:
        if isinstance(game, RomGame):
            folder.mkdir(parents=True, exist_ok=True)
            copies = []
            for f in files:
                temp = folder / f"{MOVING}{f.name}"
                made.append(temp)
                _copy_file(f, temp, progress)
                copies.append((temp, folder / f.name))
            for temp, final in copies:  # everything's there: now it's a game
                temp.rename(final)
                made.append(final)
            moved = folder / game.path.name if not game.discs else folder
        else:
            folder.parent.mkdir(parents=True, exist_ok=True)
            temp = folder.parent / f"{MOVING}{folder.name}"
            made.append(temp)
            _copy_tree(game.path, temp, progress, links)
            temp.rename(folder)
            made.append(folder)
            moved = folder
    except MoveError:
        for path in made:
            _remove(path)
        raise
    except OSError as exc:
        for path in made:
            _remove(path)
        raise MoveError(f"Could not move {game.name}: {exc.strerror or exc}") from exc
    for f in files:
        _remove(f)
    return moved
