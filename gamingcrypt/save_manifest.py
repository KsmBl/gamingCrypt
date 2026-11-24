"""Ludusavi's list of where PC games keep their saves (gathered from PCGamingWiki): fetched once,
boiled down to the Windows places of each game and kept in the cache folder - fetched again after
MAX_AGE_DAYS. Without it (offline), save_locations still learns from playing.

The list is 18 MB of YAML: read one game at a time, so it never needs more than a few MB.
Registry entries aren't here: they're inside the prefix (user.reg), saved with it as a whole.
"""

from __future__ import annotations

import gzip
import json
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Callable, Iterable, Iterator

from gamingcrypt.save_locations import LISTED, SAVE, SETTINGS, Location

URL = "https://raw.githubusercontent.com/mtkennerly/ludusavi-manifest/master/data/manifest.yaml"
FILE = "save-manifest.json.gz"
MAX_AGE_DAYS = 30
RETRY_S = 3600  # didn't get it: not again before this

# the list's placeholders on Windows -> (root, folder below it)
PLACES = {
    "<base>": ("game", ""),
    "<home>": ("home", ""),
    "<winAppData>": ("home", "AppData/Roaming"),
    "<winLocalAppData>": ("home", "AppData/Local"),
    "<winLocalAppDataLow>": ("home", "AppData/LocalLow"),
    "<winDocuments>": ("home", "Documents"),
    "<winPublic>": ("drive_c", "users/Public"),
    "<winProgramData>": ("drive_c", "ProgramData"),
    "<winDir>": ("drive_c", "windows"),
}
ANYONE = ("<storeUserId>", "<osUserName>", "<storeGameId>")  # whoever it is: any folder
NOT_WINDOWS_HOME = re.compile(r"^(\.|library/|\.config|\.local)", re.IGNORECASE)  # <home> on a Mac / Linux

_lock = threading.Lock()
_loaded: tuple[float, dict] | None = None  # (the file's time, its content)
_last_try = 0.0


def path(cache: Path | None = None) -> Path:
    if cache is None:
        from gamingcrypt.config import cache_dir

        cache = cache_dir()
    return Path(cache) / FILE


# --- reading the list ----------------------------------------------------------------------------

def _games(lines: Iterable[str]) -> Iterator[tuple[str, dict]]:
    """(title, its entry) - each game's lines read on their own."""
    import yaml

    loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
    chunk: list[str] = []

    def done() -> Iterator[tuple[str, dict]]:
        if not chunk:
            return
        try:
            data = yaml.load("".join(chunk), Loader=loader)
        except yaml.YAMLError:
            return  # one game the list got wrong: the others still count
        if isinstance(data, dict):
            for title, entry in data.items():
                if isinstance(entry, dict):
                    yield str(title), entry

    for line in lines:
        if line.startswith("---"):
            continue
        if line[:1] not in (" ", "\n", "\r", "#", ""):  # the next game starts
            yield from done()
            chunk = []
        chunk.append(line)
    yield from done()


def _on_windows(entry: dict) -> bool:
    conditions = entry.get("when") or []
    if not conditions:
        return True
    return any(isinstance(c, dict) and c.get("os") in (None, "windows") and c.get("store") != "microsoft"
               for c in conditions)


def translate(place: str) -> tuple[str, str] | None:
    """"<winAppData>/StardewValley/Saves" -> ("home", "AppData/Roaming/StardewValley/Saves") - None when
    it isn't somewhere in a prefix or the game's folder."""
    head, _, rest = place.replace("\\", "/").partition("/")
    if head not in PLACES:
        return None
    if head == "<home>" and NOT_WINDOWS_HOME.match(rest):
        return None
    for anyone in ANYONE:
        rest = rest.replace(anyone, "*")
    if "<" in rest or ".." in rest.split("/"):
        return None
    root, below = PLACES[head]
    joined = "/".join(p for p in (*below.split("/"), *rest.split("/")) if p)
    return (root, joined) if joined else None


def boil_down(lines: Iterable[str]) -> dict:
    """The list -> {"games": {title: {"steam": id, "files": [[root, path, kind], …]}}, "names": …}."""
    games, titles, folders, steam = {}, {}, {}, {}
    for title, entry in _games(lines):
        places = []
        for place, facts in (entry.get("files") or {}).items():
            facts = facts if isinstance(facts, dict) else {}
            if not _on_windows(facts):
                continue
            found = translate(str(place))
            if found is None:
                continue
            tags = facts.get("tags") or []
            places.append([*found, SAVE if "save" in tags or not tags else SETTINGS])
        if not places:
            continue
        appid = (entry.get("steam") or {}).get("id") if isinstance(entry.get("steam"), dict) else None
        games[title] = {"steam": appid, "files": places}
        titles.setdefault(normalize(title), title)
        for folder in entry.get("installDir") or {}:
            folders.setdefault(normalize(str(folder)), title)
        if isinstance(appid, int):
            steam.setdefault(str(appid), title)
    return {"games": games, "titles": titles, "folders": folders, "steam": steam, "made": time.time()}


