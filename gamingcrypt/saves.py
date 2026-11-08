"""Everybody's saves of a game: who has how much, backed up, copied to another user, deleted.

Two kinds, the same to work with: a Windows game's saves are a whole folder for each user (its Wine
prefix, wine/library.py), an emulated game's are files named after it in that user's saves/ and
states/ (emulation/library.EmulationPaths). "" is the admin, as everywhere.

What's replaced is never touched before its replacement is complete: everything is copied to a work
folder first and only then swapped in - and what's there is backed up first. Backups are whole copies,
in <root>/.save-backups/<user>/<game>/<date>: only the newest few of each user and game are kept.
"""

from __future__ import annotations

import os
import shutil
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from gamingcrypt.emulation.library import EmulationPaths, RomGame
from gamingcrypt.emulation.removal import _named_like
from gamingcrypt.wine import library as wine
from gamingcrypt.wine.library import BACKUPS, USERS, WindowsGame, folder_size

MAX_BACKUPS = 3
ADMIN_FOLDER = "admin"
WORK = ".work"
SPARE_ROOM = 100 * 1024 * 1024  # never fill the drive to its last byte
REPLACED = ".replaced-by-gamingcrypt"  # (the old prefix for a moment, while the new one is put there)
_working = threading.Lock()  # one at a time: and the work folder is only tidied when nothing uses it


class SaveError(Exception):
    """Why it didn't work, for the user - everything is as it was."""


@dataclass
class Backup:
    path: Path
    made: float
    size: int


@dataclass
class UserSaves:
    user: str
    size: int = 0
    changed: float = 0.0  # 0: no saves
    backups: list[Backup] = field(default_factory=list)
    states: list = field(default_factory=list)  # an emulated game: the user's save states (savestates.State)

    @property
    def has_saves(self) -> bool:
        return self.changed > 0


def _newest(path: Path) -> float:
    """When anything below it (or it itself) last changed."""
    try:
        newest = path.lstat().st_mtime
    except OSError:
        return 0.0
    for base, _dirs, files in os.walk(path):
        for name in files:
            try:
                newest = max(newest, os.lstat(os.path.join(base, name)).st_mtime)
            except OSError:
                pass
    return newest


class PrefixSaves:
    """A Windows game: every user's Wine prefix. Its size includes Wine's own files."""

    NOTE = "The size includes Wine's own files. If a game saves into its own folder, those saves are shared."

    def __init__(self, game: WindowsGame):
        self.game = game
        self.root = wine.library_root(game)
        self.key = game.path.name

    def owners(self) -> list[str]:
        return [user for user in ("", *self._user_folders()) if self.has(user)]

    def has(self, user: str) -> bool:
        return wine.prefix_dir(self.game, user).is_dir()

    def measure(self, user: str) -> tuple[int, float]:
        prefix = wine.prefix_dir(self.game, user)
        # what the game writes - not the prefix's own files, which changing Proton may touch
        changed = max(_newest(prefix / "pfx" / "drive_c" / "users"), _newest(prefix / "pfx" / "user.reg"),
                      _newest(prefix) if not (prefix / "pfx").exists() else 0.0)
        return folder_size(prefix), changed

    def snapshot(self, user: str, into: Path) -> None:
        shutil.copytree(wine.prefix_dir(self.game, user), into, symlinks=True)

    def install(self, source: Path, user: str) -> None:
        """Moves ``source`` (complete, on the same drive) to be the user's prefix."""
        prefix = wine.prefix_dir(self.game, user)
        prefix.parent.mkdir(parents=True, exist_ok=True)
        old = prefix.with_name(prefix.name + REPLACED)
        if prefix.exists():
            os.replace(prefix, old)
        try:
            os.replace(source, prefix)
        except OSError:
            if old.exists():
                os.replace(old, prefix)
            raise
        shutil.rmtree(old, ignore_errors=True)

    def wipe(self, user: str) -> None:
        shutil.rmtree(wine.prefix_dir(self.game, user))

    def tidy(self) -> None:
        """Cut off in the middle of install(): the old prefix back, or what's left of it away."""
        for user in ("", *self._user_folders()):
            prefix = wine.prefix_dir(self.game, user)
            old = prefix.with_name(prefix.name + REPLACED)
            if old.exists():
                if prefix.exists():
                    shutil.rmtree(old, ignore_errors=True)
                else:
                    os.replace(old, prefix)

    def _user_folders(self) -> list[str]:
        try:
            return sorted(p.name for p in (self.root / USERS).iterdir() if p.is_dir())
        except OSError:
            return []


