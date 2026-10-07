"""Choosing a game's picture by hand (hold its picture): when the one found is wrong, or
there is none.

Where the pictures come from is what the game's cover comes from anyway:
- emulated games: libretro-thumbnails' box art of the system, searched by name
- Steam, Windows and Linux games: Steam's store, searched by name (a Steam game's own
  picture first)

The chosen picture is written where the cover is kept, so every card and page shows it
from then on. "Drawn cover" writes a file that isn't a picture there: the cover is kept
(nothing is looked up again) and every card draws the game's letter instead.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import quote

import requests

DRAWN = b"drawn by choice\n"  # not a picture: the card draws the letter
MAX_CHOICES = 30


@dataclass(frozen=True)
class Choice:
    name: str
    urls: tuple[str, ...]  # tried in this order


class Offline(Exception):
    pass


def _default_get(url, params=None):
    return requests.get(url, params=params, timeout=15)


def is_picture(data: bytes) -> bool:
    return data[:3] == b"\xff\xd8\xff" or data[:4] == b"\x89PNG"


def steam_pictures(appid: int) -> tuple[str, ...]:
    from gamingcrypt.wine.covers import PICTURES

    return tuple(url.format(appid=appid) for url in PICTURES)


def steam_choices(query: str, get: Callable | None = None, own: tuple[int, str] | None = None) -> list[Choice]:
    """Steam's store search; own: (appid, name) of a Steam game - its picture comes first."""
    from gamingcrypt.wine.covers import SEARCH

    get = get or _default_get

    choices = [Choice(own[1], steam_pictures(own[0]))] if own else []
    if not query.strip():
        return choices
    try:
        response = get(SEARCH, {"term": query, "cc": "us", "l": "english"})
    except requests.RequestException as exc:
        if choices:
            return choices
        raise Offline(str(exc)) from exc
    if response.status_code != 200:
        return choices
    try:
        items = response.json().get("items") or []
    except ValueError:
        return choices
    for item in items:
        if item.get("type", "app") == "app" and "id" in item and (own is None or int(item["id"]) != own[0]):
            choices.append(Choice(item.get("name", ""), steam_pictures(int(item["id"]))))
    return choices[:MAX_CHOICES]


def rom_choices(covers, game, query: str) -> list[Choice]:
    """Box art of the game's system whose name has every word of the query."""
    from gamingcrypt.emulation.covers import BASE, PLAYLISTS, _title, wanted_regions, words

    names = covers.index(game)
    if names is None:
        raise Offline("libretro-thumbnails not reachable")
    wanted = words(query)
    regions = wanted_regions(game.path.name)

    def order(name: str):
        tags = name[len(_title(name)):]
        region = next((i for i, r in enumerate(regions) if r in tags), len(regions))
        return len(words(_title(name))), region, name

    found = sorted((n for n in names if set(wanted) <= set(words(n))), key=order)
    playlist = PLAYLISTS[game.system.id]
    return [Choice(n, (f"{BASE}/{quote(playlist)}/Named_Boxarts/{quote(n)}.png",)) for n in found[:MAX_CHOICES]]


def download(choice: Choice, get: Callable | None = None) -> bytes | None:
    """The picture (the first of its addresses that has one); None: there's none."""
    get = get or _default_get
    for url in choice.urls:
        try:
            response = get(url)
        except requests.RequestException:
            continue
        if response.status_code == 200 and is_picture(response.content or b""):
            return response.content
    return None


def save(path: Path, data: bytes) -> None:
    """The cover from now on - the picture, or DRAWN."""
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(".part")
    part.write_bytes(data)
    part.replace(path)
    path.with_suffix(".nomatch").unlink(missing_ok=True)


@dataclass
class Source:
    """What a game's pictures are searched in, and where its cover is kept."""

    path: Path
    query: str
    search: Callable[[str], list[Choice]]


def source_for(game, tab) -> Source | None:
    """None: no place for its cover (e.g. the drive isn't unlocked)."""
    from gamingcrypt.emulation.library import RomGame
    from gamingcrypt.steam.models import SteamGame
    from gamingcrypt.wine.library import WindowsGame

    if isinstance(game, RomGame):
        from gamingcrypt.emulation.covers import _title

        covers = getattr(tab, "covers", None)
        if covers is None:
            return None
        return Source(covers.path(game), _title(game.path.stem).strip() or game.name,
                      lambda q: rom_choices(covers, game, q))
    if isinstance(game, WindowsGame):  # Linux games too
        from gamingcrypt.wine.covers import search_name

        covers = getattr(tab, f"{game.KIND}_covers", None)
        if covers is None:
            return None
        return Source(covers.path(game), search_name(game.name) or game.name, steam_choices)
    if isinstance(game, SteamGame):
        cache = getattr(tab.service, "cache_dir", None)
        if cache is None:
            return None
        own = (game.appid, game.name)
        return Source(Path(cache) / "images" / f"{game.appid}.jpg", re.sub(r"[™®©]", "", game.name),
                      lambda q: steam_choices(q, own=own))
    return None
