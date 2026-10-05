"""The movies on the encrypted drive (<drive>/Movies, sub folders too) and what's known about them.

Every movie gets two files next to it, named like it: "<name>.jpg" (the cover) and
"<name>.nfo" (title, description, actors, FSK rating, length - and whether it was
watched and where it was stopped). The .nfo is in Kodi's format, which Jellyfin and
Kodi read as well.
"""

from __future__ import annotations

import re
import threading
import time
import xml.etree.ElementTree as ET
import zlib
from dataclasses import dataclass, field, fields
from datetime import datetime
from pathlib import Path

VIDEO_SUFFIXES = {".mkv", ".mp4", ".m4v", ".avi", ".mov", ".wmv", ".webm", ".mpg", ".mpeg", ".ts", ".m2ts",
                  ".flv", ".ogv"}
SUBTITLE_SUFFIXES = {".srt", ".ass", ".ssa", ".sub", ".idx", ".vtt", ".sup"}
COVER_SUFFIX, INFO_SUFFIX = ".jpg", ".nfo"
ART_NAMES = ("poster", "fanart", "landscape", "thumb")  # "<name>-poster.jpg" (Jellyfin, Kodi)
MOVIE_APPID_BASE = 0x60000000  # below the emulated games' ids, far above any Steam app id
SAMPLE = re.compile(r"(?:^|[\W_])sample(?:[\W_]|$)", re.IGNORECASE)
YEAR = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
RELEASE_TAGS = re.compile(
    r"(?<![^\W_])(?:2160p|1080p|1080i|720p|576p|480p|4k|uhd|hdr|hdr10|bluray|blu-ray|bdrip|brrip|webrip|web-dl|"
    r"webdl|web|hdtv|dvdrip|dvd|remux|x264|x265|h264|h265|h\.264|h\.265|hevc|avc|xvid|divx|aac|ac3|dts|truehd|"
    r"atmos|german|english|dubbed|dl|multi|proper|repack|extended|unrated|uncut|remastered|imax)(?![^\W_])",
    re.IGNORECASE)
EDITION = re.compile(r"(?:\bthe\s+)?\b(?:director'?s|final|theatrical|special|extended|ultimate|collector'?s|anniversary)\s+"
                     r"(?:cut|edition|version)\b", re.IGNORECASE)
LANGUAGE_TAG = re.compile(r"[a-z]{2,3}(?:-[a-z]{2,4})?|forced|sdh|cc|hi|default", re.IGNORECASE)
WATCHED_AT = 0.9  # this far in counts as watched (as Jellyfin does)
RESUME_MIN_S = 60  # stopped earlier: starts from the beginning next time
LAST_PLAYED = "%Y-%m-%d %H:%M:%S"  # Kodi's format


@dataclass
class MovieInfo:
    title: str = ""
    year: int | None = None
    plot: str = ""
    runtime: int = 0  # minutes
    fsk: str = ""  # "FSK 12"
    genres: list[str] = field(default_factory=list)
    directors: list[str] = field(default_factory=list)
    actors: list[tuple[str, str]] = field(default_factory=list)  # (name, role)
    wikidata: str = ""  # found online: its Wikidata id
    looked_up: float = 0  # when it was searched online (0: not yet)
    # watching
    watched: bool = False
    playcount: int = 0
    position: float = 0  # seconds - where it was stopped
    total: float = 0  # seconds - the length the player saw
    last_played: float = 0

    @property
    def resume_at(self) -> float:
        """Where to go on (0: from the start)."""
        if self.position < RESUME_MIN_S or (self.total and self.position >= self.total * WATCHED_AT):
            return 0
        return self.position

    @property
    def minutes(self) -> int:
        return self.runtime or round(self.total / 60)


PROGRESS_FIELDS = ("watched", "playcount", "position", "total", "last_played")


