"""The shows in <drive>/Shows: episodes grouped into shows, seasons, what to watch next.

Episodes are found by their names - "Show S01E02 - Title.mkv", "show.1x02.mkv",
"Season 1/Episode 2.mkv" - in a folder per show (Jellyfin's way: "Show (2008)/Season 01/…")
or loose in the Shows folder, where the name in the file says which show it belongs to.

Next to every episode: "<name>.nfo" (Kodi's episodedetails: title, plot, watched, where
it was stopped) and "<name>.jpg" (its picture). The show's own info and poster are
"tvshow.nfo" and "poster.jpg" in its folder (Kodi / Jellyfin read them too); a show
without a folder keeps them as "<Show>.tvshow.nfo" and "<Show>.jpg" in the Shows folder.
"""

from __future__ import annotations

import re
import zlib
from dataclasses import dataclass, field
from pathlib import Path

from gamingcrypt.movies import library as movies
from gamingcrypt.movies.library import (MOVIE_APPID_BASE, SAMPLE, VIDEO_SUFFIXES, MovieInfo, read_info,
                                        related_files)

SEASON_FOLDER = re.compile(r"^(?:season|staffel|series|s)[ ._-]*(\d{1,3})\b|^(specials?|extras?)$", re.IGNORECASE)
PATTERNS = (  # season, episode (, last episode of a double one)
    re.compile(r"(?<![a-z0-9])s(\d{1,3})[ ._-]?e(\d{1,4})(?:[ ._-]?(?:-|e)(\d{1,4}))?(?![0-9])", re.IGNORECASE),
    re.compile(r"(?<![a-z0-9])(\d{1,2})x(\d{2,3})(?:-(\d{2,3}))?(?![0-9])", re.IGNORECASE),
    re.compile(r"(?:season|staffel)[ ._-]*(\d{1,3}).*?(?:episode|folge|ep)[ ._-]*(\d{1,4})()", re.IGNORECASE),
)
EPISODE_ONLY = re.compile(r"^(?:e|ep|episode|folge)?[ ._-]*(\d{1,4})(?![0-9])|(?<![a-z0-9])(?:e|ep|episode|folge)[ ._-]*(\d{1,4})(?![0-9])",
                          re.IGNORECASE)
YEAR = re.compile(r"[\s._(\[-]*[(\[]?((?:19|20)\d{2})[)\]]?\s*$")
SHOW_INFO, SHOW_POSTER = "tvshow.nfo", "poster.jpg"


def _clean(text: str) -> str:
    text = text.replace("_", " ")
    if " " not in text.strip():
        text = text.replace(".", " ")
    text = re.sub(r"\[[^\]]*\]", " ", text)
    return re.sub(r"\s+", " ", text).strip(" .-_")


def split_year(name: str) -> tuple[str, int | None]:
    """"Breaking Bad (2008)" -> ("Breaking Bad", 2008)."""
    match = YEAR.search(name)
    if match and match.start() > 0:
        return name[:match.start()].strip(" .-_"), int(match.group(1))
    return name, None


def episode_title(rest: str) -> str:
    """What follows the episode number, without release tags: "- Pilot.720p" -> "Pilot"."""
    rest = _clean(rest)
    tag = movies.RELEASE_TAGS.search(rest)
    if tag is not None:
        rest = rest[:tag.start()]
    return rest.strip(" .-_")


def parse_episode(path: Path, root: Path) -> tuple[str, int | None, int, int | None, str, str | None] | None:
    """(show, season, episode, last episode, title, show folder) - None: not an episode."""
    rel = path.relative_to(root)
    parts = rel.parts
    folder = parts[0] if len(parts) > 1 else None
    season_from_folder = None
    if len(parts) > 2:
        match = SEASON_FOLDER.match(_clean(parts[-2]))
        if match:
            season_from_folder = 0 if match.group(2) else int(match.group(1))
    stem = path.stem
    for pattern in PATTERNS:
        match = pattern.search(stem)
        if match:
            season, number = int(match.group(1)), int(match.group(2))
            last = int(match.group(3)) if match.group(3) else None
            show = _clean(stem[:match.start()])
            title = episode_title(stem[match.end():])
            break
    else:
        if season_from_folder is None and folder is None:
            return None  # loose and without an episode number: not an episode
        match = EPISODE_ONLY.search(_clean(stem))
        if match is None:
            return None
        season = season_from_folder if season_from_folder is not None else 1
        number, last = int(match.group(1) or match.group(2)), None
        show = ""
        title = episode_title(_clean(stem)[match.end():])
    if season_from_folder is not None:
        season = season_from_folder
    if folder is not None:
        show = _clean(folder)
    show = split_year(show)[0] if show else ""
    if not show:
        return None
    return show, season, number, last, title, folder


