"""Shows on the drive: episodes recognised by their names, grouped into shows, what comes next."""

from pathlib import Path

import pytest

from gamingcrypt.movies import library as movies
from gamingcrypt.movies.library import MovieInfo
from gamingcrypt.shows import library
from gamingcrypt.shows.library import parse_episode

ROOT = Path("/drive/Shows")


@pytest.mark.parametrize("name, expected", [
    ("Breaking.Bad.S01E02.720p.HDTV.x264-GRP.mkv", ("Breaking Bad", 1, 2, None, "", None)),
    ("Breaking Bad (2008)/Season 01/Breaking Bad S01E03 - And the Bags in the River.mkv",
     ("Breaking Bad", 1, 3, None, "And the Bags in the River", "Breaking Bad (2008)")),
    ("Dark/Staffel 2/Folge 3.mkv", ("Dark", 2, 3, None, "", "Dark")),
    ("Dark/Staffel 2/03 - Ghosts.mkv", ("Dark", 2, 3, None, "Ghosts", "Dark")),
    ("the office 2x05.avi", ("the office", 2, 5, None, "", None)),
    ("Friends/S10E17-18 The Last One.mkv", ("Friends", 10, 17, 18, "The Last One", "Friends")),
    ("Doctor Who/Specials/Doctor Who S00E01.mkv", ("Doctor Who", 0, 1, None, "", "Doctor Who")),
    ("Sherlock/Episode 1.mkv", ("Sherlock", 1, 1, None, "", "Sherlock")),
    ("Show.Name.2019.S01E01.Pilot.1080p.mkv", ("Show Name", 1, 1, None, "Pilot", None)),
    ("Random Movie.mkv", None),  # loose, no episode number: not an episode
])
def test_episode_names(name, expected):
    assert parse_episode(ROOT / name, ROOT) == expected


def make(root: Path, rel: str, size: int = 10) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"v" * size)
    return path


def watched(path: Path, **info) -> None:
    movies.write_info(path.with_suffix(".nfo"), MovieInfo(**info), "episodedetails")


@pytest.fixture
def drive(tmp_path):
    root = tmp_path / "Shows"
    for season in (1, 2):
        for number in (1, 2, 3):
            make(root, f"Breaking Bad (2008)/Season {season}/Breaking Bad S0{season}E0{number}.mkv", 100)
    make(root, "Breaking Bad (2008)/Specials/Breaking Bad S00E01.mkv")
    make(root, "Breaking Bad (2008)/Season 1/Breaking Bad S01E01.de.srt")
    make(root, "Dark.S01E02.mkv")
    make(root, "dark 1x01.mkv")
    make(root, "Notes.txt")
    return root


def test_one_show_per_folder_and_per_name(drive):
    shows = library.scan(drive)
    assert [s.title for s in shows] == ["Breaking Bad", "Dark"]
    bb, dark = shows
    assert bb.folder == drive / "Breaking Bad (2008)" and bb.year == 2008 and bb.key == "folder:Breaking Bad (2008)"
    assert [e.code for e in bb.episodes] == ["S01E01", "S01E02", "S01E03", "S02E01", "S02E02", "S02E03", "S00E01"]
    assert bb.seasons == [1, 2, 0] and len(bb.season(2)) == 3  # specials last
    assert bb.info_path == bb.folder / "tvshow.nfo" and bb.cover_path == bb.folder / "poster.jpg"
    # loose files with differently written names: one show
    assert dark.folder is None and [e.code for e in dark.episodes] == ["S01E01", "S01E02"]
    assert dark.info_path == drive / "Dark.tvshow.nfo" or dark.info_path == drive / "dark.tvshow.nfo"
    episode = bb.episodes[0]
    assert episode.info_path == episode.path.with_suffix(".nfo") and episode.cover_path == episode.path.with_suffix(".jpg")
    assert episode.title == "Breaking Bad - S01E01 - Episode 1" and episode.NFO_KIND == "episodedetails"
    assert movies.is_movie_appid(episode.appid) and len({e.appid for e in bb.episodes}) == 7  # the player's ids


