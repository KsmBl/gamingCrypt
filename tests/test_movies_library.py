"""Movies on the drive: names, the .nfo next to them, watching state, removing, searching."""

from pathlib import Path

import pytest

from gamingcrypt.emulation.library import EMU_APPID_BASE
from gamingcrypt.movies import library
from gamingcrypt.movies.library import MovieInfo, parse_name


@pytest.mark.parametrize("name, expected", [
    ("The.Matrix.1999.1080p.BluRay.x264-GRP.mkv", ("The Matrix", 1999)),
    ("Blade Runner 2049 (2017).mkv", ("Blade Runner 2049", 2017)),
    ("Blade Runner 2049.mkv", ("Blade Runner 2049", None)),  # 2049 is no year (yet)
    ("2012 (2009).mp4", ("2012", 2009)),
    ("1917.mkv", ("1917", None)),
    ("Der Schuh des Manitu (2001) [German].avi", ("Der Schuh des Manitu", 2001)),
    ("Matrix_Reloaded_2003_German_DL.mkv", ("Matrix Reloaded", 2003)),
    ("Alien - Director's Cut (1979).mkv", ("Alien", 1979)),
    ("Blade.Runner.The.Final.Cut.1982.mkv", ("Blade Runner", 1982)),
    ("Ocean's Eleven.mp4", ("Ocean's Eleven", None)),
])
def test_names(name, expected):
    assert parse_name(name) == expected


def make(root: Path, rel: str, size: int = 10) -> Path:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"v" * size)
    return path


def test_scan_finds_videos_in_sub_folders(tmp_path):
    root = tmp_path / "Movies"
    make(root, "The Matrix (1999).mkv", 100)
    make(root, "Alien (1979)/Alien (1979).mp4")
    make(root, "Alien (1979)/Alien-sample.mp4")  # a sample clip
    make(root, "Alien (1979)/Alien (1979).de.srt")
    make(root, ".hidden/Secret.mkv")
    make(root, ".Upload.mkv.part")
    make(root, "notes.txt")
    movies = library.scan(root)
    assert [m.key for m in movies] == ["Alien (1979)/Alien (1979).mp4", "The Matrix (1999).mkv"]
    matrix = movies[1]
    assert matrix.title == "The Matrix" and matrix.year == 1999 and matrix.size == 100
    assert matrix.cover_path == root / "The Matrix (1999).jpg" and matrix.info_path == root / "The Matrix (1999).nfo"
    assert library.scan(tmp_path / "missing") == []


def test_movie_ids_are_stable_and_their_own(tmp_path):
    make(tmp_path, "A.mkv")
    make(tmp_path, "B.mkv")
    a, b = library.scan(tmp_path)
    assert a.appid != b.appid and a.appid == library.scan(tmp_path)[0].appid
    assert library.is_movie_appid(a.appid) and library.MOVIE_APPID_BASE <= a.appid < EMU_APPID_BASE
    assert not library.is_movie_appid(EMU_APPID_BASE + 5) and not library.is_movie_appid(730)
    assert not library.is_movie_appid(None)


FULL = MovieInfo(title="The Matrix", year=1999, plot="Neo wakes up.", runtime=136, fsk="FSK 16",
                 genres=["Action", "Science fiction"], directors=["Lana Wachowski"],
                 actors=[("Keanu Reeves", "Neo"), ("Joe Pantoliano", "")], wikidata="Q83495", looked_up=1700000000,
                 watched=True, playcount=2, position=600.0, total=8160.0, last_played=1750000000)


def test_nfo_round_trip_in_kodis_format(tmp_path):
    path = tmp_path / "The Matrix.nfo"
    library.write_info(path, FULL)
    text = path.read_text()
    assert text.startswith('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<movie>')
    for tag in ("<title>The Matrix</title>", "<mpaa>FSK 16</mpaa>", "<runtime>136</runtime>",
                '<uniqueid type="wikidata" default="true">Q83495</uniqueid>', "<playcount>2</playcount>",
                "<watched>true</watched>", "<position>600.0</position>", "<name>Keanu Reeves</name>"):
        assert tag in text
    assert library.read_info(path) == FULL
    assert not list(tmp_path.glob(".*.part"))


