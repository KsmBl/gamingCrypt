"""What newly arrived on the drive - over the network share, the browser upload or a copy by
hand: ROMs, Windows / Linux games, movies, shows.

Polled (every few seconds, from the app): the folders' entries are compared with the last
look. An entry counts once it stopped changing between two looks - a copy still running
isn't reported half done. The first look only learns what's there.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from gamingcrypt.movies.library import VIDEO_SUFFIXES

KINDS = ("rom", "windows", "linux", "movie", "show")
IGNORED = (".part", ".tmp", ".nfo", ".jpg", ".png", ".srt", ".json", ".appid", ".nomatch", ".m3u")


@dataclass(frozen=True)
class Arrival:
    kind: str  # one of KINDS
    name: str  # as a person says it: "Super Mario World"
    where: str = ""  # the system, for ROMs ("SNES")


def tidy(name: str) -> str:
    """"Super Mario World (USA) [!].sfc" -> "Super Mario World"."""
    stem = Path(name).stem if Path(name).suffix and not name.endswith(")") else name
    stem = re.sub(r"\s*[\[(][^\])]*[\])]", "", stem).replace("_", " ").replace(".", " ")
    return re.sub(r"\s+", " ", stem).strip() or name


def _state(path: Path) -> tuple[int, int] | None:
    """Changes while something is copied in: a file's size, a folder's newest entry."""
    try:
        if path.is_dir():
            newest = 0
            total = 0
            for root, _dirs, files in os.walk(path):
                for name in files:
                    info = os.stat(os.path.join(root, name))
                    newest, total = max(newest, int(info.st_mtime)), total + info.st_size
            return newest, total
        info = path.stat()
        return int(info.st_mtime), info.st_size
    except OSError:
        return None


class Watcher:
    def __init__(self, drive: str | Path):
        self.drive = Path(drive)
        self.known: dict[Path, tuple] | None = None  # entry -> its state when it was last seen
        self.waiting: dict[Path, tuple] = {}  # new, still being copied (maybe)

    def folders(self) -> list[tuple[str, Path, str]]:
        """(kind, folder, system) for every folder whose entries are things."""
        from gamingcrypt.emulation.systems import SYSTEMS, short_name

        found = [("rom", self.drive / "Emulation" / "roms" / s.id, short_name(s.id)) for s in SYSTEMS]
        found += [("windows", self.drive / "Windows Games", ""), ("linux", self.drive / "Linux Games", ""),
                  ("movie", self.drive / "Movies", ""), ("show", self.drive / "Shows", "")]
        return found

    def _entries(self) -> dict[Path, tuple[str, str]]:
        entries = {}
        for kind, folder, system in self.folders():
            try:
                children = list(folder.iterdir())
            except OSError:
                continue
            for child in children:
                name = child.name
                if name.startswith(".") or name.lower().endswith(IGNORED):
                    continue
                if kind in ("windows", "linux") and not child.is_dir():
                    continue  # games are folders
                if kind in ("movie", "show") and child.is_file() and child.suffix.lower() not in VIDEO_SUFFIXES:
                    continue
                entries[child] = (kind, system)
        return entries

    def poll(self) -> list[Arrival]:
        """What arrived since the last look (and stopped changing)."""
        entries = self._entries()
        if self.known is None:  # the first look: what's there was there before
            self.known = {path: () for path in entries}
            return []
        arrived = []
        for path, (kind, system) in entries.items():
            if path in self.known:
                continue
            state = _state(path)
            if state is None:
                continue
            if self.waiting.get(path) == state:  # the same as last time: done
                del self.waiting[path]
                self.known[path] = state
                arrived.append(Arrival(kind, tidy(path.name), system))
            else:
                self.waiting[path] = state
        for path in [p for p in self.known if p not in entries]:  # removed: new again if it comes back
            del self.known[path]
        for path in [p for p in self.waiting if p not in entries]:
            del self.waiting[path]
        return arrived


def describe(arrivals: list[Arrival]) -> str:
    """One notice for what came in together."""
    if len(arrivals) == 1:
        a = arrivals[0]
        what = {"rom": f"{a.name} ({a.where})", "windows": f"{a.name} (Windows game)",
                "linux": f"{a.name} (Linux game)", "movie": f"{a.name} (movie)", "show": f"{a.name} (show)"}[a.kind]
        return f"New on your drive: {what}"
    counts = [(sum(a.kind in ("rom", "windows", "linux") for a in arrivals), "game"),
              (sum(a.kind == "movie" for a in arrivals), "movie"), (sum(a.kind == "show" for a in arrivals), "show")]
    return "New on your drive: " + ", ".join(f"{n} {noun}{'s' if n != 1 else ''}" for n, noun in counts if n)
