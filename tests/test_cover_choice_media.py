"""Choosing a movie's or show's picture: hold the poster, or Options → Change picture (also
on game pages - the way with the controller)."""

import pytest
import requests

from gamingcrypt import cover_choice
from gamingcrypt.cover_choice import Offline
from tests.fakes import FakeService, cover_color
from tests.test_cover_choice import Response, hold, png
from tests.test_movies_tab import make_tab as make_movies_tab
from tests.test_movies_tab import root as movies_root  # noqa: F401 - fixture
from tests.test_shows_tab import make_tab as make_shows_tab
from tests.test_shows_tab import root as shows_root  # noqa: F401 - fixture


# --- where the pictures come from -------------------------------------------------------------

def wikidata_get(asked=None):
    def get(url, params=None):
        params = params or {}
        if asked is not None:
            asked.append((url, params.get("action"), params.get("titles")))
        if params.get("list") == "search":
            return Response({"query": {"search": [{"title": "Q1"}, {"title": "Q2"}, {"title": "Q3"}]}})
        if params.get("action") == "wbgetentities":
            return Response({"entities": {
                "Q1": {"id": "Q1", "labels": {"en": {"value": "The Matrix"}}, "sitelinks": {
                    "enwiki": {"title": "The_Matrix"}},
                    "claims": {"P577": [{"mainsnak": {"datavalue": {"value": {"time": "+1999-03-31T00:00:00Z"}}}}]}},
                "Q2": {"id": "Q2", "labels": {"en": {"value": "The Matrix Reloaded"}}, "sitelinks": {},
                       "claims": {"P3383": [{"mainsnak": {"datavalue": {"value": "Reloaded poster.jpg"}}}]}},
                "Q3": {"id": "Q3", "labels": {"en": {"value": "Matrix (no picture)"}}, "sitelinks": {}, "claims": {}},
            }})
        if "wikipedia" in url:
            return Response({"query": {"normalized": [{"from": "The_Matrix", "to": "The Matrix"}],
                                       "pages": [{"title": "The Matrix",
                                                  "thumbnail": {"source": "https://upload/matrix.jpg"}}]}})
        return Response(status=404)
    return get


def test_movie_posters_from_wikipedia_and_commons():
    asked = []
    choices = cover_choice.movie_choices("matrix", wikidata_get(asked))
    assert [c.name for c in choices] == ["The Matrix (1999)", "The Matrix Reloaded"]  # none without a picture
    assert choices[0].urls == ("https://upload/matrix.jpg",)
    assert choices[1].urls == ("https://commons.wikimedia.org/wiki/Special:FilePath/Reloaded_poster.jpg?width=600",)
    assert sum(1 for url, _a, _t in asked if "wikipedia" in url) == 1  # every poster in one question
    assert cover_choice.movie_choices(" ", wikidata_get()) == []


def test_movie_search_offline():
    def offline(url, params=None):
        raise requests.ConnectionError("no network")

    with pytest.raises(Offline):
        cover_choice.movie_choices("matrix", offline)


def test_show_posters_from_tvmaze():
    def get(url, params=None):
        assert url.endswith("/search/shows") and params == {"q": "dark"}
        return Response([{"show": {"name": "Dark", "premiered": "2017-12-01",
                                   "image": {"original": "https://tvmaze/dark.jpg", "medium": "https://tvmaze/m.jpg"}}},
                         {"show": {"name": "Dark Matter", "image": None}}])

    choices = cover_choice.show_choices("dark", get)
    assert [(c.name, c.urls) for c in choices] == [("Dark (2017)", ("https://tvmaze/dark.jpg", "https://tvmaze/m.jpg"))]

    def offline(url, params=None):
        raise requests.ConnectionError("no network")

    with pytest.raises(Offline):
        cover_choice.show_choices("dark", offline)


def test_the_default_download_names_itself():
    """Wikimedia turns away requests without a User-Agent."""
    seen = {}

    import gamingcrypt.cover_choice as module

    original = module.requests.get
    try:
        module.requests.get = lambda url, params=None, timeout=None, headers=None: seen.update(headers or {})
        cover_choice._default_get("https://x")
    finally:
        module.requests.get = original
    assert seen["User-Agent"].startswith("GamingCrypt")


# --- movies -----------------------------------------------------------------------------------

@pytest.fixture
def fake_net(monkeypatch):
    monkeypatch.setattr(cover_choice, "movie_choices", lambda q, get=None, languages=(): [
        cover_choice.Choice("Matrix poster", ("https://a",))] if q else [])
    monkeypatch.setattr(cover_choice, "show_choices", lambda q, get=None: [
        cover_choice.Choice("Show poster", ("https://b",))] if q else [])
    monkeypatch.setattr(cover_choice, "_default_get", lambda url, params=None: Response(content=png("#3050e0")))