def show_key(name: str) -> str:
    """Loose episodes of one show: "Breaking.Bad.S01E01" and "breaking bad 1x02" together."""
    return " ".join(re.findall(r"[^\W_]+", name.casefold()))


@dataclass
class Episode:
    path: Path
    key: str  # path inside the Shows folder
    info: MovieInfo
    season: int
    number: int
    last: int | None = None  # a double episode: S01E01-02
    file_title: str = ""
    size: int = 0
    added: float = 0
    show_name: str = ""
    NFO_KIND = "episodedetails"

    @property
    def appid(self) -> int:
        return MOVIE_APPID_BASE | (zlib.crc32(("show:" + self.key).encode()) & 0x0FFFFFFF)

    @property
    def code(self) -> str:
        """"S01E02" ("S01E01-02" for a double one)."""
        last = f"-{self.last:02d}" if self.last else ""
        return f"S{self.season:02d}E{self.number:02d}{last}"

    @property
    def name(self) -> str:
        """Its own title."""
        return self.info.title or self.file_title or f"Episode {self.number}"

    @property
    def title(self) -> str:
        """For the player and the quick menu: "Breaking Bad - S01E02 - Cat's in the Bag…"."""
        return f"{self.show_name} - {self.code} - {self.name}"

    @property
    def cover_path(self) -> Path:
        return self.path.with_suffix(movies.COVER_SUFFIX)

    @property
    def info_path(self) -> Path:
        return self.path.with_suffix(movies.INFO_SUFFIX)

    @property
    def order(self) -> tuple:
        return (self.season == 0, self.season, self.number)  # specials last


@dataclass
class Show:
    name: str  # from the folder or the file names
    key: str  # "folder:<folder>" or "loose:<name>"
    folder: Path | None  # its own folder, if it has one
    root: Path
    info: MovieInfo
    episodes: list[Episode] = field(default_factory=list)
    year: int | None = None
    NFO_KIND = "tvshow"

    @property
    def title(self) -> str:
        return self.info.title or self.name

    @property
    def info_path(self) -> Path:
        if self.folder is not None:
            return self.folder / SHOW_INFO
        return self.root / f"{self.name}.tvshow.nfo"

    @property
    def cover_path(self) -> Path:
        if self.folder is not None:
            return self.folder / SHOW_POSTER
        return self.root / f"{self.name}.jpg"

    @property
    def seasons(self) -> list[int]:
        found = sorted({e.season for e in self.episodes})
        return [s for s in found if s] + ([0] if 0 in found else [])  # specials last

    def season(self, number: int) -> list[Episode]:
        return [e for e in self.episodes if e.season == number]

    @property
    def regular(self) -> list[Episode]:
        """Without the specials (season 0)."""
        return [e for e in self.episodes if e.season] or list(self.episodes)

    @property
    def size(self) -> int:
        return sum(e.size for e in self.episodes)

    @property
    def added(self) -> float:
        return max((e.added for e in self.episodes), default=0)

    @property
    def unwatched(self) -> int:
        return sum(not e.info.watched for e in self.regular)

    @property
    def appids(self) -> set[int]:
        return {e.appid for e in self.episodes}


def scan(root: Path) -> list[Show]:
    """Every show below the folder, its episodes in order."""
    root = Path(root)
    shows: dict[str, Show] = {}
    try:
        candidates = sorted(root.rglob("*"))
    except OSError:
        return []
    for path in candidates:
        rel = path.relative_to(root)
        if (path.suffix.lower() not in VIDEO_SUFFIXES or any(part.startswith(".") for part in rel.parts)
                or SAMPLE.search(path.stem)):
            continue
        parsed = parse_episode(path, root)
        if parsed is None:
            continue
        name, season, number, last, title, folder = parsed
        try:
            stat = path.stat()
        except OSError:
            continue
        key = f"folder:{folder}" if folder is not None else f"loose:{show_key(name)}"
        show = shows.get(key)
        if show is None:
            folder_path = root / folder if folder is not None else None
            year = split_year(_clean(folder))[1] if folder is not None else None
            show = Show(name, key, folder_path, root, MovieInfo(), year=year)
            show.info = read_info(show.info_path)
            shows[key] = show
        show.episodes.append(Episode(path, rel.as_posix(), read_info(path.with_suffix(movies.INFO_SUFFIX)), season,
                                     number, last, title, stat.st_size, stat.st_mtime, show.name))
    for show in shows.values():
        show.episodes.sort(key=lambda e: (e.order, e.path.name))
        for episode in show.episodes:
            episode.show_name = show.title
    return sorted(shows.values(), key=lambda s: s.title.casefold())


