"""Where a Windows game keeps its saves - only those files, not its whole Wine prefix (saves.py backs
up the whole prefix: Wine's own files are most of it).

Two ways to know:
- **the list** (save_manifest.py): Ludusavi's list of where thousands of PC games save, from
  PCGamingWiki - fetched once and kept;
- **playing** (learn()): GamingCrypt starts every Windows game itself, so after a game ran it looks at
  what was written while it ran - in the user's folder inside the prefix (AppData, Documents, Saved
  Games) and in the game's own folder. Caches, logs and crash reports don't count.

A place is a folder or file under one of three roots: "home" (the Windows user's folder in the prefix,
C:/users/steamuser), "drive_c" (the prefix's C:) or "game" (the game's own folder: shared by all users).
Paths are "/"-separated and may hold the list's "*" and "**"; they're matched ignoring case, as on Windows.

What was learned, and what the admin removed, is kept on the drive with the prefixes:
<library>/.save-locations.json - it belongs to the game, the same for every user.
"""

from __future__ import annotations

import fnmatch
import json
import os
import threading
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from gamingcrypt.wine import library as wine

FILE = ".save-locations.json"
ROOTS = ("home", "drive_c", "game")
SAVE, SETTINGS = "save", "settings"
LISTED, PLAYED = "list", "played"
SLACK_S = 2.0  # file times are compared with the start: a little earlier still counts
# a session that wrote this much into the game's own folder updated the game - it didn't save
MAX_GAME_FILES = 200
MAX_GAME_BYTES = 200 * 1024 * 1024

# what never counts as a save (case doesn't matter) --------------------------------------------
NOT_SAVES_HOME = (  # under the Windows user's folder: Wine's, Windows' and the GPU drivers' own
    "appdata/local/temp", "appdata/local/microsoft", "appdata/roaming/microsoft", "appdata/locallow/microsoft",
    "appdata/local/d3dscache", "appdata/local/nvidia", "appdata/local/nvidia corporation", "appdata/local/amd",
    "appdata/local/crashdumps", "appdata/locallow/unity", "appdata/local/unrealengine", "appdata/local/unity",
    "appdata/local/cef", "appdata/local/openal", "temp",
)
NOT_SAVES_FOLDERS = {  # anywhere
    "temp", "tmp", "cache", "caches", "shadercache", "shader_cache", "shadercaches", "gpucache", "code cache",
    "crashes", "crashreports", "crashdumps", "crash reports", "logs", "log", "webcache", "dxcache", "glcache",
    "__pycache__",
}
NOT_SAVES_ENDINGS = (
    ".log", ".tmp", ".temp", ".dmp", ".mdmp", ".lock", ".lck", ".dxvk-cache", ".cache", ".etl", ".pdb",
    ".exe", ".dll", ".so", ".old", ".bak~",
)
NOT_SAVES_NAMES = {"output_log.txt", "player.log", "player-prev.log", "desktop.ini", "thumbs.db", "steam_appid.txt"}

# a game's folder in the user's folder: how deep it goes before it's that game's own
HOME_PLACES = (  # (the parent, how many folders below it are the game's)
    ("appdata/locallow", 2),  # <company>/<game>
    ("appdata/roaming", 1),
    ("appdata/local", 1),
    ("documents/my games", 1),
    ("my documents/my games", 1),
    ("documents", 1),
    ("my documents", 1),
    ("saved games", 1),
)

_lock = threading.Lock()  # the file on the drive: learned while the saves page may be removing


@dataclass(frozen=True)
class Location:
    root: str  # ROOTS
    path: str  # "/"-separated, may hold "*" / "**" ("" = the whole root - never kept)
    source: str = PLAYED  # LISTED / PLAYED
    kind: str = SAVE  # SAVE / SETTINGS (the list tells them apart; what was played is a save)

    @property
    def key(self) -> tuple[str, str]:
        return self.root, self.path.casefold()

    def label(self) -> str:
        """For people: "AppData/Roaming/StardewValley", "Game folder/Saves", "C:/ProgramData/…"."""
        if self.root == "game":
            return f"Game folder/{self.path}" if self.path else "Game folder"
        if self.root == "drive_c":
            return f"C:/{self.path}"
        return self.path or "User folder"


# --- the prefix --------------------------------------------------------------------------------

def drive_c(game, user: str = "") -> Path:
    return wine.prefix_dir(game, user) / "pfx" / "drive_c"


def home_dir(game, user: str = "") -> Path | None:
    """The Windows user's folder in that user's prefix: Proton's steamuser, Wine's is named after the
    Linux user. None before the game first ran."""
    users = drive_c(game, user) / "users"
    if (users / "steamuser").is_dir():
        return users / "steamuser"
    try:
        found = sorted(p for p in users.iterdir() if p.is_dir() and not p.is_symlink()
                       and p.name.casefold() not in ("public", "default"))
    except OSError:
        return None
    return found[0] if found else None


