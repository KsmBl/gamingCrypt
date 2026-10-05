"""Emulation folders on the encrypted drive and the games in them."""

from __future__ import annotations

import re
import zlib
from dataclasses import dataclass
from pathlib import Path

from gamingcrypt.emulation.systems import SYSTEMS, System

FOLDERS = ("roms", "bios", "cores", "saves", "states", "screenshots", "config")
TAGS = re.compile(r"\s*[\(\[][^\)\]]*[\)\]]")  # "(USA) (Rev 1) [!]"
DISC = re.compile(r"\s*[\(\[]\s*(?:disc|disk|cd)\s*(\d+)(?:\s*of\s*\d+)?\s*[\)\]]", re.IGNORECASE)
EMU_APPID_BASE = 0x70000000  # far above any Steam app id


@dataclass
class EmulationPaths:
    root: Path  # <drive>/Emulation

    def __post_init__(self):
        self.root = Path(self.root)

    def __getattr__(self, name: str) -> Path:
        if name in FOLDERS:
            return self.root / name
        raise AttributeError(name)

    def roms_for(self, system: System) -> Path:
        return self.root / "roms" / system.folder

    def ensure(self) -> None:
        for folder in FOLDERS:
            (self.root / folder).mkdir(parents=True, exist_ok=True)
        for system in SYSTEMS:
            self.roms_for(system).mkdir(exist_ok=True)


@dataclass
class RomGame:
    system: System
    path: Path
    name: str
    size: int
    last_played: int | None = None  # from the play log (emulation/playtime)
    minutes: int = 0
    discs: tuple[Path, ...] = ()  # a game on several discs: path is the playlist (.m3u) GamingCrypt wrote

    @property
    def appid(self) -> int:
        """Stable id (favorites, power profiles, gamescope focus) - not a real Steam app."""
        key = f"{self.system.id}/{self.path.name}".encode()
        return EMU_APPID_BASE | (zlib.crc32(key) & 0x0FFFFFFF)


def clean_name(filename: str) -> str:
    stem = Path(filename).stem
    return TAGS.sub("", stem).replace("_", " ").strip() or stem


def _referenced(path: Path) -> set[str]:
    """Files a .m3u / .cue / .gdi points to (shown as one game, not one per disc/track)."""
    try:
        text = path.read_text(errors="replace")
    except OSError:
        return set()
    names = set()
    for line in text.splitlines():
        line = line.strip()
        if path.suffix.lower() == ".m3u" and line and not line.startswith("#"):
            names.add(Path(line).name.lower())
        quoted = re.search(r'"([^"]+)"', line)
        if quoted and path.suffix.lower() in (".cue", ".gdi"):
            names.add(Path(quoted.group(1)).name.lower())
        elif path.suffix.lower() == ".gdi" and line.split() and len(line.split()) >= 5:
            names.add(line.split()[4].lower())
    return names


def disc_number(filename: str) -> int | None:
    found = DISC.search(Path(filename).stem)
    return int(found.group(1)) if found else None


def _size(path: Path) -> int:
    """The file and what a .cue / .gdi points to (the .bin tracks)."""
    total = path.stat().st_size
    wanted = _referenced(path) if path.suffix.lower() in (".cue", ".gdi") else set()
    if wanted:  # (names in lower case: match them case-insensitively)
        for f in path.parent.iterdir():
            if f.name.lower() in wanted and f != path:
                total += f.stat().st_size
    return total


def write_playlist(paths: EmulationPaths, system: System, title: str, discs: list[Path]) -> Path:
    """An .m3u with the discs (in GamingCrypt's config on the drive): RetroArch's disc switching."""
    playlist = paths.config / "playlists" / system.id / f"{title}.m3u"
    text = "".join(f"{disc}\n" for disc in discs)
    if not playlist.exists() or playlist.read_text() != text:
        playlist.parent.mkdir(parents=True, exist_ok=True)
        playlist.write_text(text)
    return playlist


def scan(paths: EmulationPaths, system: System) -> list[RomGame]:
    folder = paths.roms_for(system)
    try:
        files = [f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in system.extensions]
    except OSError:
        return []
    hidden: set[str] = set()
    for f in files:
        if f.suffix.lower() in (".m3u", ".cue", ".gdi"):
            hidden |= _referenced(f)
    shown = [f for f in files if f.name.lower() not in hidden]
    # "Game (Disc 1).cue", "Game (Disc 2).cue" ...: one game (by the name without the disc)
    groups: dict[str, list[Path]] = {}
    for f in shown:
        if disc_number(f.name) is not None:
            groups.setdefault(DISC.sub("", f.stem).strip(), []).append(f)
    games = []
    for f in shown:
        number = disc_number(f.name)
        group = groups.get(DISC.sub("", f.stem).strip()) if number is not None else None
        if group is None or len(group) < 2:
            games.append(RomGame(system, f, clean_name(f.name), _size(f)))
        elif f is group[0]:
            discs = sorted(group, key=lambda d: disc_number(d.name))
            title = DISC.sub("", f.stem).strip()
            playlist = write_playlist(paths, system, title, discs)
            games.append(RomGame(system, playlist, clean_name(title + ".m3u"), sum(_size(d) for d in discs),
                                 discs=tuple(discs)))
    return sorted(games, key=lambda g: g.name.lower())


def scan_all(paths: EmulationPaths) -> dict[str, list[RomGame]]:
    """Systems that have games."""
    found = {}
    for system in SYSTEMS:
        games = scan(paths, system)
        if games:
            found[system.id] = games
    return found
