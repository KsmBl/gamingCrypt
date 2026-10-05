"""Cover art for emulated games from libretro-thumbnails (no account needed).

Looked up by the file name - the usual "Name (Region)" dumps match exactly; names
without a region get the common ones tried. Anything else (patched, translated, renamed
dumps: "Final Fantasy VII - German Retranslation") is matched against the list of all
covers of the system: the longest official title whose words are all in the file name,
in the file's region if possible. Covers (and misses, so the network isn't asked over
and over) are kept on the encrypted drive: Emulation/config/covers.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Callable
from urllib.parse import quote

import requests

from gamingcrypt.emulation.library import EmulationPaths, RomGame

BASE = "https://thumbnails.libretro.com"
PLAYLISTS = {
    "nes": "Nintendo - Nintendo Entertainment System", "snes": "Nintendo - Super Nintendo Entertainment System",
    "n64": "Nintendo - Nintendo 64", "gb": "Nintendo - Game Boy", "gbc": "Nintendo - Game Boy Color",
    "gba": "Nintendo - Game Boy Advance", "nds": "Nintendo - Nintendo DS", "gc": "Nintendo - GameCube",
    "mastersystem": "Sega - Master System - Mark III", "megadrive": "Sega - Mega Drive - Genesis",
    "gamegear": "Sega - Game Gear", "segacd": "Sega - Mega-CD - Sega CD", "saturn": "Sega - Saturn",
    "dreamcast": "Sega - Dreamcast", "psx": "Sony - PlayStation", "ps2": "Sony - PlayStation 2",
    "psp": "Sony - PlayStation Portable", "switch": "Nintendo - Nintendo Switch",
    "pce": "NEC - PC Engine - TurboGrafx 16", "atari2600": "Atari - 2600", "arcade": "MAME",
}
REGIONS = ("(USA)", "(Europe)", "(World)", "(USA, Europe)", "(Japan)")
MISS_DAYS = 7
MISS = ".nomatch"  # (".miss" files from before the matching are ignored: they're retried)
INDEX_DAYS = 30
REGION_WORDS = {"germany": "Germany", "german": "Germany", "deu": "Germany", "ger": "Germany", "de": "Germany",
                "europe": "Europe", "eur": "Europe", "pal": "Europe", "usa": "USA", "us": "USA", "ntsc": "USA",
                "japan": "Japan", "jpn": "Japan", "jp": "Japan", "france": "France", "fr": "France",
                "spain": "Spain", "italy": "Italy", "world": "World"}
DEFAULT_REGIONS = ("Europe", "USA", "World", "Japan")
SKIP_WORDS = {"the", "a", "an"}
BAD_CHARS = re.compile(r'[&*/:`<>?\\|"]')  # libretro writes these as "_"


def thumbnail_names(game: RomGame) -> list[str]:
    stem = BAD_CHARS.sub("_", game.path.stem)
    names = [stem]
    if "(" not in stem:  # tidied up name: try the usual regions
        names += [f"{stem} {region}" for region in REGIONS]
    return names


def urls(game: RomGame) -> list[str]:
    playlist = PLAYLISTS.get(game.system.id)
    if playlist is None:
        return []
    return [f"{BASE}/{quote(playlist)}/Named_Boxarts/{quote(name)}.png" for name in thumbnail_names(game)]


def words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in SKIP_WORDS]


def _title(name: str) -> str:
    """ "Legend of Zelda, The - Ocarina of Time (USA)" -> its title without the tags."""
    return re.sub(r"\s*[\(\[][^\)\]]*[\)\]]", "", name)


def wanted_regions(filename: str) -> list[str]:
    """Regions the file says it's from (tags and words), then the usual ones."""
    found = [REGION_WORDS[w] for w in re.findall(r"[a-z]+", filename.lower()) if w in REGION_WORDS]
    return list(dict.fromkeys(found + list(DEFAULT_REGIONS)))


def best_match(filename: str, names: list[str]) -> str | None:
    """The cover name for a file that has no exact match."""
    own = set(words(_title(filename)))
    if not own:
        return None
    regions = wanted_regions(filename)
    disc = re.search(r"(?:disc|disk|cd)\s*(\d+)", filename.lower())

    def score(name: str):
        tags = name[len(_title(name)):]
        region = next((len(regions) - i for i, r in enumerate(regions) if r in tags), 0)
        name_disc = re.search(r"\(disc (\d+)\)", name.lower())
        same_disc = (name_disc.group(1) == disc.group(1)) if disc and name_disc else name_disc is None
        return len(set(words(_title(name)))), region, same_disc, -len(name)

    candidates = [n for n in names if (title := set(words(_title(n)))) and title <= own]
    return max(candidates, key=score) if candidates else None


class Covers:
    def __init__(self, paths: EmulationPaths, get: Callable | None = None, now: Callable[[], float] = time.time):
        self.folder = paths.config / "covers"
        self.get = get or (lambda url: requests.get(url, timeout=15))
        self.now = now

    def path(self, game: RomGame) -> Path:
        return self.folder / game.system.id / f"{game.path.stem}.png"

    def cached(self, game: RomGame) -> Path | None:
        path = self.path(game)
        return path if path.exists() else None

    def _missed_recently(self, game: RomGame) -> bool:
        miss = self.path(game).with_suffix(MISS)
        try:
            return self.now() - float(miss.read_text()) < MISS_DAYS * 86400
        except (OSError, ValueError):
            return False

    def index(self, game: RomGame) -> list[str] | None:
        """All cover names of the system (cached on the drive for a while); None: offline."""
        playlist = PLAYLISTS.get(game.system.id)
        if playlist is None:
            return None
        cache = self.folder / game.system.id / ".index.json"
        try:
            if self.now() - cache.stat().st_mtime < INDEX_DAYS * 86400:
                return json.loads(cache.read_text())
        except (OSError, ValueError):
            pass
        try:
            response = self.get(f"{BASE}/{quote(playlist)}/Named_Boxarts/")
        except requests.RequestException:
            return None
        if response.status_code != 200:
            return []  # no list for this system: nothing to match against
        from urllib.parse import unquote

        text = response.content.decode(errors="replace")
        names = sorted({unquote(n) for n in re.findall(r'href="([^"/?]+)\.png"', text)})
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(names))
        return names

    def _download(self, url: str, path: Path) -> bool | None:
        """True: saved; False: not there; None: offline."""
        try:
            response = self.get(url)
        except requests.RequestException:
            return None
        if response.status_code == 200 and response.content[:4] == b"\x89PNG":
            path.parent.mkdir(parents=True, exist_ok=True)
            part = path.with_suffix(".part")
            part.write_bytes(response.content)
            part.replace(path)
            return True
        return False

    def fetch(self, game: RomGame) -> Path | None:
        """Cached cover, or download it (None: there's none, or offline)."""
        cached = self.cached(game)
        if cached is not None or self._missed_recently(game):
            return cached
        path = self.path(game)
        for url in urls(game):
            result = self._download(url, path)
            if result is None:
                return None  # offline: try again later
            if result:
                return path
        names = self.index(game)
        if names is None:
            return None  # offline
        match = best_match(game.path.name, names)
        if match is not None:
            playlist = PLAYLISTS[game.system.id]
            result = self._download(f"{BASE}/{quote(playlist)}/Named_Boxarts/{quote(match)}.png", path)
            if result is None:
                return None
            if result:
                return path
        path.parent.mkdir(parents=True, exist_ok=True)  # really not there: don't ask again for a while
        path.with_suffix(MISS).write_text(str(self.now()))
        return None
