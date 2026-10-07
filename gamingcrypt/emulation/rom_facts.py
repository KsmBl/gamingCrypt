"""Genre and release year of emulated games, from libretro-database (no account needed).

Its metadat/genre and metadat/releaseyear lists name every game of a system as No-Intro does
("Super Mario World (USA)") - matched to the files like the covers are (emulation/covers).
Cartridge systems and the PSP have them; disc systems (PlayStation, GameCube, …) don't.
Kept on the drive: Emulation/config/metadata/<system>.json, fetched again after a while.
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

BASE = "https://raw.githubusercontent.com/libretro/libretro-database/master/metadat"
FIELDS = ("genre", "releaseyear")
KEEP_DAYS = 30
GAME = re.compile(r'game \(\s*comment "((?:[^"\\]|\\.)*)"\s*(\w+) "([^"]*)"')


def parse_dat(text: str, field: str) -> dict[str, str]:
    """clrmamepro DAT -> {game name: value of ``field``}."""
    return {name: value for name, key, value in GAME.findall(text) if key == field}


def split_genres(value: str) -> tuple[str, ...]:
    """"Action / Platform" -> ("Action", "Platform")."""
    return tuple(g.strip() for g in re.split(r"\s*[/,]\s*", value) if g.strip())


class RomFacts:
    def __init__(self, paths: EmulationPaths, get: Callable | None = None, now: Callable[[], float] = time.time):
        self.folder = paths.config / "metadata"
        self.get = get or (lambda url: requests.get(url, timeout=30))
        self.now = now
        self._tables: dict[str, dict] = {}
        self._found: dict[tuple[str, str], tuple] = {}  # (system, file) -> facts: matched once

    def path(self, system_id: str) -> Path:
        return self.folder / f"{system_id}.json"

    def table(self, system_id: str) -> dict | None:
        """What's known for the system (no network); None: not fetched yet."""
        if system_id not in self._tables:
            try:
                self._tables[system_id] = json.loads(self.path(system_id).read_text())
            except (OSError, ValueError):
                return None
        return self._tables[system_id]

    def needs_fetch(self, system_id: str) -> bool:
        from gamingcrypt.emulation.covers import PLAYLISTS

        if system_id not in PLAYLISTS:
            return False
        table = self.table(system_id)
        return table is None or self.now() - table.get("fetched", 0) > KEEP_DAYS * 86400

    def fetch(self, system_id: str) -> bool:
        """Download the system's lists; False: offline (try later)."""
        from gamingcrypt.emulation.covers import PLAYLISTS

        playlist = PLAYLISTS.get(system_id)
        if playlist is None:
            return True
        table = {"fetched": self.now()}
        for field in FIELDS:
            try:
                response = self.get(f"{BASE}/{field}/{quote(playlist)}.dat")
            except requests.RequestException:
                return False
            if response.status_code == 404:
                table[field] = {}  # libretro has none for this system
            elif response.status_code != 200:
                return False
            else:
                table[field] = parse_dat(response.content.decode(errors="replace"), field)
        self.folder.mkdir(parents=True, exist_ok=True)
        part = self.path(system_id).with_suffix(".part")
        part.write_text(json.dumps(table))
        part.replace(self.path(system_id))
        self._tables[system_id] = table
        self._found = {k: v for k, v in self._found.items() if k[0] != system_id}
        return True

    def facts(self, game: RomGame) -> tuple[tuple[str, ...], int | None]:
        """(genres, release year) of the game - what the lists know (no network)."""
        from gamingcrypt.emulation.covers import best_match

        key = (game.system.id, game.path.name)
        if key in self._found:
            return self._found[key]
        table = self.table(game.system.id)
        if not table:
            return (), None
        genres, years = table.get("genre") or {}, table.get("releaseyear") or {}
        stem = game.path.stem

        def find(names: dict) -> str | None:
            if stem in names:
                return names[stem]
            match = best_match(game.path.name, list(names))
            return names.get(match) if match else None

        genre, year = find(genres), find(years)
        try:
            year_number = int(year[:4]) if year else None
        except ValueError:
            year_number = None
        found = (split_genres(genre) if genre else ()), year_number
        self._found[key] = found
        return found
