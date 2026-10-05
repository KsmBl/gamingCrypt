"""Games tab: "Continue playing" - the game played last, one tap to play on."""

from gamingcrypt.steam.models import SteamGame
from gamingcrypt.ui.games_tab import GamesTab, last_played
from tests.fakes import FakeService


def games():
    return [SteamGame(620, "Portal 2", installed=True, playtime_minutes=1234, last_played=1700000000),
            SteamGame(1145360, "Hades", installed=True, playtime_minutes=60, last_played=1710000000),
            SteamGame(292030, "The Witcher 3", playtime_minutes=6000, last_played=1720000000)]  # not installed


def test_last_played_installed_game():
    assert last_played(games()).name == "Hades"
    assert last_played([SteamGame(1, "New", installed=True)]) is None  # never played


def tab_with(qtbot, game_list):
    service = FakeService(games=game_list)
    tab = GamesTab(service)
    qtbot.addWidget(tab)
    tab.show()
    tab.games.update({g.appid: g for g in game_list})  # the library load does this in the app
    tab.home.set_installed(service.installed_games())
    return tab, service


def test_continue_card_plays_and_opens(qtbot):
    tab, service = tab_with(qtbot, games())
    card = tab.home.continue_card
    assert card.isVisible() and card.title.text() == "Hades"
    assert card.meta.text().startswith("Last played") and "1.0 h played" in card.meta.text()
    card.play_button.click()
    assert service.client.actions == [("play", 1145360)]
    card.details_button.click()
    assert tab.currentWidget().game.appid == 1145360


def test_hidden_while_searching_and_without_played_games(qtbot):
    tab, _ = tab_with(qtbot, games())
    tab.home.search.setText("port")
    assert not tab.home.continue_card.isVisible()
    tab.home.search.setText("")
    assert tab.home.continue_card.isVisible()
    tab2, _ = tab_with(qtbot, [SteamGame(1, "New", installed=True)])
    assert not tab2.home.continue_card.isVisible()
