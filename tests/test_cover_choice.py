"""Hold a game's picture to choose another one: wrong pictures and games without one."""

import copy
from pathlib import Path

import pytest
import requests
from PySide6.QtCore import QBuffer, QByteArray, QPoint, Qt
from PySide6.QtGui import QColor, QImage
from PySide6.QtTest import QTest

from gamingcrypt import cover_choice
from gamingcrypt.cover_choice import Choice, Offline
from gamingcrypt.emulation import covers as rom_covers
from gamingcrypt.emulation.library import EmulationPaths
from gamingcrypt.emulation.systems import BY_ID
from gamingcrypt.wine import covers as pc_covers
from tests.fakes import FakeService, cover_color


def png(color: str = "#20a040") -> bytes:
    image = QImage(60, 90, QImage.Format.Format_RGB32)
    image.fill(QColor(color))
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QBuffer.OpenModeFlag.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(data)


class Response:
    def __init__(self, data=None, content=b"", status=200):
        self.data, self.content, self.status_code = data, content, status

    def json(self):
        return self.data


# --- where the pictures come from -------------------------------------------------------------

def test_steam_search_with_the_games_own_picture_first():
    asked = []

    def get(url, params=None):
        asked.append(params["term"])
        return Response({"items": [{"id": 20, "name": "Need for Speed Underground 2"},
                                   {"id": 10, "name": "Own game again"},
                                   {"id": 30, "name": "A soundtrack", "type": "dlc"}]})

    choices = cover_choice.steam_choices("need for speed", get, own=(10, "NFS"))
    assert asked == ["need for speed"]
    assert [c.name for c in choices] == ["NFS", "Need for Speed Underground 2"]  # own once, no DLC
    assert "/apps/10/library_600x900.jpg" in choices[0].urls[0] and choices[1].urls[-1].endswith("/20/header.jpg")


def test_steam_search_offline():
    def offline(url, params=None):
        raise requests.ConnectionError("no network")

    with pytest.raises(Offline):
        cover_choice.steam_choices("x", offline)
    assert [c.name for c in cover_choice.steam_choices("x", offline, own=(10, "NFS"))] == ["NFS"]
    assert cover_choice.steam_choices("", offline) == []


@pytest.fixture
def emu(tmp_path):
    paths = EmulationPaths(tmp_path / "GamingCrypt" / "Emulation")
    paths.ensure()
    (paths.roms_for(BY_ID["snes"]) / "Super Mario World (Germany).sfc").write_bytes(b"x")
    return paths


def rom(emu):
    from gamingcrypt.emulation.library import scan

    return scan(emu, BY_ID["snes"])[0]


def test_box_art_search_by_words_in_the_games_region_first(emu, monkeypatch):
    names = ["Super Mario World (USA)", "Super Mario World (Germany)", "Super Mario World 2 - Yoshi's Island (USA)",
             "Super Mario Kart (USA)", "Zelda (USA)"]
    covers = rom_covers.Covers(emu)
    monkeypatch.setattr(covers, "index", lambda game: names)
    choices = cover_choice.rom_choices(covers, rom(emu), "mario world")
    assert [c.name for c in choices] == ["Super Mario World (Germany)", "Super Mario World (USA)",
                                         "Super Mario World 2 - Yoshi's Island (USA)"]
    assert choices[0].urls == ("https://thumbnails.libretro.com/Nintendo%20-%20Super%20Nintendo%20Entertainment"
                               "%20System/Named_Boxarts/Super%20Mario%20World%20%28Germany%29.png",)
    monkeypatch.setattr(covers, "index", lambda game: None)
    with pytest.raises(Offline):
        cover_choice.rom_choices(covers, rom(emu), "mario")


def test_download_takes_the_first_real_picture():
    pages = {"a": Response(content=b"<html>not found</html>"), "b": Response(status=404),
             "c": Response(content=png())}
    assert cover_choice.download(Choice("x", ("a", "b", "c")), lambda url: pages[url]) == pages["c"].content
    assert cover_choice.download(Choice("x", ("a", "b")), lambda url: pages[url]) is None


def test_saving_replaces_the_cover_and_its_miss(tmp_path):
    path = tmp_path / "covers" / "snes" / "Game.png"
    path.parent.mkdir(parents=True)
    path.with_suffix(".nomatch").write_text("1000")
    cover_choice.save(path, b"\x89PNG...")
    assert path.read_bytes() == b"\x89PNG..." and not path.with_suffix(".nomatch").exists()
    assert not path.with_suffix(".part").exists()


