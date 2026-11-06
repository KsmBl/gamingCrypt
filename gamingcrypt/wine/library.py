"""The Windows games in <drive>/Windows Games: every folder is a game (copied over the network
share as it is), started with an .exe chosen once.

Each game gets its own Wine prefix (its "C:" drive, where most games keep their saves) on
the encrypted drive too. The admin's is <drive>/Windows Games/.prefixes/<game>, where it always
was; another user's is <drive>/Windows Games/.users/<id>/.prefixes/<game>, so each has their own saves.
"""

from __future__ import annotations

import os
import re
import shutil
import zlib
from dataclasses import dataclass
from pathlib import Path

WINE_APPID_BASE = 0x50000000  # below the movies' and emulated games' ids, far above Steam's
PREFIXES = ".prefixes"
USERS = ".users"
BACKUPS = ".save-backups"  # (saves.py)
STARTABLE = (".exe",)
# names that are almost never the game itself
NOT_THE_GAME = re.compile(r"unins|uninstall|setup|install|redist|vcredist|vc_redist|directx|dxsetup|dxwebsetup|"
                          r"dotnet|netfx|physx|ue4prereq|prereq|crash|report|helper|updater|update|config|"
                          r"settings|benchmark|server|editor|dedicated|cleanup|touchup|activation", re.IGNORECASE)
SKIP_FOLDERS = re.compile(r"^(_?commonredist|redist|redistributables?|directx|dotnet|vcredist|__installer|"
                          r"_installer|support|tools?)$", re.IGNORECASE)
MAX_DEPTH = 5


@dataclass
class WindowsGame:
    path: Path  # its folder
    name: str
    size: int = 0
    last_played: int | None = None
    minutes: int = 0
    removable: str = ""  # on a USB stick, USB drive or SD card (system.removable.KINDS) - "" on the drive
    home: Path | None = None  # on one: the drive's library folder, where its prefixes are

    KIND = "windows"  # a Linux game (linux.library.LinuxGame) is the same, without Proton / Wine
    LABEL = "Windows"
    APPID_BASE = WINE_APPID_BASE

    @property
    def appid(self) -> int:
        """Stable id (favorites, settings, the game watcher) - not a Steam app."""
        return self.APPID_BASE | (zlib.crc32(self.path.name.encode()) & 0x0FFFFFFF)

    @property
    def key(self) -> str:
        return self.path.name


def is_wine_appid(appid: int | None) -> bool:
    return appid is not None and WINE_APPID_BASE <= appid < WINE_APPID_BASE + 0x10000000


def folder_size(path: Path) -> int:
    total = 0
    for base, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.lstat(os.path.join(base, name)).st_size
            except OSError:
                pass
    return total


def scan(root: Path, sizes: bool = True, kind: type = WindowsGame, drives: list | tuple = ()) -> list[WindowsGame]:
    """Every folder in the Windows Games folder (not hidden ones, not the prefixes) - and in the one
    on every USB stick, drive or SD card in (system.removable.Removable). A game on both is the one
    on the drive."""
    root = Path(root)
    games = [kind(p, p.name, folder_size(p) if sizes else 0) for p in _folders(root)]
    seen = {g.appid for g in games}
    for drive in drives:
        for p in _folders(getattr(drive, kind.KIND)):
            game = kind(p, p.name, folder_size(p) if sizes else 0, removable=drive.kind, home=root)
            if game.appid not in seen:
                seen.add(game.appid)
                games.append(game)
    return sorted(games, key=lambda g: g.name.casefold()) if drives else games


def _folders(root: Path) -> list[Path]:
    try:
        return sorted((p for p in Path(root).iterdir() if p.is_dir() and not p.name.startswith(".")),
                      key=lambda p: p.name.casefold())
    except OSError:
        return []


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.casefold()) if len(w) > 1}


def executables(game: WindowsGame) -> list[str]:
    """Its .exe files (paths inside its folder), the likeliest start file first: named like the
    game, not an installer / redistributable / crash reporter, near the top, the biggest."""
    found = []
    for base, dirs, files in os.walk(game.path):
        rel_base = Path(base).relative_to(game.path)
        depth = len(rel_base.parts)
        dirs[:] = [d for d in dirs if not d.startswith(".") and not SKIP_FOLDERS.match(d) and depth < MAX_DEPTH]
        for name in files:
            if Path(name).suffix.lower() in STARTABLE:
                path = Path(base) / name
                try:
                    size = path.stat().st_size
                except OSError:
                    size = 0
                found.append(((rel_base / name).as_posix(), depth, size))
    game_words = _words(game.name)

    def rank(item) -> tuple:
        rel, depth, size = item
        stem = Path(rel).stem
        unlikely = bool(NOT_THE_GAME.search(stem))
        alike = len(game_words & _words(stem))
        return (unlikely, -alike, depth, -size, rel.casefold())

    return [rel for rel, _d, _s in sorted(found, key=rank)]


def library_root(game: WindowsGame) -> Path:
    """The library folder on the drive with the game's prefixes and backups - also for a game on a
    USB stick: its saves stay encrypted, and are there again when the stick is."""
    return Path(game.home) if game.home is not None else game.path.parent


def prefix_dir(game: WindowsGame, user: str = "") -> Path:
    """The game's prefix for that user's id ("" = the admin)."""
    root = library_root(game)
    return (root / USERS / user if user else root) / PREFIXES / game.path.name


def all_prefixes(game: WindowsGame) -> list[Path]:
    """The game's prefixes that exist: the admin's and every user's - also a deleted user's."""
    try:
        users = sorted(p.name for p in (library_root(game) / USERS).iterdir() if p.is_dir())
    except OSError:
        users = []
    return [p for p in (prefix_dir(game, user) for user in ("", *users)) if p.exists()]


def remove(game: WindowsGame, with_saves: bool) -> int:
    """Delete the game's folder - and everybody's prefix (saves, settings) and backups of them when
    asked. Bytes freed."""
    freed = folder_size(game.path)
    shutil.rmtree(game.path, ignore_errors=True)
    if with_saves:
        for folder in [*all_prefixes(game), *_all_backups(game)]:
            freed += folder_size(folder)
            shutil.rmtree(folder, ignore_errors=True)
    return freed


def _all_backups(game: WindowsGame) -> list[Path]:
    try:
        owners = [p for p in (library_root(game) / BACKUPS).iterdir() if p.is_dir()]
    except OSError:
        return []
    return [owner / game.path.name for owner in owners if (owner / game.path.name).is_dir()]