def test_broken_or_missing_nfo_is_empty(tmp_path):
    (tmp_path / "x.nfo").write_text("<movie><title>oops")
    assert library.read_info(tmp_path / "x.nfo") == MovieInfo()
    assert library.read_info(tmp_path / "missing.nfo") == MovieInfo()


@pytest.fixture
def matrix(tmp_path):
    make(tmp_path, "The Matrix (1999).mkv")
    return library.scan(tmp_path)[0]


def test_where_it_was_stopped_is_kept(matrix):
    library.set_progress(matrix, 3723.4, 8160)
    info = library.read_info(matrix.info_path)
    assert info.position == pytest.approx(3723.4) and info.total == 8160 and info.title == "The Matrix"
    assert info.resume_at == pytest.approx(3723.4) and library.state(info) == "progress"
    info = library.finish_watching(matrix, now=1750000000)
    assert info.resume_at == pytest.approx(3723.4) and not info.watched and info.last_played == 1750000000
    assert matrix.info == info


def test_watched_to_the_end(matrix):
    library.set_progress(matrix, 7400, 8160)  # past 90 %: the credits
    info = library.finish_watching(matrix)
    assert info.watched and info.playcount == 1 and info.position == 0 and library.state(info) == "watched"
    library.set_progress(matrix, 8100, 8160)  # watched again
    assert library.finish_watching(matrix).playcount == 2


def test_stopped_right_away_starts_from_the_beginning(matrix):
    library.set_progress(matrix, 30, 8160)
    info = library.finish_watching(matrix)
    assert info.position == 0 and info.resume_at == 0 and library.state(info) == "new"


def test_mark_watched_and_unwatched(matrix):
    library.set_progress(matrix, 3000, 8160)
    info = library.set_watched(matrix, True)
    assert info.watched and info.playcount == 1 and info.resume_at == 0
    info = library.set_watched(matrix, False)
    assert not info.watched and info.playcount == 0


def test_new_info_keeps_the_watching_state(matrix):
    library.set_progress(matrix, 3000, 8160)
    library.set_watched(matrix, True)
    library.set_progress(matrix, 3000, 8160)
    info = library.set_metadata(matrix, MovieInfo(title="Matrix", year=1999, fsk="FSK 16", watched=False))
    assert info.title == "Matrix" and info.fsk == "FSK 16" and info.watched and info.position == 3000


def test_remove_takes_everything_that_belongs_to_it(tmp_path):
    root = tmp_path / "Movies"
    own = make(root, "Alien (1979)/Alien (1979).mkv", 1000)
    for name in ("Alien (1979).jpg", "Alien (1979).nfo", "Alien (1979).de.srt", "Alien (1979).en.forced.srt",
                 "Alien (1979)-poster.jpg"):
        make(root, f"Alien (1979)/{name}", 10)
    alien = make(root, "Alien.mkv", 500)
    keep = [make(root, n) for n in ("Alien.Resurrection.mkv", "Alien.Resurrection.srt", "Alien.Resurrection.jpg",
                                    "Alien 2.jpg", "Alien.nfo.txt")]
    make(root, "Alien.srt")
    make(root, "Alien.jpg")
    movies = {m.key: m for m in library.scan(root)}
    first = movies["Alien (1979)/Alien (1979).mkv"]
    assert sorted(f.name for f in library.related_files(first)) == [
        "Alien (1979)-poster.jpg", "Alien (1979).de.srt", "Alien (1979).en.forced.srt", "Alien (1979).jpg",
        "Alien (1979).nfo"]
    assert library.removal_size(first) == 1050
    assert library.remove(first, root) == 1050
    assert not own.parent.exists() and root.exists()  # its own folder went, the Movies folder stays
    assert library.remove(movies["Alien.mkv"], root) == 520
    assert not alien.exists() and not (root / "Alien.srt").exists() and not (root / "Alien.jpg").exists()
    assert all(f.exists() for f in keep)


