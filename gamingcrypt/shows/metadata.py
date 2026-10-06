"""Finding a show online: TVmaze for the show, its episodes and cast; Wikidata for the FSK rating.

No account or API key needed. TVmaze (api.tvmaze.com) knows nearly every show with
every episode's title, summary, air date and picture. The FSK rating comes from Wikidata,
found by the show's IMDb id - and with German first, the German Wikipedia's description.
"""

from __future__ import annotations

import html
import re
import time
from typing import Callable

import requests

from gamingcrypt.movies import library as movies
from gamingcrypt.movies.metadata import USER_AGENT, WIKIDATA, Lookup as MovieLookup, Offline, name_score
from gamingcrypt.movies.library import MovieInfo
from gamingcrypt.shows.library import Show

TVMAZE = "https://api.tvmaze.com"
MAX_ACTORS = 15
RETRY_DAYS = 30


def plain(text: str | None) -> str:
    """TVmaze's summaries are HTML."""
    text = re.sub(r"<br\s*/?>|</p>\s*<p>", "\n", text or "")
    return html.unescape(re.sub(r"<[^>]+>", "", text)).strip()


def _year(date: str | None) -> int | None:
    return int(date[:4]) if date and re.match(r"\d{4}", date) else None


class ShowLookup:
    def __init__(self, get: Callable | None = None, languages: tuple[str, ...] = ("en", "de")):
        self.get = get or (lambda url, params: requests.get(url, params=params, timeout=15,
                                                              headers={"User-Agent": USER_AGENT}))
        self.languages = languages
        self.wiki = MovieLookup(self.get, languages)

    def _json(self, url: str, params: dict):
        try:
            response = self.get(url, params)
        except requests.RequestException as exc:
            raise Offline(str(exc)) from exc
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise Offline(f"HTTP {response.status_code}")
        try:
            return response.json()
        except ValueError as exc:
            raise Offline("not JSON") from exc

    def best(self, name: str, year: int | None) -> dict | None:
        found = self._json(f"{TVMAZE}/search/shows", {"q": name}) or []
        ranked = []
        for rank, hit in enumerate(found):
            show = hit.get("show") or {}
            score = name_score(name, [show.get("name", "")])
            if not score:
                continue
            premiered = _year(show.get("premiered"))
            if year and premiered:
                score += 3 if premiered == year else -3
            ranked.append((score, -rank, show))
        return max(ranked, key=lambda r: (r[0], r[1]))[2] if ranked else None

    def wikidata(self, imdb: str | None) -> dict | None:
        """The show's Wikidata entry, by its IMDb id."""
        if not imdb:
            return None
        data = self.wiki._json(WIKIDATA, {"action": "query", "list": "search", "srlimit": 1,
                                          "srsearch": f"haswbstatement:P345={imdb}"})
        hits = [h["title"] for h in data.get("query", {}).get("search", [])]
        if not hits:
            return None
        return self.wiki.entities(hits[:1], "labels|claims|sitelinks").get(hits[0])

    def find(self, name: str, year: int | None) -> tuple[MovieInfo, str, dict] | None:
        """(show info, poster url, {(season, number): episode}); None: not found. Raises Offline."""
        show = self.best(name, year)
        if show is None:
            return None
        full = self._json(f"{TVMAZE}/shows/{show['id']}", {"embed[]": ["episodes", "cast"]}) or show
        embedded = full.get("_embedded", {})
        info = MovieInfo(
            title=full.get("name") or name, year=_year(full.get("premiered")),
            end_year=_year(full.get("ended")) if full.get("status") == "Ended" else None,
            plot=plain(full.get("summary")), runtime=int(full.get("averageRuntime") or full.get("runtime") or 0),
            genres=list(full.get("genres") or [])[:4], tvmaze=str(full.get("id", "")),
            actors=[((c.get("person") or {}).get("name", ""), (c.get("character") or {}).get("name", ""))
                    for c in embedded.get("cast", [])[:MAX_ACTORS] if (c.get("person") or {}).get("name")])
        entity = self.wikidata((full.get("externals") or {}).get("imdb"))
        if entity is not None:
            info.wikidata = entity.get("id", "")
            rating = [i for i in (c.get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("id")
                                  for c in entity.get("claims", {}).get("P1981", [])) if i]
            if rating:
                labels = self.wiki.entities(rating[:1], "labels")
                info.fsk = self.wiki.label(labels.get(rating[0], {}))
            if self.languages[0] != "en":  # TVmaze writes English: the Wikipedia of the language
                plot, _poster = self.wiki.article(entity)
                info.plot = plot or info.plot
        poster = (full.get("image") or {}).get("original") or (full.get("image") or {}).get("medium") or ""
        episodes = {(e.get("season"), e.get("number")): e for e in embedded.get("episodes", [])
                    if e.get("number") is not None}
        return info, poster, episodes