class RomSaves:
    """An emulated game: what RetroArch wrote under its name into the user's saves/ and states/.
    (A memory card shared by all users, like PS2's, isn't anybody's: not here.)"""

    NOTE = ""
    FOLDERS = ("saves", "states")

    def __init__(self, root: Path, game: RomGame):
        self.game = game
        self.root = Path(root)
        self.key = f"{game.system.id}/{game.path.stem}"

    def _files(self, user: str) -> list[tuple[str, Path, Path]]:
        """(its folder's name, the folder, the file)."""
        paths = EmulationPaths(self.root, user)
        stems = {self.game.path.stem} | {disc.stem for disc in self.game.discs}
        return [(name, getattr(paths, name), file) for name in self.FOLDERS
                for file in sorted(_named_like(getattr(paths, name), stems))]

    def owners(self) -> list[str]:
        try:
            found = sorted(p.name for p in (self.root / "users").iterdir() if p.is_dir())
        except OSError:
            found = []
        return [user for user in ("", *found) if self.has(user)]

    def has(self, user: str) -> bool:
        return bool(self._files(user))

    def measure(self, user: str) -> tuple[int, float]:
        size, changed = 0, 0.0
        for _name, _folder, file in self._files(user):
            try:
                facts = file.stat()
            except OSError:
                continue
            size, changed = size + facts.st_size, max(changed, facts.st_mtime)
        return size, changed

    def snapshot(self, user: str, into: Path) -> None:
        into.mkdir(parents=True)
        for name, folder, file in self._files(user):
            target = into / name / file.relative_to(folder)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file, target)

    def install(self, source: Path, user: str) -> None:
        paths = EmulationPaths(self.root, user)
        before = {file for _name, _folder, file in self._files(user)}
        placed = set()
        for name in self.FOLDERS:
            folder = getattr(paths, name)
            incoming = source / name
            for file in sorted(p for p in incoming.rglob("*") if p.is_file()):
                target = folder / file.relative_to(incoming)
                target.parent.mkdir(parents=True, exist_ok=True)
                os.replace(file, target)
                placed.add(target)
        for file in before - placed:
            file.unlink(missing_ok=True)
        shutil.rmtree(source, ignore_errors=True)

    def wipe(self, user: str) -> None:
        for _name, _folder, file in self._files(user):
            file.unlink(missing_ok=True)

    def tidy(self) -> None:
        pass


# --- what can be done with them, the same for both --------------------------------------------

def _backups_root(box) -> Path:
    return box.root / BACKUPS


def _backups_of(box, user: str) -> Path:
    return _backups_root(box) / (user or ADMIN_FOLDER) / box.key


def _busy() -> SaveError:
    return SaveError("Another copy of saves is still running - try again when it's done")


def _work_folder(box) -> Path:
    folder = _backups_root(box) / WORK
    folder.mkdir(parents=True, exist_ok=True)
    return folder / uuid.uuid4().hex


def _check_room(box, needed: int) -> None:
    _backups_root(box).mkdir(parents=True, exist_ok=True)
    free = shutil.disk_usage(_backups_root(box)).free
    if free < needed + SPARE_ROOM:
        raise SaveError(f"Not enough free space on the drive: {_gb(needed + SPARE_ROOM)} needed, {_gb(free)} free")


def _gb(size: int) -> str:
    return f"{size / 1024 ** 3:.1f} GB"


def backups(box, user: str) -> list[Backup]:
    """The newest first. Only finished ones are here: they're moved in when they're complete."""
    try:
        folders = [p for p in _backups_of(box, user).iterdir() if p.is_dir()]
    except OSError:
        return []
    found = []
    for folder in folders:
        try:
            made = time.mktime(time.strptime(folder.name[:15], "%Y%m%d-%H%M%S"))
        except ValueError:
            continue  # not one of ours
        found.append(Backup(folder, made, folder_size(folder)))
    return sorted(found, key=lambda b: (b.made, b.path.name), reverse=True)