def test_hold_a_movie_poster(qtbot, movies_root, fake_net):  # noqa: F811
    from gamingcrypt.ui.cover_picker import CoverPicker

    tab = make_movies_tab(qtbot, movies_root)
    card = next(c for c in tab.home.cards.values() if c.movie.title == "The Matrix")
    hold(qtbot, card.cover)
    picker = tab.currentWidget()
    assert isinstance(picker, CoverPicker) and picker.item.key == card.movie.key
    assert picker.search.text() == "The Matrix"
    qtbot.waitUntil(lambda: len(picker.cards) == 1 and picker.cards[0].data is not None)
    picker.cards[0].tapped.emit()
    assert tab.currentWidget() is tab.home
    assert card.movie.cover_path.read_bytes()[:4] == b"\x89PNG"
    card = next(c for c in tab.home.cards.values() if c.movie.title == "The Matrix")
    qtbot.waitUntil(lambda: cover_color(card.cover) == "#3050e0")


def test_movie_options_change_picture_and_drawn(qtbot, movies_root, fake_net):  # noqa: F811
    tab = make_movies_tab(qtbot, movies_root)
    movie = next(m for m in tab.movies if m.title == "Alien")
    tab.open_movie(movie)
    page = tab.currentWidget()
    page.options_button.click()
    page.picture_button.click()
    picker = tab.currentWidget()
    assert picker.item is movie
    picker.drawn_button.click()
    assert tab.currentWidget() is page and movie.cover_path.read_bytes() == cover_choice.DRAWN


def test_holding_a_picture_in_the_picker_opens_no_picker(qtbot, movies_root, fake_net):  # noqa: F811
    tab = make_movies_tab(qtbot, movies_root)
    tab.open_cover_picker(tab.movies[0])
    picker = tab.currentWidget()
    qtbot.waitUntil(lambda: len(picker.cards) == 1 and picker.cards[0].data is not None)
    held = []
    tab.hold.held.connect(held.append)
    hold(qtbot, picker.cards[0].cover)
    assert held == []  # no picker for a picture to choose from - holding it just chooses it
    assert tab.currentWidget() is tab.home


# --- shows ------------------------------------------------------------------------------------

def test_hold_a_show_poster(qtbot, shows_root, fake_net):  # noqa: F811
    tab = make_shows_tab(qtbot, shows_root)
    card = tab.home.cards["folder:Breaking Bad (2008)"]
    hold(qtbot, card.cover)
    picker = tab.currentWidget()
    assert picker.item.key == "folder:Breaking Bad (2008)" and picker.search.text() == "Breaking Bad"
    qtbot.waitUntil(lambda: len(picker.cards) == 1 and picker.cards[0].data is not None)
    picker.cards[0].tapped.emit()
    assert (shows_root / "Breaking Bad (2008)" / "poster.jpg").read_bytes()[:4] == b"\x89PNG"
    qtbot.waitUntil(lambda: cover_color(tab.home.cards["folder:Breaking Bad (2008)"].cover) == "#3050e0")


def test_show_page_options_and_episode_pictures(qtbot, shows_root, fake_net):  # noqa: F811
    tab = make_shows_tab(qtbot, shows_root)
    show = next(s for s in tab.shows if s.title == "Breaking Bad")
    tab.open_show(show)
    page = tab.currentWidget()
    row = next(iter(page.rows.values()))
    hold(qtbot, row.thumb)  # an episode's picture isn't the show's
    assert tab.currentWidget() is page
    page.options_button.click()
    page.picture_button.click()
    assert tab.currentWidget().item is show


# --- games: Options → Change picture ----------------------------------------------------------

def test_game_pages_have_change_picture(qtbot, tmp_path, monkeypatch):
    from gamingcrypt.steam.models import SteamGame
    from gamingcrypt.ui.cover_picker import CoverPicker
    from gamingcrypt.ui.games_tab import GamesTab

    monkeypatch.setattr(cover_choice, "steam_choices", lambda q, get=None, own=None: [])
    service = FakeService(games=[SteamGame(5, "Racer", installed=True)])
    service.cache_dir = tmp_path / "cache"
    t = GamesTab(service)
    qtbot.addWidget(t)
    t.show()
    qtbot.waitUntil(lambda: 5 in t.games)
    t.open_game(5)
    page = t.currentWidget()
    page.options_button.click()
    assert page.picture_button.isVisible()
    page.picture_button.click()
    assert isinstance(t.currentWidget(), CoverPicker) and t.currentWidget().item.appid == 5


def test_emulated_and_windows_pages_have_change_picture():
    import inspect

    from gamingcrypt.ui import emulation_pages, wine_pages

    assert "picture_button" in inspect.getsource(emulation_pages.RomGamePage.__init__)
    assert "picture_button" in inspect.getsource(wine_pages.WindowsGamePage.__init__)