def _movie(root, name, **info):
    path = make(root, name)
    library.write_info(path.with_suffix(".nfo"), MovieInfo(**info))
    return path


@pytest.fixture
def shelf(tmp_path):
    import os

    _movie(tmp_path, "The Matrix (1999).mkv", title="The Matrix", year=1999, runtime=136, fsk="FSK 16",
           genres=["Action"], actors=[("Keanu Reeves", "Neo")], watched=True, playcount=1)
    _movie(tmp_path, "Finding Nemo.mkv", title="Finding Nemo", year=2003, runtime=100, fsk="FSK 0",
           genres=["Family", "Comedy"], actors=[("Ellen DeGeneres", "Dory")], position=1200, total=6000)
    _movie(tmp_path, "Alien.mkv", title="Alien", year=1979, runtime=117, fsk="FSK 16", genres=["Horror"],
           directors=["Ridley Scott"])
    make(tmp_path, "Home Video.mp4")  # nothing known
    for age, name in enumerate(["Alien.mkv", "The Matrix (1999).mkv", "Finding Nemo.mkv", "Home Video.mp4"]):
        os.utime(tmp_path / name, (1700000000 + age, 1700000000 + age))
    return library.scan(tmp_path)


def titles(movies):
    return [m.title for m in movies]


def test_search_by_title_actor_and_director(shelf):
    assert titles(library.filter_movies(shelf, "matrix")) == ["The Matrix"]
    assert titles(library.filter_movies(shelf, "keanu")) == ["The Matrix"]
    assert titles(library.filter_movies(shelf, "ridley scott")) == ["Alien"]
    assert titles(library.filter_movies(shelf, "home")) == ["Home Video"]
    assert library.filter_movies(shelf, "nothing like it") == []


def test_filters(shelf):
    assert titles(library.filter_movies(shelf, watch_state="watched")) == ["The Matrix"]
    assert titles(library.filter_movies(shelf, watch_state="progress")) == ["Finding Nemo"]
    assert sorted(titles(library.filter_movies(shelf, watch_state="new"))) == ["Alien", "Home Video"]
    assert titles(library.filter_movies(shelf, genre="Comedy")) == ["Finding Nemo"]
    assert titles(library.filter_movies(shelf, max_age=12)) == ["Finding Nemo"]  # unknown ratings are left out
    assert sorted(titles(library.filter_movies(shelf, max_age=16))) == ["Alien", "Finding Nemo", "The Matrix"]
    assert library.genres(shelf) == ["Action", "Comedy", "Family", "Horror"]


def test_sorting(shelf):
    assert titles(library.sort_movies(shelf, "title")) == ["Alien", "Finding Nemo", "Home Video", "The Matrix"]
    assert titles(library.sort_movies(shelf, "added")) == ["Home Video", "Finding Nemo", "The Matrix", "Alien"]
    assert titles(library.sort_movies(shelf, "year")) == ["Finding Nemo", "The Matrix", "Alien", "Home Video"]
    assert titles(library.sort_movies(shelf, "length")) == ["Finding Nemo", "Alien", "The Matrix", "Home Video"]


def test_formats():
    assert library.format_length(136) == "2 h 16 min" and library.format_length(45) == "45 min"
    assert library.format_length(0) == ""
    assert library.format_time(3723.9) == "1:02:03"
    assert library.fsk_age(MovieInfo(fsk="FSK 12")) == 12 and library.fsk_age(MovieInfo()) is None
    assert MovieInfo(total=6000).minutes == 100 and MovieInfo(runtime=90, total=6000).minutes == 90
