"""The Windows games in <drive>/Windows Games: every folder is a game (copied over the network
share as it is), started with an .exe chosen once.

Each game gets its own Wine prefix (its "C:" drive, where most games keep their saves) on
the encrypted drive too: <drive>/Windows Games/.prefixes/<game>.
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

    @property
    def appid(self) -> int:
        """Stable id (favorites, settings, the game watcher) - not a Steam app."""
        return WINE_APPID_BASE | (zlib.crc32(self.path.name.encode()) & 0x0FFFFFFF)

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


def scan(root: Path, sizes: bool = True) -> list[WindowsGame]:
    """Every folder in the Windows Games folder (not hidden ones, not the prefixes)."""
    root = Path(root)
    try:
        folders = sorted((p for p in root.iterdir() if p.is_dir() and not p.name.startswith(".")),
                         key=lambda p: p.name.casefold())
    except OSError:
        return []
    return [WindowsGame(p, p.name, folder_size(p) if sizes else 0) for p in folders]


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


def prefix_dir(game: WindowsGame) -> Path:
    return game.path.parent / PREFIXES / game.path.name


def remove(game: WindowsGame, with_saves: bool) -> int:
    """Delete the game's folder - and its prefix (saves, settings) when asked. Bytes freed."""
    freed = folder_size(game.path)
    shutil.rmtree(game.path, ignore_errors=True)
    prefix = prefix_dir(game)
    if with_saves and prefix.exists():
        freed += folder_size(prefix)
        shutil.rmtree(prefix, ignore_errors=True)
    return freed
