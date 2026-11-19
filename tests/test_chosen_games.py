"""Instead of an age, a user can see only the games the admin chose for them ("Chosen games" in
Settings -> Users)."""

import copy

import pytest

from gamingcrypt import ratings, users
from gamingcrypt.ui.users_page import PICKED, ChoosePage
from tests.test_code_dialogs import rect_in
from tests.test_rating_overview import MIA, SCREENS, by_name, config, games, settings  # noqa: F401 - fixtures
from tests.test_ratings import emu, names  # noqa: F401 - fixture

LEA = {"id": "lea", "name": "Lea", "method": "pin", "picked": True}


def picked_user(user_id="lea"):
    return users.User(user_id, "Lea", "pin", picked=True)


def tab_of(qtbot, emu, who):  # noqa: F811
    """As tests.test_ratings.tab_for - without waiting for games: there may be none to see."""
    from gamingcrypt.ui.games_tab import GamesTab
    from tests.fakes import FakeService
    from tests.test_ratings import AGES, STEAM

    service = FakeService(games=copy.deepcopy(STEAM), metadata=copy.deepcopy(AGES))
    service.fetched = list(AGES)
    tab = GamesTab(service, emulation_root=str(emu.root), user=who)
    loaded = []
    real = tab._installed_loaded
    tab._installed_loaded = lambda found: loaded.append(1) or real(found)
    tab.rom_facts.now = lambda: 2000
    qtbot.addWidget(tab)
    tab.show()
    qtbot.waitUntil(lambda: bool(tab._all_roms))
    tab.reload_installed()
    qtbot.waitUntil(lambda: bool(loaded))
    return tab


# --- the user ---------------------------------------------------------------------------------

def test_chosen_games_or_an_age():
    cfg = config(dict(MIA))
    users.set_picked(cfg, "mia")
    mia = users.all_users(cfg)[1]
    assert mia.picked and mia.age is None
    users.set_age(cfg, "mia", 12)
    mia = users.all_users(cfg)[1]
    assert not mia.picked and mia.age == 12  # (one or the other)
    with pytest.raises(users.UserError):
        users.set_picked(cfg, users.ADMIN)


def test_kept_beside_the_container_without_the_games():
    from gamingcrypt.unlock import sidecar

    assert "picked" in sidecar.USER_FIELDS
    cfg = config(dict(LEA))
    assert users.all_users(cfg)[1].picked
    assert "users" not in str(cfg["users"][0].keys() - {"id", "name", "method", "picked"})  # (no game in it)


# --- what they see ----------------------------------------------------------------------------

def test_they_see_only_the_chosen_games(qtbot, emu, games):  # noqa: F811
    ratings.pick(by_name(games, "Adult Game"), games, "lea", True)  # (no age limit with chosen games)
    ratings.pick(by_name(games, "Some Homebrew"), games, "lea", True)  # (not rated: shown all the same)
    lea = tab_of(qtbot, emu, picked_user())
    assert names(lea.home.all_games()) == ["Adult Game", "Some Homebrew"]
    assert names(lea.service.load_library()) == ["Adult Game"]
    assert lea.service.unrated == []  # (nothing to look up ratings for)
    other = tab_of(qtbot, emu, picked_user("tom"))
    assert other.home.all_games() == []  # chosen for Lea, not for Tom


def test_choosing_for_one_keeps_the_others(games):
    kids = by_name(games, "Kids Game")
    ratings.pick(kids, games, "lea", True)
    ratings.pick(kids, games, "tom", True)
    ratings.pick(kids, games, "lea", False)
    assert ratings.picked_for(kids, games) == ["tom"]
    ratings.pick(kids, games, "tom", False)
    assert games.rating_profiles.get(kids.appid) == {}  # (nothing left behind)


def test_the_store_too(qtbot, emu, games):  # noqa: F811
    lea = tab_of(qtbot, emu, picked_user())
    assert lea.service.search_store("Game") == []  # (searching shows no other game either)


# --- Settings -> Users ------------------------------------------------------------------------

def test_choosing_it_for_a_user(qtbot, settings, games):
    section = settings.users_section
    combo = section.rows["mia"]["age"]
    assert combo.itemText(combo.count() - 1) == "Chosen games"
    combo.setCurrentIndex(combo.findData(PICKED))
    assert users.all_users(settings.config)[1].picked
    assert "only the games you choose" in settings.status.text()
    rows = section.rows["mia"]
    assert rows["age"].currentData() == PICKED
    assert rows["sees"].text() == "Sees 0 of 8 games - the ones you chose"
    assert rows["rate"].text() == "Choose games" and rows["rate"].isVisibleTo(settings)


def test_the_choose_page(qtbot, settings, games):
    section = settings.users_section
    section.rows["mia"]["age"].setCurrentIndex(section.rows["mia"]["age"].findData(PICKED))
    section.rows["mia"]["rate"].click()
    page = settings.currentWidget()
    assert isinstance(page, ChoosePage) and len(page.buttons) == 8
    kids, homebrew = by_name(games, "Kids Game"), by_name(games, "Some Homebrew")
    page.buttons[kids.appid].click()
    page.buttons[homebrew.appid].click()
    assert page.buttons[kids.appid].text() == "✓  Kids Game"
    assert ratings.picked_for(kids, games) == ["mia"]  # (kept right away)
    page.done_button.click()
    assert settings.currentWidget() is settings.overview and "Mia sees 2 of 8 games" in settings.status.text()
    assert section.rows["mia"]["sees"].text() == "Sees 2 of 8 games - the ones you chose"
    section.rows["mia"]["rate"].click()
    page = settings.currentWidget()
    assert page.buttons[kids.appid].isChecked()  # (as chosen before)
    page.all_button.click()
    assert page.chosen() == 8 and all(ratings.picked_for(g, games) == ["mia"] for g in games.home.all_games())
    page.none_button.click()
    assert page.chosen() == 0 and ratings.picked_for(kids, games) == []
    assert settings.gamepad_back() and settings.currentWidget() is settings.overview


def test_back_to_an_age(qtbot, settings):
    combo = lambda: settings.users_section.rows["mia"]["age"]  # noqa: E731 - (built anew on each change)
    combo().setCurrentIndex(combo().findData(PICKED))
    combo().setCurrentIndex(combo().findData(12))
    mia = users.all_users(settings.config)[1]
    assert mia.age == 12 and not mia.picked
    assert settings.users_section.rows["mia"]["rate"].text() == "Rate them"


@pytest.mark.parametrize("w,h", SCREENS)
def test_the_page_fits(qtbot, settings, w, h):
    settings.resize(w, h)
    combo = settings.users_section.rows["mia"]["age"]
    combo.setCurrentIndex(combo.findData(PICKED))
    settings.users_section.rows["mia"]["rate"].click()
    page = settings.currentWidget()
    qtbot.waitUntil(page.isVisible)
    qtbot.wait(20)
    for part in (page.all_button, page.none_button, page.done_button, next(iter(page.buttons.values()))):
        assert settings.rect().contains(rect_in(part, settings)), f"{part} is off the {w}x{h} screen"


def test_with_copy_of_config_untouched():
    """(config() hands out copies: tests don't share a user.)"""
    first = config(dict(LEA))
    second = copy.deepcopy(first)
    users.set_age(first, "lea", 6)
    assert users.all_users(second)[1].picked
