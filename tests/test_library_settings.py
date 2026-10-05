"""Settings -> Games -> Libraries: which libraries the Games tab shows."""

import copy

from gamingcrypt.config import DEFAULTS
from gamingcrypt.ui.games_tab import LIBRARIES, GamesTab
from gamingcrypt.ui.settings_tab import SettingsTab
from tests.fakes import FakeService


def test_hide_and_show_libraries(qtbot):
    cfg = copy.deepcopy(DEFAULTS)
    saved = []
    games = GamesTab(FakeService(), library_settings=cfg["libraries"])
    settings = SettingsTab(cfg, saved.append)
    qtbot.addWidget(games)
    qtbot.addWidget(settings)
    games.show()
    settings.libraries_changed.connect(games.home.apply_libraries)
    home = games.home
    assert set(settings.library_buttons) == set(LIBRARIES)
    assert all(b.isChecked() and b.text().startswith("✓") for b in settings.library_buttons.values())
    settings.library_buttons["recent"].click()
    assert saved[-1]["libraries"]["hidden"] == ["recent"]
    assert not home.recent_card.isVisible() and home.steam_card.isVisible()
    settings.library_buttons["favorites"].click()
    settings.library_buttons["steam"].click()
    assert not home.sources_heading.isVisible()  # nothing left: no "Libraries" heading
    settings.library_buttons["steam"].click()
    assert home.steam_card.isVisible() and home.sources_heading.isVisible()
    assert settings.library_buttons["steam"].text() == "✓  Steam"
    assert sorted(saved[-1]["libraries"]["hidden"]) == ["favorites", "recent"]


def test_hidden_libraries_stay_hidden_after_a_restart_and_while_searching(qtbot):
    cfg = copy.deepcopy(DEFAULTS)
    cfg["libraries"]["hidden"] = ["steam"]
    games = GamesTab(FakeService(), library_settings=cfg["libraries"])
    qtbot.addWidget(games)
    games.show()
    games.home.set_installed(FakeService().installed_games())
    assert not games.home.steam_card.isVisible() and games.home.favorites_card.isVisible()
    games.home.search.setText("portal")
    assert not games.home.sources.isVisible()
    games.home.search.setText("")
    assert games.home.sources.isVisible() and not games.home.steam_card.isVisible()


def test_main_window_wires_settings_to_the_games_tab(qtbot):
    from gamingcrypt.app import MainWindow, default_pages

    cfg = copy.deepcopy(DEFAULTS)
    pages = {}

    def factory(config):
        made = default_pages(config)
        pages.update(made)
        return made

    window = MainWindow(cfg, lambda c: None, page_factory=factory)
    qtbot.addWidget(window)
    window.show()
    window.show_shell()
    settings = window.shell.pages["Settings"]
    settings.library_buttons["steam"].click()
    assert not pages["Games"].home.steam_card.isVisibleTo(pages["Games"].home)