@dataclass
class Movie:
    path: Path
    key: str  # path inside the movies folder: the stable id
    info: MovieInfo
    size: int = 0
    added: float = 0

    @property
    def appid(self) -> int:
        """Stable id for the player (gamescope focus, the game watcher) - not a Steam app."""
        return MOVIE_APPID_BASE | (zlib.crc32(self.key.encode()) & 0x0FFFFFFF)

    @property
    def title(self) -> str:
        return self.info.title or parse_name(self.path.name)[0]

    @property
    def year(self) -> int | None:
        return self.info.year or parse_name(self.path.name)[1]

    @property
    def cover_path(self) -> Path:
        return self.path.with_suffix(COVER_SUFFIX)

    @property
    def info_path(self) -> Path:
        return self.path.with_suffix(INFO_SUFFIX)


def is_movie_appid(appid: int | None) -> bool:
    from gamingcrypt.emulation.library import EMU_APPID_BASE

    return appid is not None and MOVIE_APPID_BASE <= appid < EMU_APPID_BASE


def parse_name(filename: str) -> tuple[str, int | None]:
    """"The.Matrix.1999.1080p.BluRay.x264-GRP.mkv" -> ("The Matrix", 1999)."""
    stem = Path(filename).stem
    text = stem.replace("_", " ")
    if " " not in text.strip():
        text = text.replace(".", " ")
    text = re.sub(r"\[[^\]]*\]", " ", text)
    latest = datetime.now().year + 1
    years = [m for m in YEAR.finditer(text) if m.start() > 0 and int(m.group(1)) <= latest]
    cut, year = len(text), None
    if years:  # the last one: "Blade Runner 2049 (2017)"
        cut, year = years[-1].start(), int(years[-1].group(1))
    tag = RELEASE_TAGS.search(text)
    if tag is not None and tag.start() > 0:
        cut = min(cut, tag.start())
    title = EDITION.sub(" ", re.sub(r"\s*\([^)]*\)", " ", text[:cut]))
    title = re.sub(r"[\s(\[{-]+$", "", re.sub(r"\s+", " ", title)).strip(" .-")
    return title or stem, year


# --- the .nfo file -----------------------------------------------------------------------
_lock = threading.Lock()  # the player's progress and the online lookup write the same files


def _text(root: ET.Element, tag: str) -> str:
    node = root.find(tag)
    return (node.text or "").strip() if node is not None else ""


def _number(text: str, kind=float, default=0):
    try:
        return kind(text)
    except (TypeError, ValueError):
        return default


def _played_time(text: str) -> float:
    try:
        return datetime.strptime(text, LAST_PLAYED).timestamp()
    except ValueError:
        return 0


def read_info(path: Path) -> MovieInfo:
    """What the .nfo says - an empty one when there's none (or it's broken)."""
    try:
        root = ET.fromstring(path.read_bytes())
    except (OSError, ET.ParseError):
        return MovieInfo()
    info = MovieInfo(
        title=_text(root, "title"), year=_number(_text(root, "year"), int, None), plot=_text(root, "plot"),
        runtime=_number(_text(root, "runtime"), int), fsk=_text(root, "mpaa"),
        genres=[(g.text or "").strip() for g in root.findall("genre") if (g.text or "").strip()],
        directors=[(d.text or "").strip() for d in root.findall("director") if (d.text or "").strip()],
        actors=[(_text(a, "name"), _text(a, "role")) for a in root.findall("actor") if _text(a, "name")],
        playcount=_number(_text(root, "playcount"), int), last_played=_played_time(_text(root, "lastplayed")),
        looked_up=_number(_text(root, "gamingcrypt/lookedup")))
    info.watched = _text(root, "watched").lower() == "true" or info.playcount > 0
    for uid in root.findall("uniqueid"):
        if uid.get("type") == "wikidata":
            info.wikidata = (uid.text or "").strip()
    resume = root.find("resume")
    if resume is not None:
        info.position, info.total = _number(_text(resume, "position")), _number(_text(resume, "total"))
    return info