def test_where_each_kind_of_game_keeps_its_cover(emu, tmp_path):
    from gamingcrypt.steam.models import SteamGame
    from gamingcrypt.ui.games_tab import GamesTab
    from gamingcrypt.wine.library import WindowsGame

    class Tab:
        covers = rom_covers.Covers(emu)
        windows_covers = pc_covers.Covers(tmp_path / "Windows Games")
        linux_covers = None
        service = FakeService()

    Tab.service.cache_dir = tmp_path / "cache"
    game = rom(emu)
    source = cover_choice.source_for(game, Tab)
    assert source.path == Tab.covers.path(game) and source.query == "Super Mario World"
    knight = WindowsGame(tmp_path / "Windows Games" / "Hollow_Knight [GOG]", "Hollow_Knight [GOG]")
    source = cover_choice.source_for(knight, Tab)
    assert source.path == Tab.windows_covers.path(knight) and source.query == "Hollow Knight"
    source = cover_choice.source_for(SteamGame(1091500, "Cyberpunk 2077®"), Tab)
    assert source.path == tmp_path / "cache" / "images" / "1091500.jpg" and source.query == "Cyberpunk 2077"
    from gamingcrypt.linux.library import LinuxGame

    assert cover_choice.source_for(LinuxGame(tmp_path / "x", "x"), Tab) is None  # no Linux games folder
    assert GamesTab  # (the tab is tested below)


# --- holding a picture ------------------------------------------------------------------------

@pytest.fixture
def tab(qtbot, emu, monkeypatch):
    from gamingcrypt.ui.games_tab import GamesTab

    monkeypatch.setattr(rom_covers.Covers, "fetch", lambda self, game: None)
    monkeypatch.setattr(rom_covers.Covers, "index", lambda self, game: ["Super Mario World (Germany)",
                                                                        "Super Mario World (USA)"])
    asked = []

    def get(url, params=None):
        asked.append(url)
        return Response(content=png("#20a040" if "Germany" in url else "#3050e0"))

    monkeypatch.setattr(cover_choice, "_default_get", get)
    t = GamesTab(FakeService(), emulation_root=str(emu.root))
    qtbot.addWidget(t)
    t.resize(1280, 800)
    t.show()
    t.reload_roms()
    qtbot.waitUntil(lambda: "snes" in t.home.system_cards)
    t.open_system("snes")
    t._asked = asked
    return t


