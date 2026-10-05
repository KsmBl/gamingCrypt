"""Finding a movie online: Wikidata for the facts, Wikipedia for description and cover.

No account or API key needed. A film is searched by its title (from the file name),
the year decides between remakes. From Wikidata: title, year, length (P2047), FSK
rating (P1981), genres (P136), director (P57), actors with their roles (P161 / P453).
From the movie's Wikipedia article: its introduction as description and the poster.
"""

from __future__ import annotations

import re
import time
import unicodedata
from pathlib import Path
from typing import Callable

import requests

from gamingcrypt.movies.library import Movie, MovieInfo, parse_name, set_metadata

WIKIDATA = "https://www.wikidata.org/w/api.php"
WIKI = "https://{lang}.wikipedia.org/w/api.php"
COMMONS_FILE = "https://commons.wikimedia.org/wiki/Special:FilePath/{name}?width=600"
USER_AGENT = "GamingCrypt (https://github.com/KsmBl/gamingCrypt)"
FILM_CLASSES = ("Q11424", "Q202866", "Q24869", "Q506240", "Q229390")  # film, animated, feature, TV, 3D
UNITS = {"Q7727": 1, "Q25235": 60, "Q11574": 1 / 60}  # minute, hour, second -> minutes
MAX_ACTORS, MAX_GENRES = 15, 4
RETRY_DAYS = 30  # not found: asked again after this long


class Offline(Exception):
    """No answer - try again later."""


def _plain(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.casefold()).replace("&", " and ")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return " ".join(re.findall(r"[^\W_]+", text))


def name_score(title: str, names: list[str]) -> int:
    """3: the same name, 2: one contains the other word by word, 0: different."""
    wanted = _plain(title)
    if not wanted:
        return 0
    best = 0
    for name in names:
        plain = _plain(name)
        if not plain:
            continue
        if plain == wanted:
            return 3
        if f" {wanted} " in f" {plain} " or f" {plain} " in f" {wanted} ":
            best = 2
    return best


def _claims(entity: dict, prop: str) -> list[dict]:
    return [c for c in entity.get("claims", {}).get(prop, []) if c.get("rank") != "deprecated"]


def _value(claim: dict):
    return claim.get("mainsnak", {}).get("datavalue", {}).get("value")


def _item(claim: dict) -> str | None:
    value = _value(claim)
    return value.get("id") if isinstance(value, dict) else None


def years(entity: dict) -> list[int]:
    found = []
    for claim in _claims(entity, "P577"):
        value = _value(claim)
        if isinstance(value, dict) and re.match(r"[+-]\d{4}", value.get("time", "")):
            found.append(int(value["time"][1:5]))
    return found


def names(entity: dict) -> list[str]:
    found = [label["value"] for label in entity.get("labels", {}).values()]
    found += [alias["value"] for aliases in entity.get("aliases", {}).values() for alias in aliases]
    found += [v.get("text", "") for v in map(_value, _claims(entity, "P1476")) if isinstance(v, dict)]
    return found


def score(entity: dict, title: str, year: int | None) -> int | None:
    """How well a search result fits; None: not this movie."""
    by_name = name_score(title, names(entity))
    if not by_name:
        return None
    released = years(entity)
    if year and released:
        if year in released:
            return by_name + 3
        if any(abs(year - y) <= 1 for y in released):
            return by_name + 1
        return by_name - 3
    return by_name


def runtime(entity: dict) -> int:
    for claim in _claims(entity, "P2047"):
        value = _value(claim)
        if not isinstance(value, dict):
            continue
        unit = value.get("unit", "").rsplit("/", 1)[-1]
        try:
            amount = float(value.get("amount", "0"))
        except ValueError:
            continue
        if unit in UNITS and amount > 0:
            return round(amount * UNITS[unit])
    return 0


def cast(entity: dict) -> list[tuple[str, str | None]]:
    """(actor item, role item or role text) in billing order - voice actors for animated films."""
    found = []
    for index, claim in enumerate(_claims(entity, "P161") or _claims(entity, "P725")):
        actor = _item(claim)
        if actor is None:
            continue
        qualifiers = claim.get("qualifiers", {})
        order = None
        for q in qualifiers.get("P1545", []):
            try:
                order = int(q["datavalue"]["value"])
            except (KeyError, TypeError, ValueError):
                pass
        role = None
        for q in qualifiers.get("P453", []):
            value = q.get("datavalue", {}).get("value")
            role = value.get("id") if isinstance(value, dict) else role
        for q in qualifiers.get("P4633", []):  # the role as text
            role = role or "text:" + str(q.get("datavalue", {}).get("value", ""))
        # billed ones first (series ordinal), then as listed
        found.append(((0, order, index) if order is not None else (1, 0, index), actor, role))
    return [(actor, role) for _key, actor, role in sorted(found)][:MAX_ACTORS]


def genre_name(label: str) -> str:
    """Wikidata's "thriller film" -> "Thriller"."""
    label = re.sub(r"\s+(?:film|movie)$", "", label.strip(), flags=re.IGNORECASE)
    return label[:1].upper() + label[1:]


