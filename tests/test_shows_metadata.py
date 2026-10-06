"""Show info from TVmaze (+ FSK from Wikidata) - against fakes, no network in tests."""

import pytest
import requests

from gamingcrypt.movies import library as movies
from gamingcrypt.shows import library, metadata
from tests.test_movies_metadata import Response, png_bytes

POSTER = "https://static.tvmaze.com/bb.jpg"
STILL = "https://static.tvmaze.com/bb-1x01.jpg"
BB = {"id": 169, "name": "Breaking Bad", "premiered": "2008-01-20", "ended": "2013-09-29", "status": "Ended",
      "genres": ["Drama", "Crime", "Thriller"], "averageRuntime": 60, "summary": "<p><b>Breaking Bad</b> follows Walter.</p>",
      "image": {"original": POSTER}, "externals": {"imdb": "tt0903747"}}
EPISODES = [
    {"id": 1, "season": 1, "number": 1, "name": "Pilot", "airdate": "2008-01-20", "runtime": 58,
     "summary": "<p>A teacher &amp; his student.</p>", "image": {"original": STILL}},
    {"id": 2, "season": 1, "number": 2, "name": "Cat's in the Bag...", "airdate": "2008-01-27", "runtime": 48,
     "summary": "<p>The desert.</p>", "image": None},
    {"id": 3, "season": 1, "number": 3, "name": "...And the Bag's in the River", "airdate": "2008-02-10",
     "runtime": 48, "summary": "", "image": None},
]
CAST = [{"person": {"name": "Bryan Cranston"}, "character": {"name": "Walter White"}},
        {"person": {"name": "Aaron Paul"}, "character": {"name": "Jesse Pinkman"}}]


class Web:
    def __init__(self, shows=None, fsk="Q16"):
        self.shows = shows if shows is not None else [BB, {**BB, "id": 27845, "name": "Breaking Bad: Minisodes",
                                                          "premiered": "2009-02-17"}]
        self.fsk, self.offline, self.calls = fsk, False, []

    def __call__(self, url, params):
        self.calls.append((url, params))
        if self.offline:
            raise requests.ConnectionError("no network")
        if url.endswith("/search/shows"):
            return Response([{"score": 1, "show": s} for s in self.shows if params["q"].lower() in s["name"].lower()
                             or s["name"].lower() in params["q"].lower()])
        if "/shows/" in url:
            assert params == {"embed[]": ["episodes", "cast"]}
            show = next(s for s in self.shows if url.endswith(f"/shows/{s['id']}"))
            return Response({**show, "_embedded": {"episodes": EPISODES, "cast": CAST}})
        if "wikidata.org" in url:
            if params["action"] == "query":
                assert params["srsearch"] == "haswbstatement:P345=tt0903747"
                return Response({"query": {"search": [{"title": "Q1079"}]}})
            if params["props"] == "labels":
                return Response({"entities": {"Q16": {"labels": {"en": {"value": "FSK 16"}}}}})
            claims = {"P1981": [{"mainsnak": {"datavalue": {"value": {"id": self.fsk}}}}]} if self.fsk else {}
            return Response({"entities": {"Q1079": {"id": "Q1079", "claims": claims,
                                                    "sitelinks": {"dewiki": {"title": "Breaking Bad"}}}}})
        if "de.wikipedia.org" in url:
            return Response({"query": {"pages": [{"extract": "Breaking Bad ist eine Fernsehserie."}]}})
        if url in (POSTER, STILL):
            return Response(content=png_bytes())
        return Response(status=404)


@pytest.fixture
def drive(tmp_path):
    root = tmp_path / "Shows"
    for name in ("Breaking.Bad.S01E01.720p.mkv", "breaking bad 1x02.mkv", "Breaking Bad S01E09 - Extra.mkv"):
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes(b"v")
    return root


