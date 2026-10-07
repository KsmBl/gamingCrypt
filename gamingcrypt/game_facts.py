"""Genres, release year and platform of every installed game - for the Games tab's filters.

- Steam games: their store page (fetched in the background, kept with the Steam metadata)
- Windows / Linux games: the store page of the Steam game their cover was matched to
- emulated games: their system (no free source knows their genres)
"""

from __future__ import annotations

import time
from dataclasses import dataclass

DECADES = {"2020": "2020s", "2010": "2010s", "2000": "2000s", "1990": "1990s", "old": "Before 1990"}
SORTS = {"name": "Name", "newest": "Newest first", "oldest": "Oldest first", "played": "Last played"}


@dataclass(frozen=True)
class Facts:
    platform: str = ""
    genres: tuple[str, ...] = ()
    year: int | None = None


def _year(timestamp) -> int | None:
    return time.gmtime(timestamp).tm_year if timestamp else None


def steam_appid_of(game, tab) -> int | None:
    """The Steam game behind a Windows / Linux game, if it was matched (no network)."""
    covers = getattr(tab, f"{getattr(game, 'KIND', '')}_covers", None)
    appid = covers.known_appid(game) if covers is not None and hasattr(covers, "known_appid") else None
    return appid or None


def facts_of(game, tab) -> Facts:
    from gamingcrypt.emulation.library import RomGame
    from gamingcrypt.wine.library import WindowsGame

    if isinstance(game, RomGame):
        from gamingcrypt.emulation.systems import short_name

        return Facts(short_name(game.system.id))
    if isinstance(game, WindowsGame):
        appid = steam_appid_of(game, tab)
        stored = getattr(tab.service, "stored_metadata", None)
        meta = stored(appid) if appid and stored is not None else {}
        return Facts(game.LABEL, tuple(meta.get("genres") or ()), _year(meta.get("release_date")))
    return Facts("Steam", tuple(getattr(game, "genres", None) or ()), _year(getattr(game, "release_date", None)))


def last_played(game) -> int:
    return int(getattr(game, "last_played", None) or 0)


def in_decade(year: int | None, decade: str) -> bool:
    if not decade:
        return True
    if year is None:
        return False
    if decade == "old":
        return year < 1990
    return int(decade) <= year < int(decade) + 10


def choose(games: list, facts: dict[int, Facts], genre: str = "", platform: str = "", decade: str = "",
           sort: str = "name") -> list:
    """The games that match, in the chosen order (unknown years last)."""
    shown = [g for g in games
             if (not genre or genre in facts[g.appid].genres)
             and (not platform or facts[g.appid].platform == platform)
             and in_decade(facts[g.appid].year, decade)]
    by_name = sorted(shown, key=lambda g: g.name.casefold())
    if sort == "newest":
        return sorted(by_name, key=lambda g: (facts[g.appid].year is None, -(facts[g.appid].year or 0)))
    if sort == "oldest":
        return sorted(by_name, key=lambda g: (facts[g.appid].year is None, facts[g.appid].year or 0))
    if sort == "played":
        return sorted(by_name, key=lambda g: -last_played(g))
    return by_name


def all_genres(facts: dict[int, Facts]) -> list[str]:
    return sorted({g for f in facts.values() for g in f.genres}, key=str.casefold)


def all_platforms(facts: dict[int, Facts]) -> list[str]:
    """Steam, Windows, Linux first, then the systems by name."""
    order = {"Steam": 0, "Windows": 1, "Linux": 2}
    return sorted({f.platform for f in facts.values() if f.platform}, key=lambda p: (order.get(p, 3), p))
