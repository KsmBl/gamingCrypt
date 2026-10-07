"""Filters and order are kept across restarts, and one button clears the filters."""

from gamingcrypt.steam.models import SteamGame
from gamingcrypt.ui import view_state
from tests.fakes import FakeService
from tests.test_movies_tab import make_tab as make_movies_tab
from tests.test_movies_tab import root as movies_root  # noqa: F401 - fixture


def test_load_and_save(tmp_path):
    path = tmp_path / "view-state.json"
    assert view_state.load("games", path) == {}
    view_state.save("games", {"genre": "Racing"}, path)
    view_state.save("movies", {"state": "new"}, path)
    assert view_state.load("games", path) == {"genre": "Racing"}
    path.write_text("not json")
    assert view_state.load("games", path) == {}
    view_state.save("games", {"sort": "newest"}, path)  # a broken file is started again
    assert view_state.load("games", path) == {"sort": "newest"}


def games_tab(qtbot):
    from gamingcrypt.ui.games_tab import GamesTab

    service = FakeService(games=[SteamGame(1, "Burnout", installed=True), SteamGame(2, "Celeste", installed=True)])
    tab = GamesTab(service)
    qtbot.addWidget(tab)
    tab.show()
    qtbot.waitUntil(lambda: len(tab.home.installed) == 2)
    return tab


def test_games_filters_after_a_restart_and_clear(qtbot):
    tab = games_tab(qtbot)
    home = tab.home
    assert not home.clear_button.isVisible()
    home.decade_combo.setCurrentIndex(home.decade_combo.findData("1990"))
    home.sort_combo.setCurrentIndex(home.sort_combo.findData("newest"))
    assert home.clear_button.isVisible()
    again = games_tab(qtbot)  # GamingCrypt started again
    home = again.home
    assert home.decade_combo.currentData() == "1990" and home.sort_combo.currentData() == "newest"
    assert home.clear_button.isVisible() and home.result_appids == []  # (no years known)
    home.clear_button.click()
    assert home.decade_combo.currentData() == "" and home.sort_combo.currentData() == "newest"  # order stays
    assert not home.clear_button.isVisible() and sorted(home.result_appids) == [1, 2]
    assert view_state.load("games")["decade"] == ""


def test_a_genre_not_known_yet_stays_chosen(qtbot):
    view_state.save("games", {"genre": "Racing"})
    tab = games_tab(qtbot)
    assert tab.home.genre_combo.currentData() == "Racing"  # (its games' genres come later)


def test_movie_filters_after_a_restart_and_clear(qtbot, movies_root):  # noqa: F811
    tab = make_movies_tab(qtbot, movies_root)
    home = tab.home
    assert not home.clear_button.isVisible()
    home.set_state(next(k for k in home.state_buttons if k != "all"))
    home.genre_combo.setCurrentIndex(home.genre_combo.findData("Horror"))
    state, genre = home.watch_state, "Horror"
    assert home.clear_button.isVisible()
    home = make_movies_tab(qtbot, movies_root).home
    assert home.watch_state == state and home.genre_combo.currentData() == genre
    home.clear_button.click()
    assert home.watch_state == "all" and home.genre_combo.currentData() == "" and not home.clear_button.isVisible()
    assert view_state.load("movies")["state"] == "all"
