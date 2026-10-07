"""Changing a picture is easy to find: Y on the controller, the hint for it, and the note
beside Options → Change picture that holding works too."""

import pytest

from gamingcrypt import cover_choice
from gamingcrypt.input import evdev as e
from gamingcrypt.steam.models import SteamGame
from gamingcrypt.ui import navigator as nav_mod
from gamingcrypt.ui.cover_picker import CoverPicker
from gamingcrypt.ui.hint_bar import hints_for
from gamingcrypt.ui.navigator import GamepadNavigator
from tests.fakes import FakeService
from tests.test_movies_tab import make_tab as make_movies_tab
from tests.test_movies_tab import root as movies_root  # noqa: F401 - fixture
from tests.test_shows_tab import root as shows_root  # noqa: F401 - fixture


@pytest.fixture(autouse=True)
def unpaused():
    nav_mod.set_paused(False)


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(cover_choice, "steam_choices", lambda q, get=None, own=None: [])
    monkeypatch.setattr(cover_choice, "movie_choices", lambda q, get=None, languages=(): [])


def press(nav, code):
    nav.on_event(e.EV_KEY, code, 1)
    nav.on_event(e.EV_KEY, code, 0)


def games_tab(qtbot, tmp_path):
    from gamingcrypt.ui.games_tab import GamesTab

    service = FakeService(games=[SteamGame(5, "Racer", installed=True)])
    service.cache_dir = tmp_path / "cache"
    tab = GamesTab(service)
    qtbot.addWidget(tab)
    tab.resize(1280, 800)
    tab.show()
    qtbot.waitUntil(lambda: 5 in tab.home.cards)
    tab.games[5] = service.games[0]
    return tab


def test_y_on_a_game_card_or_page(qtbot, tmp_path):
    tab = games_tab(qtbot, tmp_path)
    nav = GamepadNavigator(tab)
    card = tab.home.cards[5]
    nav.focus(card)
    assert "Ⓨ  Picture" in hints_for(card)
    press(nav, e.BTN_NORTH)
    picker = tab.currentWidget()
    assert isinstance(picker, CoverPicker) and picker.item.appid == 5
    assert "Ⓨ" not in hints_for(picker.search)  # nothing more to pick a picture for in there
    press(nav, e.BTN_NORTH)
    assert tab.currentWidget() is picker  # Y in the picker opens no second one
    tab.back()
    tab.open_game(5)
    page = tab.currentWidget()
    nav.focus(page.main_button)
    press(nav, e.BTN_NORTH)
    assert isinstance(tab.currentWidget(), CoverPicker)


def test_y_elsewhere_does_nothing(qtbot, tmp_path):
    tab = games_tab(qtbot, tmp_path)
    nav = GamepadNavigator(tab)
    nav.focus(tab.home.search)
    assert "Ⓨ" not in hints_for(tab.home.search)
    press(nav, e.BTN_NORTH)
    assert tab.currentWidget() is tab.home


def test_y_on_a_movie(qtbot, movies_root):  # noqa: F811
    tab = make_movies_tab(qtbot, movies_root)
    nav = GamepadNavigator(tab)
    card = next(iter(tab.home.cards.values()))
    nav.focus(card)
    assert "Ⓨ  Picture" in hints_for(card)
    press(nav, e.BTN_NORTH)
    assert isinstance(tab.currentWidget(), CoverPicker) and tab.currentWidget().item.key == card.movie.key


def test_options_say_that_holding_works_too(qtbot, tmp_path):
    from PySide6.QtWidgets import QLabel

    tab = games_tab(qtbot, tmp_path)
    tab.open_game(5)
    page = tab.currentWidget()
    row = page.picture_button.parentWidget()
    notes = [label.text() for label in row.findChildren(QLabel)]
    assert notes == ["or hold any picture · Ⓨ on the controller"]


# --- what A and X do on each kind of card ----------------------------------------------------------

def test_each_card_says_what_it_does(qtbot, tmp_path, movies_root):  # noqa: F811
    tab = games_tab(qtbot, tmp_path)
    assert hints_for(tab.home.cards[5]).startswith("Ⓐ  Open game     Ⓧ  Favorite")
    movies = make_movies_tab(qtbot, movies_root)
    assert hints_for(next(iter(movies.home.cards.values()))).startswith("Ⓐ  Open movie     Ⓧ  Watched")


def test_x_puts_a_game_in_favorites_from_its_card_and_page(qtbot, tmp_path):
    tab = games_tab(qtbot, tmp_path)
    shown = []
    tab.window().notify = lambda text, icon="": shown.append(text)
    nav = GamepadNavigator(tab)
    nav.focus(tab.home.cards[5])
    press(nav, e.BTN_WEST)
    assert tab.profiles.is_favorite(5) and shown == ["Racer: added to Favorites"]
    assert tab.home.favorites_card.subtitle.text().startswith("1")
    tab.open_game(5)
    page = tab.currentWidget()
    nav.focus(page.main_button)
    press(nav, e.BTN_WEST)
    assert not tab.profiles.is_favorite(5) and not page.favorite_button.isChecked()  # the page shows it
    assert shown[-1] == "Racer: removed from Favorites"


def test_x_marks_a_movie_watched(qtbot, movies_root):  # noqa: F811
    tab = make_movies_tab(qtbot, movies_root)
    nav = GamepadNavigator(tab)
    card = next(c for c in tab.home.cards.values() if c.movie.title == "The Matrix")
    assert not card.movie.info.watched
    nav.focus(card)
    press(nav, e.BTN_WEST)
    qtbot.waitUntil(lambda: next(m for m in tab.movies if m.title == "The Matrix").info.watched)


def test_x_on_an_episode_and_a_show(qtbot, shows_root):  # noqa: F811
    from tests.test_shows_tab import make_tab as make_shows_tab

    tab = make_shows_tab(qtbot, shows_root)
    nav = GamepadNavigator(tab)
    dark = next(c for c in tab.home.cards.values() if c.movie.title == "Dark")
    assert hints_for(dark).startswith("Ⓐ  Open show     Ⓧ  Watched")
    nav.focus(dark)
    press(nav, e.BTN_WEST)  # all watched before: now none
    qtbot.waitUntil(lambda: next(s for s in tab.shows if s.title == "Dark").unwatched == 2)
    show = next(s for s in tab.shows if s.title == "Breaking Bad")
    tab.open_show(show)
    page = tab.currentWidget()
    row = next(r for r in page.rows.values() if not r.episode.info.watched)
    assert hints_for(row).startswith("Ⓐ  Play     Ⓧ  Watched")
    key = row.episode.key
    nav.focus(row)
    press(nav, e.BTN_WEST)
    qtbot.waitUntil(lambda: any(ep.key == key and ep.info.watched
                                for s in tab.shows for ep in s.episodes))