def test_the_whole_show_from_tvmaze(drive):
    show = library.scan(drive)[0]
    assert metadata.update(show, metadata.ShowLookup(Web()), now=lambda: 1750000000)
    show = library.scan(drive)[0]
    info = show.info
    assert info.title == "Breaking Bad" and info.year == 2008 and info.end_year == 2013 and info.fsk == "FSK 16"
    assert info.genres == ["Drama", "Crime", "Thriller"] and info.plot == "Breaking Bad follows Walter."
    assert info.actors == [("Bryan Cranston", "Walter White"), ("Aaron Paul", "Jesse Pinkman")]
    assert info.tvmaze == "169" and info.wikidata == "Q1079" and info.looked_up == 1750000000
    assert show.cover_path.read_bytes()[:2] == b"\xff\xd8"  # poster, as JPEG
    first, second, ninth = show.episodes
    assert first.name == "Pilot" and first.info.plot == "A teacher & his student." and first.info.aired == "2008-01-20"
    assert first.info.runtime == 58 and first.cover_path.exists() and not second.cover_path.exists()
    assert second.name == "Cat's in the Bag..." and second.info.showtitle == "Breaking Bad"
    assert ninth.name == "Extra" and ninth.info.looked_up  # TVmaze doesn't know it: the name from the file
    assert library.years(show) == "2008-2013" and not metadata.needs_lookup(show, 1750000000)


def test_german_first_takes_the_german_description(drive):
    show = library.scan(drive)[0]
    metadata.update(show, metadata.ShowLookup(Web(), languages=("de", "en")))
    assert library.scan(drive)[0].info.plot == "Breaking Bad ist eine Fernsehserie."


def test_watching_state_stays(drive):
    show = library.scan(drive)[0]
    movies.set_progress(show.episodes[0], 900, 3000)
    movies.set_watched(show.episodes[1], True)
    metadata.update(show, metadata.ShowLookup(Web()))
    show = library.scan(drive)[0]
    assert show.episodes[0].info.position == 900 and show.episodes[1].info.watched
    assert show.episodes[0].name == "Pilot"


def test_new_episodes_get_their_info_later(drive):
    show = library.scan(drive)[0]
    metadata.update(show, metadata.ShowLookup(Web()))
    (drive / "Breaking Bad S01E03.mkv").write_bytes(b"v")
    show = library.scan(drive)[0]
    assert metadata.needs_lookup(show, 0)
    metadata.update(show, metadata.ShowLookup(Web()))
    show = library.scan(drive)[0]
    assert [e.name for e in show.episodes][:3] == ["Pilot", "Cat's in the Bag...", "...And the Bag's in the River"]


def test_not_found_and_offline(drive, tmp_path):
    show = library.scan(drive)[0]
    web = Web(shows=[])
    assert metadata.update(show, metadata.ShowLookup(web), now=lambda: 1750000000)
    show = library.scan(drive)[0]
    assert show.info.looked_up == 1750000000 and not show.info.tvmaze
    assert not metadata.needs_lookup(show, 1750000000 + 86400)
    assert metadata.needs_lookup(show, 1750000000 + 31 * 86400)
    other = tmp_path / "Other"
    (other / "Dark").mkdir(parents=True)
    (other / "Dark" / "Dark S01E01.mkv").write_bytes(b"v")
    dark = library.scan(other)[0]
    offline = Web()
    offline.offline = True
    assert metadata.update(dark, metadata.ShowLookup(offline)) is False
    assert not dark.info_path.exists()


def test_the_year_picks_the_right_show(drive):
    lookup = metadata.ShowLookup(Web(shows=[{**BB, "id": 1, "premiered": "1990-01-01"}, BB]))
    assert lookup.best("Breaking Bad", 2008)["id"] == 169
    assert lookup.best("Breaking Bad", 1990)["id"] == 1


def test_no_fsk_known(drive):
    show = library.scan(drive)[0]
    metadata.update(show, metadata.ShowLookup(Web(fsk=None)))
    assert library.scan(drive)[0].info.fsk == ""


def test_html_summaries():
    assert metadata.plain("<p>A &amp; B<br>C</p><p>D</p>") == "A & B\nC\nD"
    assert metadata.plain(None) == ""


def test_double_episode(tmp_path):
    root = tmp_path / "Shows"
    root.mkdir()
    (root / "Breaking Bad S01E01-02.mkv").write_bytes(b"v")
    show = library.scan(root)[0]
    metadata.update(show, metadata.ShowLookup(Web()))
    episode = library.scan(root)[0].episodes[0]
    assert episode.code == "S01E01-02" and episode.name == "Pilot / Cat's in the Bag..."
    assert episode.info.runtime == 58 + 48