def info_xml(info: MovieInfo) -> bytes:
    root = ET.Element("movie")

    def add(tag: str, value, parent: ET.Element = root) -> ET.Element:
        node = ET.SubElement(parent, tag)
        node.text = str(value)
        return node

    add("title", info.title)
    if info.year:
        add("year", info.year)
    if info.plot:
        add("plot", info.plot)
    if info.runtime:
        add("runtime", info.runtime)
    if info.fsk:
        add("mpaa", info.fsk)
    for genre in info.genres:
        add("genre", genre)
    for director in info.directors:
        add("director", director)
    for order, (name, role) in enumerate(info.actors):
        actor = ET.SubElement(root, "actor")
        add("name", name, actor)
        if role:
            add("role", role, actor)
        add("order", order, actor)
    if info.wikidata:
        add("uniqueid", info.wikidata).attrib.update(type="wikidata", default="true")
    add("playcount", info.playcount)
    add("watched", "true" if info.watched else "false")
    if info.last_played:
        add("lastplayed", datetime.fromtimestamp(info.last_played).strftime(LAST_PLAYED))
    if info.position:
        resume = ET.SubElement(root, "resume")
        add("position", f"{info.position:.1f}", resume)
        add("total", f"{info.total:.1f}", resume)
    if info.looked_up:
        add("lookedup", int(info.looked_up), ET.SubElement(root, "gamingcrypt"))
    ET.indent(root)
    return b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' + ET.tostring(root, encoding="utf-8")


def write_info(path: Path, info: MovieInfo) -> None:
    part = path.with_name(f".{path.name}.part")
    part.write_bytes(info_xml(info))
    part.replace(path)


def change_info(movie: Movie, change) -> MovieInfo:
    """Read the .nfo, change it, write it back - one writer at a time."""
    with _lock:
        info = read_info(movie.info_path)
        change(info)
        write_info(movie.info_path, info)
    movie.info = info
    return info


def set_metadata(movie: Movie, found: MovieInfo) -> MovieInfo:
    """Online info in, the watching state as it is."""

    def change(info: MovieInfo) -> None:
        for f in fields(MovieInfo):
            if f.name not in PROGRESS_FIELDS:
                setattr(info, f.name, getattr(found, f.name))

    return change_info(movie, change)


def set_progress(movie: Movie, position: float, total: float) -> MovieInfo:
    def change(info: MovieInfo) -> None:
        info.position, info.total = max(0.0, position), max(0.0, total or info.total)
        info.title = info.title or movie.title

    return change_info(movie, change)


def finish_watching(movie: Movie, now: float | None = None) -> MovieInfo:
    """The player closed: watched to the end (90 %) - or where to go on next time."""

    def change(info: MovieInfo) -> None:
        info.title = info.title or movie.title
        info.last_played = now or time.time()
        if info.total and info.position >= info.total * WATCHED_AT:
            info.watched, info.playcount = True, info.playcount + 1
            info.position = 0
        elif info.position < RESUME_MIN_S:
            info.position = 0

    return change_info(movie, change)


def set_watched(movie: Movie, watched: bool) -> MovieInfo:
    def change(info: MovieInfo) -> None:
        info.title = info.title or movie.title
        info.watched, info.playcount, info.position = watched, max(info.playcount, 1) if watched else 0, 0

    return change_info(movie, change)


# --- the folder ---------------------------------------------------------------------------
def scan(root: Path) -> list[Movie]:
    """Every video below the folder (not hidden ones, not "sample" clips)."""
    root = Path(root)
    movies = []
    try:
        candidates = sorted(root.rglob("*"))
    except OSError:
        return []
    for path in candidates:
        rel = path.relative_to(root)
        if (path.suffix.lower() not in VIDEO_SUFFIXES or any(part.startswith(".") for part in rel.parts)
                or SAMPLE.search(path.stem)):
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        if not path.is_file():
            continue
        movies.append(Movie(path, rel.as_posix(), read_info(path.with_suffix(INFO_SUFFIX)), stat.st_size,
                            stat.st_mtime))
    return movies