def episode_info(found: dict, show_title: str) -> MovieInfo:
    return MovieInfo(title=found.get("name") or "", plot=plain(found.get("summary")),
                     runtime=int(found.get("runtime") or 0), aired=found.get("airdate") or "",
                     year=_year(found.get("airdate")), season=found.get("season"), episode=found.get("number"),
                     showtitle=show_title, tvmaze=str(found.get("id", "")))


def needs_lookup(show: Show, now: float) -> bool:
    info = show.info
    if info.tvmaze:
        # new episodes added later: they get their info from what's known (see update)
        return any(not e.info.looked_up for e in show.episodes)
    return not info.looked_up or now - info.looked_up > RETRY_DAYS * 86400


def _picture(lookup: ShowLookup, url: str, path) -> None:
    if url and not path.exists():
        lookup.wiki.download_cover(url, path)


def update(show: Show, lookup: ShowLookup, now: Callable[[], float] = time.time) -> bool:
    """Search the show online, save its info, poster and every episode's info and picture.
    False: offline (try again later)."""
    try:
        result = lookup.find(show.name, show.year)
    except Offline:
        return False
    stamp = now()
    if result is None:  # not found: what the names say, asked again in a while
        movies.change_info(show, lambda info: _merge(info, MovieInfo(title=show.name, year=show.year,
                                                                       looked_up=stamp)))
        for episode in show.episodes:
            if not episode.info.looked_up:
                movies.change_info(episode, lambda info, e=episode: _merge(info, MovieInfo(
                    title=e.file_title, season=e.season, episode=e.number, showtitle=show.name, looked_up=stamp)))
        return True
    info, poster, episodes = result
    info.looked_up = stamp
    _picture(lookup, poster, show.cover_path)
    movies.change_info(show, lambda current: _merge(current, info))
    for episode in show.episodes:
        found = episodes.get((episode.season, episode.number))
        if found is None:
            new = MovieInfo(title=episode.file_title, season=episode.season, episode=episode.number,
                            showtitle=info.title)
        else:
            new = episode_info(found, info.title)
            if episode.last and episodes.get((episode.season, episode.last)):  # S01E01-02
                second = episodes[(episode.season, episode.last)]
                new.title = f"{new.title} / {second.get('name')}" if second.get("name") else new.title
                new.runtime += int(second.get("runtime") or 0)
            image = (found.get("image") or {}).get("original") or (found.get("image") or {}).get("medium")
            _picture(lookup, image or "", episode.cover_path)
        new.looked_up = stamp
        movies.change_info(episode, lambda current, new=new: _merge(current, new))
        episode.show_name = info.title
    return True


def _merge(current: MovieInfo, found: MovieInfo) -> None:
    """Online info in, the watching state as it is."""
    from dataclasses import fields

    for f in fields(MovieInfo):
        if f.name not in movies.PROGRESS_FIELDS:
            setattr(current, f.name, getattr(found, f.name))
