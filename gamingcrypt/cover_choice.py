"""Choosing a picture by hand (hold it, or Options -> Change picture): when the one found
is wrong, or there is none.

Where the pictures come from is what the cover comes from anyway, searched by name:
- emulated games: libretro-thumbnails' box art of the system
- Steam, Windows and Linux games: Steam's store (a Steam game's own picture first)
- movies: films on Wikidata, with their Wikipedia (or Commons) poster
- shows: TVmaze

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
    from gamingcrypt.movies.metadata import USER_AGENT

    return requests.get(url, params=params, timeout=15, headers={"User-Agent": USER_AGENT})  # Wikimedia wants one


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


def movie_choices(query: str, get: Callable | None = None, languages: tuple[str, ...] = ("en",)) -> list[Choice]:
    """Films on Wikidata: each with its English Wikipedia article's poster (all in one
    question), else its poster or picture on Commons."""
    from gamingcrypt.movies import metadata as wiki

    if not query.strip():
        return []
    get = get or _default_get
    lookup = wiki.Lookup(get=lambda url, params: get(url, params), languages=languages)
    try:
        ids = lookup.search(query)
        found = lookup.entities(ids, "labels|claims|sitelinks") if ids else {}
        articles = {q: e["sitelinks"]["enwiki"]["title"] for q, e in found.items()
                    if "enwiki" in e.get("sitelinks", {})}
        posters = {}
        if articles:
            data = lookup._json(wiki.WIKI.format(lang="en"), {
                "action": "query", "prop": "pageimages", "piprop": "thumbnail", "pithumbsize": 600,
                "pilicense": "any", "redirects": 1, "formatversion": 2, "titles": "|".join(articles.values())})
            answer = data.get("query", {})
            renamed = {r["from"]: r["to"] for r in answer.get("normalized", []) + answer.get("redirects", [])}
            pages = {page.get("title"): page.get("thumbnail", {}).get("source")
                     for page in answer.get("pages", [])}
            for q, title in articles.items():
                title = renamed.get(title, title)
                title = renamed.get(title, title)  # normalized, then redirected
                if pages.get(title):
                    posters[q] = pages[title]
    except wiki.Offline as exc:
        raise Offline(str(exc)) from exc
    choices = []
    for q in ids:
        entity = found.get(q)
        if entity is None:
            continue
        urls = [posters[q]] if q in posters else []
        for prop in ("P3383", "P18"):  # film poster / image on Commons
            files = [v for v in map(wiki._value, wiki._claims(entity, prop)) if isinstance(v, str)]
            if files:
                urls.append(wiki.COMMONS_FILE.format(name=quote(files[0].replace(" ", "_"))))
        if urls:
            released = wiki.years(entity)
            label = lookup.label(entity) or query
            choices.append(Choice(f"{label} ({min(released)})" if released else label, tuple(dict.fromkeys(urls))))
    return choices[:MAX_CHOICES]


def show_choices(query: str, get: Callable | None = None) -> list[Choice]:
    """Shows on TVmaze, with their posters."""
    from gamingcrypt.shows.metadata import TVMAZE

    if not query.strip():
        return []
    get = get or _default_get
    try:
        response = get(f"{TVMAZE}/search/shows", {"q": query})
    except requests.RequestException as exc:
        raise Offline(str(exc)) from exc
    if response.status_code != 200:
        return []
    try:
        hits = response.json() or []
    except ValueError:
        return []
    choices = []
    for hit in hits:
        show = hit.get("show") or {}
        image = show.get("image") or {}
        urls = tuple(u for u in (image.get("original"), image.get("medium")) if u)
        if urls:
            year = (show.get("premiered") or "")[:4]
            name = show.get("name") or query
            choices.append(Choice(f"{name} ({year})" if year else name, urls))
    return choices[:MAX_CHOICES]


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
    from gamingcrypt.movies.library import Movie
    from gamingcrypt.shows.library import Show
    from gamingcrypt.steam.models import SteamGame
    from gamingcrypt.wine.library import WindowsGame

    if isinstance(game, Movie):  # (next to the movie, as Kodi has it)
        languages = tuple(dict.fromkeys((*getattr(tab, "languages", ()), "en")))
        return Source(game.cover_path, game.title, lambda q: movie_choices(q, languages=languages))
    if isinstance(game, Show):
        return Source(game.cover_path, game.title, show_choices)

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
