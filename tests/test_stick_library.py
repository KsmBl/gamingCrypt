"""A library card for every USB stick / SD card ("GAMES · 2 games") with a page of its games, and
"On a USB stick / SD card" in the platform filter."""

import pytest

from gamingcrypt import game_facts
from gamingcrypt.ui.games_tab import STICK_CHOICE
from tests.test_code_dialogs import rect_in
from tests.test_remembered_games import config, drive, make_tab, names, stick  # noqa: F401 - fixtures

SCREENS = [(1280, 800), (1280, 720), (1920, 1080), (1366, 768), (1024, 600)]


def shown_names(tab) -> list[str]:
    return sorted(c.game.name for c in tab.home.grid.widgets()
                  if hasattr(c.game, "removable") and c.isVisibleTo(tab.home.grid_widget))


@pytest.mark.parametrize("w,h", SCREENS)
def test_a_card_for_the_stick_and_its_page(qtbot, drive, config, stick, w, h):  # noqa: F811
    from gamingcrypt.ui.recent_page import StickPage

    tab = make_tab(qtbot, drive, config)
    tab.resize(w, h)
    tab.set_drives([stick])
    qtbot.waitUntil(lambda: len(tab.home.stick_cards) == 1 and "Celeste" in names(tab))
    qtbot.waitUntil(lambda: next(iter(tab.home.stick_cards.values())).subtitle.text() == "2 games")
    card = tab.home.stick_cards["fs:1234-abcd"]
    assert card.title.text() == "STICK" and card.isVisibleTo(tab)
    assert card in tab.home.sources_row.widgets() and card.icon.pixmap() is not None
    order = tab.home.sources_row.widgets()
    assert order.index(card) == len(order) - 2  # the sticks: last, before "Add ROMs"
    card.tapped.emit()
    page = tab.currentWidget()
    assert isinstance(page, StickPage) and page.title_label.text() == "STICK"
    qtbot.waitUntil(lambda: len(page.cards) == 2)
    assert sorted(c.game.name for c in page.cards.values()) == ["Celeste", "Earthbound"]
    for c in page.cards.values():
        assert c.cover.badge == "usb"
        where = rect_in(c, tab)
        assert where.right() <= tab.width() and where.left() >= 0, f"a card off the {w}x{h} page"


def test_taken_out_it_says_not_in_and_its_page_greys(qtbot, drive, config, stick):  # noqa: F811
    from gamingcrypt.ui.recent_page import StickPage

    tab = make_tab(qtbot, drive, config)
    tab.set_drives([stick])
    qtbot.waitUntil(lambda: "Celeste" in names(tab))
    qtbot.wait(50)
    tab.set_drives([])
    qtbot.waitUntil(lambda: names(tab).get("Celeste") == "STICK")
    qtbot.waitUntil(lambda: tab.home.stick_cards.get("fs:1234-abcd") is not None
                    and tab.home.stick_cards["fs:1234-abcd"].subtitle.text() == "2 games · not in")
    tab.open_stick("fs:1234-abcd")
    page = tab.currentWidget()
    assert isinstance(page, StickPage) and page.title_label.text() == "STICK  ·  not in"
    qtbot.waitUntil(lambda: len(page.cards) == 2)
    assert all(c.property("away") for c in page.cards.values())
    config["sticks"]["remember"] = False  # not remembered: no card
    tab.back()
    tab.reload_roms()
    qtbot.waitUntil(lambda: tab.home.stick_cards == {})


def test_an_empty_stick_has_a_card_too(qtbot, drive, config, tmp_path):  # noqa: F811
    from gamingcrypt.system.removable import Removable

    empty = Removable(tmp_path / "EMPTY", "sd", "EMPTY", uuid="9")
    empty.mount.mkdir()
    tab = make_tab(qtbot, drive, config)
    tab.set_drives([empty])
    qtbot.waitUntil(lambda: "fs:9" in tab.home.stick_cards)
    assert tab.home.stick_cards["fs:9"].subtitle.text() == "0 games"
    tab.open_stick("fs:9")
    qtbot.waitUntil(lambda: "No games on it yet" in tab.currentWidget().status.text())


def test_the_filter(qtbot, drive, config, stick):  # noqa: F811
    tab = make_tab(qtbot, drive, config)
    (drive / "Emulation" / "roms" / "snes" / "Mario.sfc").write_bytes(b"x")  # one on the drive
    tab.reload_roms()
    home = tab.home
    qtbot.waitUntil(lambda: "Mario" in names(tab))
    assert home.platform_combo.findData(game_facts.ON_A_STICK) < 0  # no stick: not offered
    tab.set_drives([stick])
    qtbot.waitUntil(lambda: home.platform_combo.findData(game_facts.ON_A_STICK) > 0)
    index = home.platform_combo.findData(game_facts.ON_A_STICK)
    assert home.platform_combo.itemText(index) == STICK_CHOICE
    home.platform_combo.setCurrentIndex(index)
    qtbot.waitUntil(lambda: shown_names(tab) == ["Celeste", "Earthbound"])
    home.platform_combo.setCurrentIndex(0)
    qtbot.waitUntil(lambda: shown_names(tab) == ["Celeste", "Earthbound", "Mario"])


def test_choose_on_a_stick():
    from types import SimpleNamespace

    games = [SimpleNamespace(appid=1, name="A", removable="usb"), SimpleNamespace(appid=2, name="B", removable="")]
    facts = {1: game_facts.Facts("SNES", (), None), 2: game_facts.Facts("SNES", (), None)}
    assert [g.name for g in game_facts.choose(games, facts, platform=game_facts.ON_A_STICK)] == ["A"]
