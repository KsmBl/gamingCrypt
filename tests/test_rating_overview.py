"""Settings -> Users: how many games a user with an age sees, and the games nobody rated - which
are hidden from them - rated right there ("Rate them")."""

import copy

import pytest

from gamingcrypt import ratings
from gamingcrypt.config import DEFAULTS
from gamingcrypt.system.controls import SystemControls
from gamingcrypt.ui.users_page import RatePage
from tests.test_code_dialogs import rect_in
from tests.test_ratings import emu, tab_for  # noqa: F401 - fixture
from tests.test_users import verify

SCREENS = [(1280, 800), (1280, 720), (1920, 1080), (1366, 768), (1024, 600)]


def config(*records):
    cfg = copy.deepcopy(DEFAULTS)
    cfg["unlock"].update(method="pin", volume="")
    cfg["users"] = [dict(r) for r in records]
    return cfg


MIA = {"id": "mia", "name": "Mia", "method": "pin", "age": 6}
TOM = {"id": "tom", "name": "Tom", "method": "pin"}  # (no age: sees everything)


@pytest.fixture
def games(qtbot, emu):  # noqa: F811
    return tab_for(qtbot, emu, None, rate_games=True)  # the admin's: everything there is


@pytest.fixture
def settings(qtbot, games):
    from gamingcrypt.ui.settings_tab import SettingsTab

    tab = SettingsTab(config(MIA, TOM), lambda c: None, system=SystemControls(), admin_check=verify)
    qtbot.addWidget(tab)
    tab.resize(1280, 800)
    tab.show()
    tab.users_section.games_fn = lambda: games
    tab.users_section.update_counts()
    tab.show_sub_tab("Security")
    return tab


def by_name(games_tab, name):
    return next(g for g in games_tab.home.all_games() if g.name == name)


def test_what_a_user_of_an_age_sees(games):
    everything = games.home.all_games()
    assert len(everything) == 8  # 4 Steam + 4 emulated
    seen, unrated = ratings.overview(everything, games, 6)
    assert seen == 2  # Kids Game (0), Super Mario World (6)
    assert sorted(g.name for g in unrated) == ["Some Homebrew", "Unrated Game"]
    assert ratings.overview(everything, games, 18)[0] == 6


def test_the_line_under_a_user_with_an_age(settings):
    rows = settings.users_section.rows
    assert rows["mia"]["sees"].text() == "Sees 2 of 8 games  ·  2 not rated - hidden from Mia"
    assert rows["mia"]["rate"].isVisibleTo(settings)
    assert "sees" not in rows["tom"] and "sees" not in rows["admin"]  # (nothing hidden from them)


def test_rating_them(qtbot, settings, games):
    section = settings.users_section
    section.rows["mia"]["rate"].click()
    page = settings.currentWidget()
    assert isinstance(page, RatePage) and len(page.combos) == 2
    homebrew = by_name(games, "Some Homebrew")
    combo = page.combos[homebrew.appid]
    combo.setCurrentIndex(combo.findData(0))
    assert ratings.age_of(homebrew, games) == 0  # (kept right away)
    page.done_button.click()
    assert settings.currentWidget() is settings.overview
    assert "1 of 2 games rated" in settings.status.text()
    assert section.rows["mia"]["sees"].text() == "Sees 3 of 8 games  ·  1 not rated - hidden from Mia"
    section.rows["mia"]["rate"].click()
    page = settings.currentWidget()
    unrated = by_name(games, "Unrated Game")
    page.combos[unrated.appid].setCurrentIndex(page.combos[unrated.appid].findData(18))
    page.done_button.click()
    assert section.rows["mia"]["sees"].text() == "Sees 3 of 8 games"
    assert not section.rows["mia"]["rate"].isVisibleTo(settings)  # nothing left to rate


def test_back_leaves_the_page(settings):
    settings.users_section.rows["mia"]["rate"].click()
    assert isinstance(settings.currentWidget(), RatePage)
    assert settings.gamepad_back()
    assert settings.currentWidget() is settings.overview


def test_ratings_given_on_a_games_page_count_when_users_is_shown_again(qtbot, settings, games):
    unrated = by_name(games, "Unrated Game")
    games.rating_profiles.set(unrated.appid, ratings.MANUAL, "6")  # (rated on its own page)
    settings.hide()
    settings.show()
    assert settings.users_section.rows["mia"]["sees"].text().startswith("Sees 3 of 8 games  ·  1 not rated")


def test_without_the_games_no_line(qtbot):
    from gamingcrypt.ui.settings_tab import SettingsTab

    tab = SettingsTab(config(MIA), lambda c: None, system=SystemControls(), admin_check=verify)
    qtbot.addWidget(tab)
    tab.show()
    tab.show_sub_tab("Security")
    assert not tab.users_section.rows["mia"]["sees_row"].isVisibleTo(tab)


@pytest.mark.parametrize("w,h", SCREENS)
def test_the_page_fits(qtbot, settings, w, h):
    settings.resize(w, h)
    settings.users_section.rows["mia"]["rate"].click()
    page = settings.currentWidget()
    qtbot.waitUntil(lambda: page.isVisible())
    qtbot.wait(20)
    for part in (page.done_button, *page.combos.values()):
        assert settings.rect().contains(rect_in(part, settings)), f"{part} is off the {w}x{h} screen"


def test_the_app_wires_the_games_in(qtbot):
    from gamingcrypt.app import MainWindow
    from gamingcrypt.ui.games_tab import GamesTab
    from gamingcrypt.ui.settings_tab import SettingsTab
    from tests.fakes import FakeService

    def factory(cfg):
        return {"Games": GamesTab(FakeService(), library_settings=cfg["libraries"]),
                "Settings": SettingsTab(cfg, lambda c: None, system=SystemControls())}

    w = MainWindow(config(), lambda c: None, page_factory=factory)
    qtbot.addWidget(w)
    w.windowed = True
    w.show()
    w.show_shell()
    settings, games = w.shell.pages["Settings"], w.shell.pages["Games"]
    assert settings.users_section.games_fn() is games
    assert not games.rate_games  # (nobody has an age)
    w.config["users"] = [dict(MIA)]
    settings.users_section.changed.emit()  # (Mia was given an age)
    assert games.rate_games