def normalize(name: str) -> str:
    """"Hollow Knight™: Voidheart Edition" -> "hollowknightvoidheartedition"."""
    name = name.casefold().replace("&", "and")
    return re.sub(r"[^0-9a-z]+", "", re.sub(r"[™®©]", "", name))


# --- fetching and keeping it -------------------------------------------------------------------

def _download(get: Callable, into: Path) -> None:
    response = get(URL)
    response.raise_for_status()
    with open(into, "wb") as file:
        for block in response.iter_content(1 << 16):
            file.write(block)


def fetch(cache: Path | None = None, get: Callable | None = None, now: Callable[[], float] = time.time,
          force: bool = False) -> bool:
    """Fetches the list when it isn't here or is old. True when there is one now. Takes a while (call it
    in the background); on errors the one there was stays."""
    global _last_try
    target = path(cache)
    with _lock:
        try:
            fresh = now() - target.stat().st_mtime < MAX_AGE_DAYS * 86400
        except OSError:
            fresh = False
        if fresh and not force:
            return True
        if not force and now() - _last_try < RETRY_S:
            return target.exists()
        _last_try = now()
        if get is None:
            import requests

            def get(url):
                return requests.get(url, timeout=30, stream=True)

        target.parent.mkdir(parents=True, exist_ok=True)
        raw = target.with_name(f".{FILE}.{uuid.uuid4().hex[:8]}.yaml")
        temp = target.with_name(f".{FILE}.{uuid.uuid4().hex[:8]}")
        try:
            _download(get, raw)
            with open(raw, encoding="utf-8") as lines:
                data = boil_down(lines)
            if not data["games"]:
                return target.exists()  # not the list (an error page?): keep the old one
            with gzip.open(temp, "wt", encoding="utf-8") as file:
                json.dump(data, file, separators=(",", ":"))
            os.replace(temp, target)
            return True
        except Exception:  # (offline, a broken download …): the old one stays
            import logging

            logging.getLogger("gamingcrypt.saves").warning("couldn't fetch the save list", exc_info=True)
            return target.exists()
        finally:
            raw.unlink(missing_ok=True)
            temp.unlink(missing_ok=True)


def load(cache: Path | None = None) -> dict | None:
    """The kept list (read once, again when it changed) - None when there's none."""
    global _loaded
    target = path(cache)
    try:
        stamp = target.stat().st_mtime
    except OSError:
        return None
    with _lock:
        if _loaded is not None and _loaded[0] == stamp and _loaded[1].get("_from") == str(target):
            return _loaded[1]
        try:
            with gzip.open(target, "rt", encoding="utf-8") as file:
                data = json.load(file)
        except (OSError, ValueError, EOFError):
            return None
        data["_from"] = str(target)
        _loaded = (stamp, data)
        return data


# --- a game in it ------------------------------------------------------------------------------

def find(data: dict | None, game, steam_appid: int | None = None) -> str | None:
    """The list's title of this game: by its Steam game (as the covers matched it), else by name."""
    if not data:
        return None
    if steam_appid:
        title = data.get("steam", {}).get(str(steam_appid))
        if title:
            return title
    from gamingcrypt.wine.covers import search_name

    for name in dict.fromkeys((game.name, game.path.name, search_name(game.path.name))):
        key = normalize(name)
        if not key:
            continue
        title = data.get("titles", {}).get(key) or data.get("folders", {}).get(key)
        if title:
            return title
    return None


def locations(data: dict | None, title: str | None) -> list[Location]:
    if not data or not title:
        return []
    entry = data.get("games", {}).get(title) or {}
    return [Location(root, place, LISTED, kind) for root, place, kind in entry.get("files", [])]


def for_game(game, cache: Path | None = None, steam_appid: int | None = None) -> tuple[str | None, list[Location]]:
    """(the list's title of it, its places there) - (None, []) when it isn't in the list, or there's no list."""
    data = load(cache)
    title = find(data, game, steam_appid)
    return title, locations(data, title)