class Lookup:
    def __init__(self, get: Callable | None = None, languages: tuple[str, ...] = ("en", "de")):
        self.get = get or (lambda url, params: requests.get(url, params=params, timeout=15,
                                                              headers={"User-Agent": USER_AGENT}))
        self.languages = languages

    def _json(self, url: str, params: dict) -> dict:
        try:
            response = self.get(url, {**params, "format": "json"})
        except requests.RequestException as exc:
            raise Offline(str(exc)) from exc
        if response.status_code != 200:
            raise Offline(f"HTTP {response.status_code}")
        try:
            return response.json()
        except ValueError as exc:
            raise Offline("not JSON") from exc

    def search(self, title: str) -> list[str]:
        films = "|".join(f"P31={q}" for q in FILM_CLASSES)
        data = self._json(WIKIDATA, {"action": "query", "list": "search", "srlimit": 10,
                                     "srsearch": f"{title} haswbstatement:{films}"})
        return [hit["title"] for hit in data.get("query", {}).get("search", []) if hit.get("title", "")[:1] == "Q"]

    def entities(self, ids: list[str], props: str) -> dict:
        found = {}
        for start in range(0, len(ids), 50):
            data = self._json(WIKIDATA, {"action": "wbgetentities", "ids": "|".join(ids[start:start + 50]),
                                         "props": props, "languages": "|".join((*self.languages, "mul"))})
            found.update(data.get("entities", {}))
        return found

    def label(self, entity: dict) -> str:
        labels = entity.get("labels", {})
        for lang in (*self.languages, "mul"):
            if lang in labels:
                return labels[lang]["value"]
        return next((label["value"] for label in labels.values()), "")

    def best(self, title: str, year: int | None) -> dict | None:
        ids = self.search(title)
        if not ids:
            return None
        found = self.entities(ids, "labels|aliases|claims|sitelinks")
        ranked = [(s, -rank, found[q]) for rank, q in enumerate(ids) if q in found
                  for s in [score(found[q], title, year)] if s is not None and s >= 2]
        return max(ranked, key=lambda r: (r[0], r[1]))[2] if ranked else None

    def article(self, entity: dict) -> tuple[str, str]:
        """(description, poster url) from the movie's Wikipedia article."""
        sitelinks = entity.get("sitelinks", {})
        plot = poster = ""
        for lang in (*self.languages, "en"):  # English articles have the posters
            link = sitelinks.get(f"{lang}wiki")
            if link is None or (plot and poster):
                continue
            data = self._json(WIKI.format(lang=lang), {
                "action": "query", "prop": "extracts|pageimages", "exintro": 1, "explaintext": 1,
                "piprop": "thumbnail", "pithumbsize": 600, "pilicense": "any", "redirects": 1,
                "formatversion": 2, "titles": link["title"]})
            for page in data.get("query", {}).get("pages", []):
                plot = plot or (page.get("extract") or "").strip()
                poster = poster or page.get("thumbnail", {}).get("source", "")
        if not poster:
            for prop in ("P3383", "P18"):  # film poster / image on Commons
                files = [v for v in map(_value, _claims(entity, prop)) if isinstance(v, str)]
                if files:
                    poster = COMMONS_FILE.format(name=requests.utils.quote(files[0].replace(" ", "_")))
                    break
        return plot, poster

    def find(self, title: str, year: int | None) -> tuple[MovieInfo, str] | None:
        """(info, poster url); None: no such film. Raises Offline."""
        entity = self.best(title, year)
        if entity is None:
            return None
        claims = {p: [i for i in map(_item, _claims(entity, p)) if i] for p in ("P1981", "P136", "P57")}
        people = cast(entity)
        wanted = {*claims["P1981"][:1], *claims["P136"], *claims["P57"],
                  *(a for a, _r in people), *(r for _a, r in people if r and not r.startswith("text:"))}
        labels = {q: self.label(e) for q, e in self.entities(sorted(wanted), "labels").items()} if wanted else {}

        def role(r: str | None) -> str:
            return "" if r is None else r[5:] if r.startswith("text:") else labels.get(r, "")

        plot, poster = self.article(entity)
        released = years(entity)
        info = MovieInfo(
            title=self.label(entity) or title, year=min(released) if released else year, plot=plot,
            runtime=runtime(entity), fsk=next((labels[q] for q in claims["P1981"][:1] if labels.get(q)), ""),
            genres=[genre_name(labels[q]) for q in claims["P136"] if labels.get(q)][:MAX_GENRES],
            directors=[labels[q] for q in claims["P57"] if labels.get(q)],
            actors=[(labels[a], role(r)) for a, r in people if labels.get(a)], wikidata=entity.get("id", ""))
        return info, poster

    def download_cover(self, url: str, path: Path) -> bool:
        """Save it as JPEG next to the movie."""
        try:
            response = self.get(url, {})
        except requests.RequestException:
            return False
        if response.status_code != 200 or not response.content:
            return False
        from PySide6.QtGui import QImage

        image = QImage.fromData(response.content)
        if image.isNull():
            return False
        part = path.with_name(f".{path.name}.part")
        if not image.save(str(part), "JPG", 90):
            part.unlink(missing_ok=True)
            return False
        part.replace(path)
        return True


def needs_lookup(movie: Movie, now: float) -> bool:
    info = movie.info
    if info.wikidata:
        return False
    return not info.looked_up or now - info.looked_up > RETRY_DAYS * 86400


def update(movie: Movie, lookup: Lookup, now: Callable[[], float] = time.time) -> bool:
    """Search the movie online and save cover + info next to it. False: offline (try later)."""
    title, year = parse_name(movie.path.name)
    try:
        result = lookup.find(title, year)
    except Offline:
        return False
    if result is None:  # not found: the name from the file, asked again in a while
        set_metadata(movie, MovieInfo(title=title, year=year, looked_up=now()))
        return True
    info, poster = result
    info.looked_up = now()
    if poster and not movie.cover_path.exists():
        lookup.download_cover(poster, movie.cover_path)
    set_metadata(movie, info)
    return True


def languages_for(config: dict) -> tuple[str, ...]:
    """German Steam: German titles and descriptions first."""
    language = (config.get("steam", {}).get("language") or "english").lower()
    return ("de", "en") if language.startswith(("german", "deutsch")) else ("en", "de")
