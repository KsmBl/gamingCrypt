"""Covers for Windows games: Steam's store knows most PC games - its search finds the game by the
folder's name, and its tall library picture is the cover (as for Steam games).

Kept on the drive: <drive>/Windows Games/.covers/<game>.jpg (".nomatch" when there's none), and
the Steam game it was matched to: <game>.appid ("0": none) - its genres and release date come
from that game's store page (game_facts).
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from typing import Callable

import requests

from gamingcrypt.wine.library import WindowsGame

SEARCH = "https://store.steampowered.com/api/storesearch/"
PICTURES = ("https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/{appid}/library_600x900.jpg",
            "https://cdn.akamai.steamstatic.com/steam/apps/{appid}/library_600x900.jpg",
            "https://cdn.akamai.steamstatic.com/steam/apps/{appid}/header.jpg")
COVERS, MISS = ".covers", ".nomatch"
MISS_DAYS = 30


def search_name(folder: str) -> str:
    """"Hollow_Knight-v1.5 [GOG]" -> "Hollow Knight"."""
    name = re.sub(r"[\[(][^\])]*[\])]", " ", folder)
    name = re.sub(r"(?<![a-z])v?\d+(\.\d+)+", " ", name, flags=re.IGNORECASE)  # a version, before the dots go
    name = name.replace("_", " ").replace(".", " ")
    name = re.sub(r"\b(gog|repack|setup|portable|goty|edition)\b", " ", name, flags=re.IGNORECASE)
    return re.sub(r"[\s-]+", " ", name).strip(" -")


class Covers:
    def __init__(self, root: Path, get: Callable | None = None, now: Callable[[], float] = time.time):
        self.folder = Path(root) / COVERS
        self.get = get or (lambda url, params=None: requests.get(url, params=params, timeout=15))
        self.now = now

    def path(self, game: WindowsGame) -> Path:
        return self.folder / f"{game.path.name}.jpg"

    def cached(self, game: WindowsGame) -> Path | None:
        path = self.path(game)
        return path if path.exists() else None

    def appid_path(self, game: WindowsGame) -> Path:
        return self.folder / f"{game.path.name}.appid"

    def known_appid(self, game: WindowsGame) -> int | None:
        """The Steam game it was matched to: an app id, 0 (no match) or None (not looked for yet)."""
        try:
            return int(self.appid_path(game).read_text().strip())
        except (OSError, ValueError):
            return None

    def _remember(self, game: WindowsGame, appid: int) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        self.appid_path(game).write_text(str(appid))

    def _search(self, name: str) -> dict | None | bool:
        """The store's best match; None: none; False: offline."""
        from gamingcrypt.movies.metadata import name_score

        try:
            response = self.get(SEARCH, {"term": name, "cc": "us", "l": "english"})
        except requests.RequestException:
            return False
        if response.status_code != 200:
            return False
        try:
            items = response.json().get("items") or []
        except ValueError:
            return False
        return next((item for item in items if item.get("type", "app") == "app"
                     and name_score(name, [item.get("name", "")]) >= 2), None)

    def match_appid(self, game: WindowsGame) -> int | None:
        """Look the game up in the store (for games whose cover came before app ids were kept):
        its app id, 0 for none; None: offline."""
        known = self.known_appid(game)
        if known is not None:
            return known
        match = self._search(search_name(game.name))
        if match is False:
            return None
        appid = int(match["id"]) if match else 0
        self._remember(game, appid)
        return appid

    def fetch(self, game: WindowsGame) -> Path | None:
        """The cover - downloaded once (None: none found, or offline)."""
        path = self.path(game)
        if path.exists():
            return path
        miss = path.with_suffix(MISS)
        try:
            if self.now() - float(miss.read_text()) < MISS_DAYS * 86400:
                return None
        except (OSError, ValueError):
            pass
        match = self._search(search_name(game.name))
        if match is False:
            return None  # offline: later
        self._remember(game, int(match["id"]) if match else 0)
        if match is not None:
            for url in PICTURES:
                try:
                    picture = self.get(url.format(appid=match["id"]))
                except requests.RequestException:
                    return None
                if picture.status_code == 200 and picture.content[:3] == b"\xff\xd8\xff":
                    self.folder.mkdir(parents=True, exist_ok=True)
                    part = path.with_suffix(".part")
                    part.write_bytes(picture.content)
                    part.replace(path)
                    return path
        self.folder.mkdir(parents=True, exist_ok=True)
        miss.write_text(str(self.now()))
        return None