def related_files(movie: Movie) -> list[Path]:
    """Its cover, its info, art and subtitles named after it ("Name.de.srt", "Name-poster.jpg")."""
    stem = movie.path.stem
    found = [movie.cover_path, movie.info_path]
    try:
        siblings = list(movie.path.parent.iterdir())
    except OSError:
        siblings = []
    for f in siblings:
        if f == movie.path or not f.is_file():
            continue
        if f.suffix.lower() in SUBTITLE_SUFFIXES and f.name.startswith(stem + "."):
            tags = f.name[len(stem) + 1:].split(".")[:-1]  # "Name.de.forced.srt" -> de, forced
            if len(tags) <= 3 and all(LANGUAGE_TAG.fullmatch(t) for t in tags):
                found.append(f)
        elif any(f.stem == f"{stem}-{art}" for art in ART_NAMES):
            found.append(f)
    return [f for f in dict.fromkeys(found) if f.exists()]


def removal_size(movie: Movie) -> int:
    total = 0
    for f in [movie.path, *related_files(movie)]:
        try:
            total += f.stat().st_size
        except OSError:
            pass
    return total


def remove(movie: Movie, root: Path) -> int:
    """Delete the movie and everything that belongs to it; the bytes freed. A folder of its
    own that is empty afterwards goes too."""
    freed = removal_size(movie)
    with _lock:
        for f in [movie.path, *related_files(movie)]:
            try:
                f.unlink(missing_ok=True)
            except OSError:
                pass
    folder, root = movie.path.parent, Path(root)
    while folder != root and root in folder.parents:
        try:
            folder.rmdir()  # only when empty
        except OSError:
            break
        folder = folder.parent
    return freed


# --- searching, filtering, sorting --------------------------------------------------------
STATES = {"all": "All", "new": "Unwatched", "progress": "In progress", "watched": "Watched"}
SORTS = {"title": "Title A-Z", "added": "Recently added", "year": "Newest first", "length": "Shortest first"}
AGES = (0, 6, 12, 16, 18)  # the FSK ratings


def fsk_age(info: MovieInfo) -> int | None:
    match = re.search(r"\d+", info.fsk)
    return int(match.group()) if match else None


def state(info: MovieInfo) -> str:
    if info.resume_at:
        return "progress"
    return "watched" if info.watched else "new"


def matches(movie: Movie, query: str) -> bool:
    """Every word somewhere in the title, the file name, a director or an actor."""
    info = movie.info
    text = " ".join([movie.title, movie.path.stem, *info.directors, *(name for name, _r in info.actors)]).casefold()
    return all(word in text for word in query.casefold().split())


def filter_movies(movies: list[Movie], query: str = "", watch_state: str = "all", genre: str = "",
                  max_age: int | None = None) -> list[Movie]:
    """max_age: only movies known to be rated up to that FSK age (unknown ones are left out)."""
    return [m for m in movies
            if matches(m, query) and watch_state in ("all", state(m.info)) and (not genre or genre in m.info.genres)
            and (max_age is None or (fsk_age(m.info) is not None and fsk_age(m.info) <= max_age))]


def sort_movies(movies: list[Movie], key: str = "title") -> list[Movie]:
    by_title = sorted(movies, key=lambda m: m.title.casefold())
    if key == "added":
        return sorted(by_title, key=lambda m: -m.added)
    if key == "year":
        return sorted(by_title, key=lambda m: -(m.year or 0))
    if key == "length":
        return sorted(by_title, key=lambda m: m.info.minutes or 10**6)
    return by_title


def genres(movies: list[Movie]) -> list[str]:
    return sorted({g for m in movies for g in m.info.genres}, key=str.casefold)


def format_length(minutes: int) -> str:
    if not minutes:
        return ""
    return f"{minutes // 60} h {minutes % 60} min" if minutes >= 60 else f"{minutes} min"


def format_time(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 3600}:{seconds // 60 % 60:02d}:{seconds % 60:02d}"
