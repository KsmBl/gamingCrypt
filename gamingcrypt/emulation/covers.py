"""Cover art for emulated games from libretro-thumbnails (no account needed).

Looked up by the file name - the usual "Name (Region)" dumps match exactly; names
without a region get the common ones tried. Covers (and misses, so the network isn't
asked over and over) are kept on the encrypted drive: Emulation/config/covers.
"""

from __future__ import annotations

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
        miss = self.path(game).with_suffix(".miss")
        try:
            return self.now() - float(miss.read_text()) < MISS_DAYS * 86400
        except (OSError, ValueError):
            return False

    def fetch(self, game: RomGame) -> Path | None:
        """Cached cover, or download it (None: there's none, or offline)."""
        cached = self.cached(game)
        if cached is not None or self._missed_recently(game):
            return cached
        path = self.path(game)
        offline = False
        for url in urls(game):
            try:
                response = self.get(url)
            except requests.RequestException:
                offline = True
                break
            if response.status_code == 200 and response.content[:4] == b"\x89PNG":
                path.parent.mkdir(parents=True, exist_ok=True)
                part = path.with_suffix(".part")
                part.write_bytes(response.content)
                part.replace(path)
                return path
        if not offline:  # really not there: don't ask again for a while
            path.parent.mkdir(parents=True, exist_ok=True)
            path.with_suffix(".miss").write_text(str(self.now()))
        return None