def overview(box, users: list[str]) -> list[UserSaves]:
    """These users - and whoever else has saves or backups of it (a user deleted since)."""
    if _working.acquire(blocking=False):
        try:
            box.tidy()
            shutil.rmtree(_backups_root(box) / WORK, ignore_errors=True)
        finally:
            _working.release()
    try:
        with_backups = sorted(p.name for p in _backups_root(box).iterdir()
                              if p.is_dir() and p.name != WORK and (p / box.key).is_dir())
    except OSError:
        with_backups = []
    named = ["" if name == ADMIN_FOLDER else name for name in with_backups]
    found = []
    for user in dict.fromkeys([*users, *box.owners(), *named]):
        size, changed = box.measure(user) if box.has(user) else (0, 0.0)
        found.append(UserSaves(user, size, changed, backups(box, user), box_states(box, user)))
    return found


def box_states(box, user: str) -> list:
    """An emulated game's save states of that user, by slot (none for a Windows game's prefix)."""
    if not isinstance(box, RomSaves):
        return []
    from gamingcrypt.emulation import savestates

    return [s for s in savestates.slots(EmulationPaths(box.root, user), box.game) if not s.empty]


def delete_state(box, user: str, slot: int) -> bool:
    """One of that user's save states - the others, and the rest of their saves, stay."""
    from gamingcrypt.emulation import savestates

    return savestates.delete(EmulationPaths(box.root, user), box.game, slot)


def _store_backup(box, user: str) -> Backup:
    """(With the lock.) A new backup, the oldest above the limit gone."""
    work = _work_folder(box)
    try:
        box.snapshot(user, work)
        target = _backups_of(box, user)
        target.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        final = target / stamp
        while final.exists():
            final = target / f"{stamp}-{uuid.uuid4().hex[:4]}"
        os.replace(work, final)
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise
    for old in backups(box, user)[MAX_BACKUPS:]:
        shutil.rmtree(old.path, ignore_errors=True)
    return next(b for b in backups(box, user) if b.path == final)


def _guarded(fn):
    def run(*args, **kwargs):
        if not _working.acquire(blocking=False):
            raise _busy()
        try:
            return fn(*args, **kwargs)
        except OSError as exc:  # (shutil.Error is one too)
            raise SaveError(f"It didn't work, nothing was replaced: {exc}") from exc
        finally:
            _working.release()
    return run


@_guarded
def back_up(box, user: str) -> Backup:
    if not box.has(user):
        raise SaveError("There are no saves to back up")
    _check_room(box, box.measure(user)[0])
    return _store_backup(box, user)


def _replace(box, user: str, fill, needed: int) -> None:
    """(With the lock.) The new saves complete in the work folder first, then what's there backed up,
    then swapped."""
    keep = box.has(user)
    _check_room(box, needed + (box.measure(user)[0] if keep else 0))
    work = _work_folder(box)
    try:
        fill(work)
        if keep:
            _store_backup(box, user)
        box.install(work, user)
    finally:
        shutil.rmtree(work, ignore_errors=True)


@_guarded
def copy_to(box, source: str, target: str) -> None:
    """``source``'s saves become ``target``'s. What ``target`` had is backed up first."""
    if source == target:
        raise SaveError("That's the same user")
    if not box.has(source):
        raise SaveError("There are no saves to copy")
    _replace(box, target, lambda work: box.snapshot(source, work), box.measure(source)[0])


@_guarded
def restore(box, user: str, backup: Backup) -> None:
    """The saves from that backup. What the user has now is backed up first."""
    if not backup.path.is_dir():
        raise SaveError("That backup isn't there any more")
    _replace(box, user, lambda work: shutil.copytree(backup.path, work, symlinks=True), backup.size)


@_guarded
def delete(box, user: str) -> None:
    """The user's saves are gone (their backups stay)."""
    box.wipe(user)


@_guarded
def delete_backup(backup: Backup) -> None:
    shutil.rmtree(backup.path)