def test_continue_with_what_comes_next(drive):
    bb = library.scan(drive)[0]
    assert library.next_up(bb).code == "S01E01" and library.state(bb) == "new"  # nothing watched
    for e in bb.episodes[:3]:
        watched(e.path, watched=True, playcount=1)
    bb = library.scan(drive)[0]
    assert library.next_up(bb).code == "S02E01" and library.state(bb) == "progress"
    assert bb.unwatched == 3  # specials don't count
    watched(bb.episodes[4].path, position=600, total=2800, last_played=5)  # S02E02 stopped in the middle
    bb = library.scan(drive)[0]
    assert library.next_up(bb).code == "S02E02"
    for e in bb.regular:
        watched(e.path, watched=True, playcount=1)
    bb = library.scan(drive)[0]
    assert library.next_up(bb) is None and library.state(bb) == "watched" and bb.unwatched == 0


def test_the_following_episode(drive):
    bb = library.scan(drive)[0]
    codes = {e.code: e for e in bb.episodes}
    assert library.following(bb, codes["S01E03"]).code == "S02E01"  # on into the next season
    assert library.following(bb, codes["S02E03"]) is None  # not into the specials
    assert library.following(bb, codes["S00E01"]) is None


def test_mark_a_whole_show(drive):
    bb = library.scan(drive)[0]
    library.set_show_watched(bb, True)
    bb = library.scan(drive)[0]
    assert library.state(bb) == "watched" and not bb.episodes[-1].info.watched  # the special isn't touched
    library.set_show_watched(bb, False)
    assert library.state(library.scan(drive)[0]) == "new"


def test_episode_nfo_is_kodis(drive):
    episode = library.scan(drive)[0].episodes[0]
    movies.set_progress(episode, 100, 2800)
    assert episode.info_path.read_text().splitlines()[1] == "<episodedetails>"
    show = library.scan(drive)[0]
    movies.change_info(show, lambda info: setattr(info, "title", "Breaking Bad"))
    assert "<tvshow>" in show.info_path.read_text()


def test_years():
    show = library.Show("X", "k", None, ROOT, MovieInfo(year=2008, end_year=2013))
    assert library.years(show) == "2008-2013"
    show.info = MovieInfo(year=2019, tvmaze="1")
    assert library.years(show) == "2019-"  # still running
    show.info = MovieInfo()
    show.year = 2010
    assert library.years(show) == "2010"


def test_search_filter_sort(drive):
    shows = library.scan(drive)
    movies.change_info(shows[0], lambda i: (setattr(i, "genres", ["Drama"]), setattr(i, "fsk", "FSK 16"),
                                            setattr(i, "actors", [("Bryan Cranston", "Walter")])))
    shows = library.scan(drive)
    assert [s.title for s in library.filter_shows(shows, "cranston")] == ["Breaking Bad"]
    assert [s.title for s in library.filter_shows(shows, genre="Drama")] == ["Breaking Bad"]
    assert [s.title for s in library.filter_shows(shows, max_age=16)] == ["Breaking Bad"]
    assert [s.title for s in library.filter_shows(shows, watch_state="new")] == ["Breaking Bad", "Dark"]
    assert library.genres(shows) == ["Drama"]
    assert [s.title for s in library.sort_shows(shows, "year")] == ["Breaking Bad", "Dark"]


def test_remove_a_show_with_everything(drive):
    bb, dark = library.scan(drive)
    (bb.folder / "poster.jpg").write_bytes(b"p")
    (bb.folder / "tvshow.nfo").write_text("<tvshow/>")
    (bb.episodes[0].path.with_suffix(".jpg")).write_bytes(b"t")
    files = library.show_files(bb)
    assert len(files) == 7 + 4  # the episodes; poster, show info, subtitles, an episode's picture
    size = library_size(files)
    assert library.remove(bb) == size
    assert not bb.folder.exists() and drive.exists()
    assert [e.path.exists() for e in dark.episodes] == [True, True]
    assert (drive / "Notes.txt").exists()
    library.remove(dark)  # loose: only its own files go
    assert sorted(p.name for p in drive.iterdir()) == ["Notes.txt"]


def library_size(files):
    return sum(f.stat().st_size for f in files if f.exists())