def hold(qtbot, widget, ms=700, move=0):
    """A finger on the picture, as the device delivers it: to the window first."""
    window = widget.window().windowHandle()
    at = widget.mapTo(widget.window(), QPoint(20, 20))
    QTest.mousePress(window, Qt.MouseButton.LeftButton, pos=at)
    if move:
        for step in range(1, 7):
            QTest.mouseMove(window, at + QPoint(0, step * move // 6))
            qtbot.wait(10)
    qtbot.wait(ms)
    QTest.mouseRelease(window, Qt.MouseButton.LeftButton, pos=at + QPoint(0, move))
    qtbot.wait(20)


def tap(qtbot, widget):
    window = widget.window().windowHandle()
    at = widget.mapTo(widget.window(), QPoint(20, 20))
    QTest.mouseClick(window, Qt.MouseButton.LeftButton, pos=at)
    qtbot.wait(20)


def test_holding_a_cover_opens_the_picker_not_the_game(qtbot, tab):
    from gamingcrypt.ui.cover_picker import CoverPicker

    card = next(iter(tab.currentWidget().cards.values()))
    hold(qtbot, card.cover)
    picker = tab.currentWidget()
    assert isinstance(picker, CoverPicker) and picker.item == card.game
    assert picker.search.text() == "Super Mario World"
    qtbot.waitUntil(lambda: len(picker.cards) == 2 and all(c.data for c in picker.cards))
    assert [c.choice.name for c in picker.cards] == ["Super Mario World (Germany)", "Super Mario World (USA)"]


def test_a_tap_still_opens_the_game_and_scrolling_doesnt_hold(qtbot, tab):
    from gamingcrypt.ui.cover_picker import CoverPicker
    from gamingcrypt.ui.emulation_pages import RomGamePage

    card = next(iter(tab.currentWidget().cards.values()))
    hold(qtbot, card.cover, move=60)  # a flick, however long
    assert not isinstance(tab.currentWidget(), CoverPicker)
    tab.open_system("snes")
    card = next(iter(tab.currentWidget().cards.values()))
    tap(qtbot, card.cover)
    assert isinstance(tab.currentWidget(), RomGamePage)


def test_choosing_a_picture_shows_it_everywhere(qtbot, tab):
    page_card = next(iter(tab.currentWidget().cards.values()))
    game = page_card.game
    tab.open_rom(game)
    detail = tab.currentWidget()
    hold(qtbot, detail.cover)  # on the game's page too
    picker = tab.currentWidget()
    qtbot.waitUntil(lambda: len(picker.cards) == 2 and all(c.data for c in picker.cards))
    picker.cards[1].tapped.emit()  # the blue one
    assert tab.currentWidget() is detail
    assert tab.covers.path(game).read_bytes()[:4] == b"\x89PNG"
    qtbot.waitUntil(lambda: cover_color(detail.cover) == "#3050e0")
    assert cover_color(page_card.cover) == "#3050e0"  # its card on the system page too


def test_drawn_cover_stays_drawn(qtbot, tab):
    from gamingcrypt.ui.game_widgets import placeholder_cover

    card = next(iter(tab.currentWidget().cards.values()))
    tab.covers.path(card.game).parent.mkdir(parents=True, exist_ok=True)
    tab.covers.path(card.game).write_bytes(png("#ff0000"))  # the wrong picture
    hold(qtbot, card.cover)
    tab.currentWidget().drawn_button.click()
    assert tab.covers.path(card.game).read_bytes() == cover_choice.DRAWN
    assert tab.covers.cached(card.game) is not None  # nothing is looked up again
    letter = placeholder_cover(card.game.name, card.cover.width(), card.cover.height()).toImage()
    assert card.cover.pixmap().toImage() == letter


def test_search_again_and_nothing_found(qtbot, tab, monkeypatch):
    card = next(iter(tab.currentWidget().cards.values()))
    hold(qtbot, card.cover)
    picker = tab.currentWidget()
    qtbot.waitUntil(lambda: len(picker.cards) == 2)
    picker.search.setText("zelda")
    picker.do_search()
    qtbot.waitUntil(lambda: "Nothing found" in picker.status.text())
    assert picker.cards == []
    monkeypatch.setattr(rom_covers.Covers, "index", lambda self, game: None)
    picker.do_search()
    qtbot.waitUntil(lambda: "No network" in picker.status.text())


def test_choices_without_a_picture_are_left_out(qtbot, tab, monkeypatch):
    monkeypatch.setattr(cover_choice, "download", lambda choice, get: None if "USA" in choice.name else png())
    card = next(iter(tab.currentWidget().cards.values()))
    hold(qtbot, card.cover)
    picker = tab.currentWidget()
    qtbot.waitUntil(lambda: len(picker.cards) == 2 and picker.cards[0].data is not None)
    qtbot.waitUntil(lambda: picker.cards[1].isHidden())


def test_steam_game_cover(qtbot, tmp_path, monkeypatch):
    """A Steam game: its own picture among the store's, kept in the image cache."""
    from gamingcrypt.steam.models import SteamGame
    from gamingcrypt.ui.games_tab import GamesTab

    monkeypatch.setattr(cover_choice, "_default_get", lambda url, params=None: (
        Response({"items": [{"id": 7, "name": "Other"}]}) if params else Response(content=png("#3050e0"))))
    service = FakeService(games=[SteamGame(5, "Racer", installed=True)])
    service.cache_dir = tmp_path / "cache"
    t = GamesTab(service)
    qtbot.addWidget(t)
    t.show()
    qtbot.waitUntil(lambda: 5 in t.games)
    t.open_game(5)
    page = t.currentWidget()
    hold(qtbot, page.cover)
    picker = t.currentWidget()
    qtbot.waitUntil(lambda: len(picker.cards) == 2 and all(c.data for c in picker.cards))
    assert [c.choice.name for c in picker.cards] == ["Racer", "Other"]
    picker.cards[0].tapped.emit()
    assert (tmp_path / "cache" / "images" / "5.jpg").exists() and t.currentWidget() is page


def test_holding_without_a_drive_says_why(qtbot):
    from gamingcrypt.steam.models import SteamGame
    from gamingcrypt.ui.games_tab import GamesTab

    t = GamesTab(FakeService())  # FakeService has no image cache
    qtbot.addWidget(t)
    t.open_cover_picker(SteamGame(5, "Racer"))
    assert t.currentWidget() is t.home and "can't be changed" in t.home.notice.text()
    assert Path  # noqa
