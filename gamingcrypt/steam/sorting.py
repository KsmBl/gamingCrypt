"""Sorting and filtering of the game list."""

from __future__ import annotations

from gamingcrypt.steam.models import SteamGame

# key -> (label, default descending?)
SORT_OPTIONS = {
    "name": ("Name", False),
    "release_date": ("Release date", True),
    "playtime": ("Playtime", True),
    "price": ("Price", True),
    "last_update": ("Latest update", True),
}


def _value(game: SteamGame, key: str):
    return {
        "name": game.name.casefold(),
        "release_date": game.release_date,
        "playtime": game.playtime_minutes,
        "price": game.price_cents,
        "last_update": game.last_updated,
    }[key]


def sort_games(games: list[SteamGame], key: str = "name", descending: bool | None = None) -> list[SteamGame]:
    """Stable sort; games with an unknown value always end up at the bottom."""
    if key not in SORT_OPTIONS:
        raise ValueError(f"unknown sort key {key!r}")
    if descending is None:
        descending = SORT_OPTIONS[key][1]
    known = [g for g in games if _value(g, key) is not None]
    unknown = [g for g in games if _value(g, key) is None]
    by_name = sorted(known, key=lambda g: g.name.casefold())
    ordered = sorted(by_name, key=lambda g: _value(g, key), reverse=descending)
    return ordered + sorted(unknown, key=lambda g: g.name.casefold())


def filter_games(games: list[SteamGame], query: str, installed_only: bool = False) -> list[SteamGame]:
    words = query.casefold().split()
    return [
        g for g in games
        if (not installed_only or g.installed) and all(w in g.name.casefold() for w in words)
    ]