# --- watching -------------------------------------------------------------------------------
def next_up(show: Show) -> Episode | None:
    """What "Continue" plays: the one stopped in the middle, else the one after the last
    watched one (the first when nothing was watched). None: all watched."""
    episodes = show.regular
    started = [e for e in episodes if e.info.resume_at]
    if started:
        return max(started, key=lambda e: e.info.last_played)
    watched = [i for i, e in enumerate(episodes) if e.info.watched]
    start = watched[-1] + 1 if watched else 0
    return next((e for e in episodes[start:] if not e.info.watched),
                next((e for e in episodes if not e.info.watched), None))


def following(show: Show, episode: Episode) -> Episode | None:
    """The episode after this one (autoplay)."""
    episodes = show.episodes
    for index, current in enumerate(episodes):
        if current.key == episode.key:
            later = episodes[index + 1:]
            return later[0] if later and (later[0].season == episode.season or later[0].season) else None
    return None


def state(show: Show) -> str:
    """new (nothing watched), progress, watched (every episode)."""
    episodes = show.regular
    if episodes and all(e.info.watched for e in episodes):
        return "watched"
    if any(e.info.watched or e.info.resume_at for e in episodes):
        return "progress"
    return "new"


def set_show_watched(show: Show, watched: bool) -> None:
    for episode in show.regular:
        movies.set_watched(episode, watched)


# --- searching, filtering, sorting ----------------------------------------------------------
SORTS = {"title": "Title A-Z", "added": "Recently added", "year": "Newest first"}


def matches(show: Show, query: str) -> bool:
    info = show.info
    text = " ".join([show.title, show.name, *(name for name, _r in info.actors), *info.directors]).casefold()
    return all(word in text for word in query.casefold().split())


def filter_shows(shows: list[Show], query: str = "", watch_state: str = "all", genre: str = "",
                 max_age: int | None = None) -> list[Show]:
    return [s for s in shows
            if matches(s, query) and watch_state in ("all", state(s)) and (not genre or genre in s.info.genres)
            and (max_age is None or (movies.fsk_age(s.info) is not None and movies.fsk_age(s.info) <= max_age))]


def sort_shows(shows: list[Show], key: str = "title") -> list[Show]:
    by_title = sorted(shows, key=lambda s: s.title.casefold())
    if key == "added":
        return sorted(by_title, key=lambda s: -s.added)
    if key == "year":
        return sorted(by_title, key=lambda s: -(s.info.year or s.year or 0))
    return by_title


def genres(shows: list[Show]) -> list[str]:
    return sorted({g for s in shows for g in s.info.genres}, key=str.casefold)


def years(show: Show) -> str:
    """"2008-2013", "2019-" (still running), "2010"."""
    start = show.info.year or show.year
    if not start:
        return ""
    end = show.info.end_year
    if end and end != start:
        return f"{start}-{end}"
    return f"{start}-" if show.info.tvmaze and not end else str(start)


# --- removing ---------------------------------------------------------------------------------
def show_files(show: Show) -> list[Path]:
    files = []
    for episode in show.episodes:
        files += [episode.path, *related_files(episode)]
    files += [p for p in (show.info_path, show.cover_path) if p.exists()]
    if show.folder is not None:
        files += [p for p in show.folder.glob("*") if p.is_file() and p.stem in ("fanart", "banner", "logo")]
    return list(dict.fromkeys(files))


def removal_size(show: Show) -> int:
    total = 0
    for f in show_files(show):
        try:
            total += f.stat().st_size
        except OSError:
            pass
    return total


def remove(show: Show) -> int:
    """The show's episodes and everything that belongs to them; empty folders go too."""
    freed = removal_size(show)
    folders = set()
    with movies._lock:
        for f in show_files(show):
            folders.add(f.parent)
            try:
                f.unlink(missing_ok=True)
            except OSError:
                pass
    for folder in sorted(folders, key=lambda p: len(p.parts), reverse=True):
        while folder != show.root and show.root in folder.parents:
            try:
                folder.rmdir()
            except OSError:
                break
            folder = folder.parent
    return freed
