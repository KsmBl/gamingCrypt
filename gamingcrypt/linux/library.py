"""The Linux games in <drive>/Linux Games: every folder is a game (copied over the network share
as it is - from GOG, itch.io, Humble ...), started with a program or script chosen once.

Like the Windows games (wine.library), without Proton / Wine: the start file runs as it is.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from gamingcrypt.wine.library import MAX_DEPTH, NOT_THE_GAME, SKIP_FOLDERS, WindowsGame, _words, scan as _scan

LINUX_APPID_BASE = 0x40000000  # below the Windows games' ids, far above Steam's
# start files: programs (ELF) and scripts (#!) - by name, so data files aren't opened
SUFFIXES = {"", ".sh", ".x86_64", ".x86", ".x64", ".bin", ".run", ".appimage", ".elf", ".64", ".32"}
LAUNCHER_NAMES = {"start", "run", "launch", "launcher", "play", "game"}  # GOG's start.sh & co.
LIBRARY = re.compile(r"\.so(\.\d+)*$", re.IGNORECASE)
NOT_STARTABLE = re.compile(r"^(license|readme|changelog|credits|copying|authors|eula)", re.IGNORECASE)


class LinuxGame(WindowsGame):
    KIND = "linux"
    LABEL = "Linux"
    APPID_BASE = LINUX_APPID_BASE


def is_linux_appid(appid: int | None) -> bool:
    return appid is not None and LINUX_APPID_BASE <= appid < LINUX_APPID_BASE + 0x10000000


def scan(root: Path, sizes: bool = True) -> list[LinuxGame]:
    return _scan(root, sizes, LinuxGame)


def startable(path: Path) -> bool:
    """A program (ELF executable) or a script (#!)."""
    if LIBRARY.search(path.name) or NOT_STARTABLE.match(path.name) or path.suffix.lower() not in SUFFIXES:
        return False
    try:
        with open(path, "rb") as f:
            head = f.read(18)
    except OSError:
        return False
    if head[:2] == b"#!":
        return True
    return head[:4] == b"\x7fELF" and len(head) == 18 and head[16] in (2, 3)  # executable / position independent


def _is_32bit(name: str) -> bool:
    name = name.casefold()
    return "64" not in name and bool(re.search(r"x86|i[3-6]86|32", name))


def executables(game: LinuxGame) -> list[str]:
    """Its programs and scripts (paths inside its folder), the likeliest start file first: a
    start script (GOG's start.sh) or named like the game, not an installer / crash reporter,
    64-bit before 32-bit, near the top, the biggest."""
    found = []
    for base, dirs, files in os.walk(game.path):
        rel_base = Path(base).relative_to(game.path)
        depth = len(rel_base.parts)
        dirs[:] = [d for d in dirs if not d.startswith(".") and not SKIP_FOLDERS.match(d) and depth < MAX_DEPTH]
        for name in files:
            path = Path(base) / name
            if startable(path):
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
        launcher = stem.casefold() in LAUNCHER_NAMES
        alike = len(game_words & _words(stem))
        return (unlikely, not launcher, -alike, _is_32bit(Path(rel).name), depth, -size, rel.casefold())

    return [rel for rel, _d, _s in sorted(found, key=rank)]


def make_startable(game: LinuxGame) -> None:
    """Copied over the network share, programs lose their "executable" mark: give it back."""
    for rel in executables(game):
        path = game.path / rel
        try:
            mode = path.stat().st_mode
            if mode & 0o111 != 0o111:
                path.chmod(mode | 0o111)
        except OSError:
            pass
