"""Favorites: ☆ on a game's page, "Favorites" in the Libraries area."""

from gamingcrypt.game_profiles import GameProfiles
from gamingcrypt.ui.games_tab import GamesTab
from gamingcrypt.ui.recent_page import FavoritesPage
from tests.fakes import FakeService


def test_store(tmp_path):
    profiles = GameProfiles(tmp_path / "p.json")
    profiles.set(620, "favorite", True)
    profiles.set(400, "favorite", True)
    profiles.set(620, "power_w", 10)
    assert profiles.favorites() == [400, 620] and profiles.is_favorite(620)
    profiles.set(620, "favorite", None)
    assert profiles.favorites() == [400] and profiles.get(620) == {"power_w": 10}  # other settings stay


def tab_for(qtbot):
    service = FakeService()
    tab = GamesTab(service)
    qtbot.addWidget(tab)
    tab.show()
    tab.games.update({g.appid: g for g in service.games})
    tab.home.set_installed(service.installed_games())
    return tab


def test_star_on_the_game_page_and_library_card(qtbot):
    tab = tab_for(qtbot)
    card = tab.home.favorites_card
    assert card.isVisible() and card.subtitle.text() == "Your starred games"
    tab.open_game(292030)  # not installed - can still be a favorite
    page = tab.currentWidget()
    assert page.favorite_button.text() == "☆ Favorite"
    page.favorite_button.click()
    assert page.favorite_button.text() == "★ Favorite" and card.subtitle.text() == "1 game"
    tab.back()
    tab.open_game(620)
    tab.currentWidget().favorite_button.click()
    assert card.subtitle.text() == "2 games"
    tab.back()
    tab.open_game(292030)
    assert tab.currentWidget().favorite_button.isChecked()  # remembered


def test_favorites_library(qtbot):
    tab = tab_for(qtbot)
    tab.profiles.set(292030, "favorite", True)
    tab.profiles.set(620, "favorite", True)
    tab.home.favorites_card.tapped.emit()
    page = tab.currentWidget()
    assert isinstance(page, FavoritesPage)
    qtbot.waitUntil(lambda: not page.loading)
    assert page.order == [620, 292030]  # by name: Portal 2, The Witcher 3
    page.cards[292030].clicked.emit(292030)
    assert tab.currentWidget().game.appid == 292030


def test_empty_favorites(qtbot):
    tab = tab_for(qtbot)
    tab.open_favorites()
    page = tab.currentWidget()
    qtbot.waitUntil(lambda: not page.loading)
    assert "No favorites yet" in page.status.text()