def base(game, user: str, root: str) -> Path | None:
    if root == "game":
        return Path(game.path)
    if root == "drive_c":
        folder = drive_c(game, user)
        return folder if folder.is_dir() else None
    return home_dir(game, user)


def _children(folder: Path) -> list[os.DirEntry]:
    try:
        with os.scandir(folder) as entries:
            return list(entries)
    except OSError:
        return []


def matches(folder: Path, pattern: str) -> list[Path]:
    """What ``pattern`` names below ``folder`` - every part matched ignoring case, "**" any depth.
    Links aren't followed (plain Wine links Documents to the real home)."""
    parts = [p for p in pattern.split("/") if p]
    found: list[Path] = []

    def walk(at: Path, rest: list[str]) -> None:
        if not rest:
            found.append(at)
            return
        part, more = rest[0], rest[1:]
        if part == "**":
            walk(at, more)  # nothing in between
            for entry in _children(at):
                if entry.is_dir(follow_symlinks=False):
                    walk(Path(entry.path), rest)
            return
        wanted = part.casefold()
        for entry in _children(at):
            if entry.is_symlink():
                continue
            if entry.name.casefold() == wanted or fnmatch.fnmatchcase(entry.name.casefold(), wanted):
                if more and not entry.is_dir(follow_symlinks=False):
                    continue
                walk(Path(entry.path), more)

    if parts:
        walk(Path(folder), parts)
    return sorted(set(found))


def files(game, user: str, locations: list[Location]) -> list[Path]:
    """Every file of these places in that user's prefix (and the game's folder), each once."""
    found: set[Path] = set()
    for location in locations:
        folder = base(game, user, location.root)
        if folder is None or not location.path:
            continue
        for match in matches(folder, location.path):
            if match.is_file() and not match.is_symlink():
                found.add(match)
                continue
            for top, dirs, names in os.walk(match):  # (os.walk doesn't follow links)
                found.update(Path(top) / name for name in names if not os.path.islink(os.path.join(top, name)))
    return sorted(found)


def measure(game, user: str, locations: list[Location]) -> tuple[int, float]:
    """(bytes, when the newest changed - 0 when there are none) of the saves themselves."""
    size, newest = 0, 0.0
    for file in files(game, user, locations):
        try:
            facts = file.stat()
        except OSError:
            continue
        size, newest = size + facts.st_size, max(newest, facts.st_mtime)
    return size, newest


# --- what's kept on the drive ------------------------------------------------------------------

def _store(game) -> Path:
    return wine.library_root(game) / FILE


def _read(game) -> dict:
    try:
        data = json.loads(_store(game).read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(game, data: dict) -> None:
    path = _store(game)
    temp = path.with_name(f"{path.name}.{uuid.uuid4().hex[:8]}")
    temp.write_text(json.dumps(data, indent=1, sort_keys=True))
    os.replace(temp, path)


def _entry(game) -> dict:
    entry = _read(game).get(game.path.name)
    return entry if isinstance(entry, dict) else {}


def _locations(items, source: str) -> list[Location]:
    found = []
    for item in items or []:
        try:
            location = Location(item["root"], item["path"], source, item.get("kind", SAVE))
        except (KeyError, TypeError):
            continue
        if location.root in ROOTS and location.path:
            found.append(location)
    return found


def learned(game) -> list[Location]:
    return _locations(_entry(game).get("played"), PLAYED)


def removed(game) -> set[tuple[str, str]]:
    return {location.key for location in _locations(_entry(game).get("removed"), PLAYED)}


def _change(game, change) -> None:
    with _lock:
        data = _read(game)
        entry = data.get(game.path.name)
        entry = dict(entry) if isinstance(entry, dict) else {}
        change(entry)
        if any(entry.values()):
            data[game.path.name] = entry
        else:
            data.pop(game.path.name, None)
        _write(game, data)


def _plain(location: Location) -> dict:
    item = asdict(location)
    item.pop("source")
    return item


def remove(game, location: Location) -> None:
    """Not a place of its saves (the admin said so): not shown, and not learned again."""
    def change(entry: dict) -> None:
        entry["played"] = [item for item in entry.get("played", [])
                           if (item.get("root"), str(item.get("path", "")).casefold()) != location.key]
        gone = entry.setdefault("removed", [])
        if location.key not in {(i.get("root"), str(i.get("path", "")).casefold()) for i in gone}:
            gone.append({"root": location.root, "path": location.path})

    _change(game, change)


def bring_back(game) -> None:
    """Every removed place counts again (the learned ones are learned anew)."""
    _change(game, lambda entry: entry.pop("removed", None))


# --- all of them -------------------------------------------------------------------------------

def _inside(location: Location, other: Location) -> bool:
    """Is ``location`` (no wildcards) one of ``other``'s, or below one?"""
    if location.root != other.root:
        return False
    parts, others = location.path.casefold().split("/"), other.path.casefold().split("/")
    if "**" in others:
        head = others[:others.index("**")]
        return parts[:len(head)] == head
    return len(parts) >= len(others) and all(
        fnmatch.fnmatchcase(part, wanted) for part, wanted in zip(parts, others))


def _around(location: Location, other: Location) -> bool:
    """Is ``other`` (which may hold wildcards) in ``location``'s folder (no wildcards)?"""
    if location.root != other.root:
        return False
    parts, others = location.path.casefold().split("/"), other.path.casefold().split("/")
    return len(others) > len(parts) and others[:len(parts)] == parts


def _already(location: Location, places: list[Location]) -> bool:
    """Is what's in ``location`` already known: it's in one of ``places`` - or the list knows which of
    its files are saves (a learned folder around the list's "…/Hollow Knight/*.dat")."""
    return any(_inside(location, other) or (other.source == LISTED and _around(location, other))
               for other in places)


def known(game, listed: list[Location] | None = None) -> list[Location]:
    """Where the game saves: the list's places, then what playing found - without what the admin
    removed. ``listed``: the list's places (save_manifest.locations()), None when it isn't there."""
    gone = removed(game)
    places = [location for location in listed or [] if location.key not in gone]
    for location in learned(game):
        if location.key not in gone and not _already(location, places):
            places.append(location)
    return places


# --- learning from playing ---------------------------------------------------------------------

def _counts(relative: str) -> bool:
    """Could this file (relative to its root, "/"-separated) be a save?"""
    lowered = relative.casefold()
    parts = lowered.split("/")
    name = parts[-1]
    if name in NOT_SAVES_NAMES or name.endswith(NOT_SAVES_ENDINGS):
        return False
    return not any(part in NOT_SAVES_FOLDERS for part in parts[:-1])


def _home_place(relative: str) -> str | None:
    """The game's own folder (or file) in the user's folder that ``relative`` is in."""
    lowered = relative.casefold()
    if any(lowered == bad or lowered.startswith(bad + "/") for bad in NOT_SAVES_HOME):
        return None
    parts = relative.split("/")
    for parent, depth in HOME_PLACES:
        above = parent.split("/")
        if [p.casefold() for p in parts[:len(above)]] == above and len(parts) > len(above):
            keep = len(above) + depth
            return "/".join(parts[:min(keep, len(parts))])
    if len(parts) == 1:
        return None  # a file right in the user's folder: Wine's, not a game's
    return "/".join(parts[:-1])


def _game_place(relative: str) -> str:
    parts = relative.split("/")
    return "/".join(parts[:-1]) if len(parts) > 1 else relative


def _written_since(folder: Path, since: float) -> list[tuple[str, int]]:
    """(path relative to ``folder``, size) of every file written since then - links not followed."""
    found = []
    for top, dirs, names in os.walk(folder):
        dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(top, d))]
        for name in names:
            path = os.path.join(top, name)
            try:
                facts = os.lstat(path)
            except OSError:
                continue
            if facts.st_mtime >= since - SLACK_S and not os.path.islink(path):
                found.append((Path(path).relative_to(folder).as_posix(), facts.st_size))
    return found


def written(game, user: str, since: float) -> list[Location]:
    """The places the game wrote to since ``since`` (a time.time()) that look like saves."""
    places: dict[tuple[str, str], Location] = {}
    home = home_dir(game, user)
    if home is not None:
        for relative, _size in _written_since(home, since):
            place = _home_place(relative) if _counts(relative) else None
            if place:
                places.setdefault(("home", place.casefold()), Location("home", place))
    changed = [(r, s) for r, s in _written_since(Path(game.path), since) if _counts(r)]
    if len(changed) <= MAX_GAME_FILES and sum(s for _r, s in changed) <= MAX_GAME_BYTES:
        for relative, _size in changed:
            place = _game_place(relative)
            places.setdefault(("game", place.casefold()), Location("game", place))
    found = list(places.values())
    # one place inside another: only the outer one
    return [p for p in found if not any(o is not p and _inside(p, o) for o in found)]


def learn(game, user: str, since: float, listed: list[Location] | None = None) -> list[Location]:
    """After the game ran (since ``since``): the places it saved to that weren't known yet are
    remembered. What's new (nothing when it changed nothing new)."""
    places = known(game, listed)
    gone = removed(game)
    new = [location for location in written(game, user, since)
           if location.key not in gone and not _already(location, places)]
    if new:
        # a new place around ones learned before replaces them (Saves/1, then Saves: Saves)
        def change(entry: dict) -> None:
            kept = [item for item in entry.get("played", [])
                    if not any(_inside(Location(item.get("root", ""), item.get("path", "")), n) for n in new)]
            entry["played"] = [*kept, *(_plain(location) for location in new)]

        _change(game, change)
    return new
