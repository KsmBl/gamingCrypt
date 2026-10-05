"""Emulator controls page (Settings, system page, quick menu) and emulated games in "Installed games"."""

import copy

import pytest

from gamingcrypt.config import DEFAULTS
from gamingcrypt.emulation import layouts, retroarch
from gamingcrypt.emulation.library import EmulationPaths, scan
from gamingcrypt.emulation.systems import BY_ID
from gamingcrypt.steam.models import SteamGame


@pytest.fixture
def emu(tmp_path):
    p = EmulationPaths(tmp_path / "Emulation")
    p.ensure()
    (p.roms / "snes" / "Super Mario World (USA).sfc").write_text("x")
    (p.roms / "psx" / "Crash Bandicoot (USA).chd").write_text("x")
    return p


@pytest.fixture
def store():
    saved = []
    s = layouts.Store(copy.deepcopy(DEFAULTS), saved.append)
    s.saved = saved
    return s


def test_store(store):
    assert store.labels("snes")["a"] == "B" and store.get("snes") == {}
    store.set("snes", "a", "A")
    assert store.get("snes") == {"a": "A"} and store.labels("snes")["a"] == "A" and store.saved
    store.set("snes", "a", "B")  # the default again: nothing stored
    assert store.get("snes") == {}
    store.set("snes", "x", "Y")
    store.reset("snes")
    assert store.get("snes") == {}


def test_assign_swaps(store):
    store.assign("psx", "Cross", "x")  # X presses Cross now, A gets X's Square
    assert store.get("psx") == {"x": "Cross", "a": "Square"}
    store.assign("psx", "Cross", "a")
    assert store.get("psx") == {}


def test_every_console_button_is_in_its_picture():
    from gamingcrypt.ui import console_pictures

    for sid, buttons in layouts.CONSOLES.items():
        assert set(buttons) <= set(console_pictures.picture(sid).buttons), sid


def test_select_then_press_assigns(qtbot, store):
    from gamingcrypt.input import evdev as e
    from gamingcrypt.ui.controls_page import ControlsPage

    page = ControlsPage(store, "psx", systems=["snes", "psx"])
    qtbot.addWidget(page)
    page.resize(1280, 800)
    page.show()
    assert page.title.text() == "Controls · PlayStation" and page.buttons["Cross"].text() == "✕"
    assert page.picture.captions["Cross"].text() == "A" and not page.reset_button.isVisible()
    page.buttons["Cross"].click()
    assert page.scanning == "Cross" and page.scan_box.isVisible()
    assert page.on_event(e.EV_KEY, e.BTN_NORTH, 1)  # X on the controller (evdev NORTH)
    assert page.scanning is None and store.get("psx") == {"x": "Cross", "a": "Square"}
    assert page.picture.captions["Cross"].text() == "X" and page.picture.captions["Square"].text() == "A"
    assert page.on_event(e.EV_KEY, e.BTN_NORTH, 0)  # its release is swallowed
    assert not page.on_event(e.EV_KEY, e.BTN_SOUTH, 1)  # not scanning: navigation as usual
    page.buttons["L2"].click()
    page.on_event(e.EV_ABS, e.ABS_RZ, 255)
    assert store.labels("psx")["rt"] == "L2"
    page.buttons["Circle"].click()
    page.tap_buttons["lb"].click()  # touch instead of a press
    assert store.labels("psx")["lb"] == "Circle"
    page.buttons["Square"].click()
    assert page.gamepad_back() and page.scanning == "Square"  # B is scanned, not back
    page.cancel_button.click()
    assert page.scanning is None
    page.reset_button.click()
    assert store.get("psx") == {}
    page.system_combo.setCurrentIndex(0)
    assert "B" in page.buttons and page.picture.captions["B"].text() == "A"
    with qtbot.waitSignal(page.closed):
        page.gamepad_back()


def test_settings_opens_emulator_controls(qtbot):
    from gamingcrypt.ui.controls_page import ControlsPage
    from gamingcrypt.ui.settings_tab import SettingsTab

    config = copy.deepcopy(DEFAULTS)
    tab = SettingsTab(config, lambda c: None)
    qtbot.addWidget(tab)
    tab.emulator_controls_button.click()
    page = tab.currentWidget()
    assert isinstance(page, ControlsPage) and page.system_combo.count() > 10
    page.start_scan("A")
    page.assign("x")
    assert layouts.load(config, page.system) == {"x": "A", "b": "Turbo B"}
    page.done_button.click()
    assert tab.currentWidget() is tab.overview


def games_tab(qtbot, emu, store=None, steam=()):
    from gamingcrypt.ui.games_tab import GamesTab
    from tests.fakes import FakeService

    tab = GamesTab(FakeService(list(steam)), emulation_root=str(emu.root))
    qtbot.addWidget(tab)
    tab.layout_store = store
    tab.resize(1280, 800)
    tab.show()
    qtbot.waitUntil(lambda: "snes" in tab.home.system_cards)
    return tab


def test_system_page_has_controls(qtbot, emu, store):
    from gamingcrypt.ui.controls_page import ControlsPage

    tab = games_tab(qtbot, emu, store)
    tab.open_system("psx")
    system_page = tab.currentWidget()
    assert system_page.controls_button.isVisible()
    system_page.controls_button.click()
    page = tab.currentWidget()
    assert isinstance(page, ControlsPage) and page.system == "psx"
    page.done_button.click()
    assert tab.currentWidget() is system_page


def test_no_controls_button_without_a_store(qtbot, emu):
    tab = games_tab(qtbot, emu)
    tab.open_system("snes")
    assert not tab.currentWidget().controls_button.isVisibleTo(tab.currentWidget())


def test_installed_games_include_emulated_ones(qtbot, emu):
    from gamingcrypt.ui.emulation_pages import RomCard

    portal = SteamGame(620, "Portal 2", installed=True)
    tab = games_tab(qtbot, emu, steam=[portal, SteamGame(10, "Not installed")])
    home = tab.home
    qtbot.waitUntil(lambda: len(home.result_appids) == 3)
    names = [home.cards[a].game.name for a in home.result_appids]
    assert names == ["Crash Bandicoot", "Portal 2", "Super Mario World"]
    mario = home.cards[home.result_appids[2]]
    assert isinstance(mario, RomCard) and mario.meta.text().startswith("SNES · ")
    home.search.setText("mario")
    assert [home.cards[a].game.name for a in home.result_appids] == ["Super Mario World"]
    assert not home.cards[620].isVisible()
    mario.clicked.emit(mario.game)
    assert tab.currentWidget().game is mario.game  # the ROM's page


@pytest.fixture
def window(qtbot, emu, monkeypatch):
    from gamingcrypt.app import MainWindow
    from gamingcrypt.ui.games_tab import GamesTab
    from tests.fakes import FakeService

    monkeypatch.setattr(retroarch, "launch", lambda *a, **k: (True, "Starting"))
    pages = {}

    def factory(cfg):
        pages["Games"] = GamesTab(FakeService(), library_settings=cfg["libraries"], emulation_root=str(emu.root))
        return dict(pages)

    w = MainWindow(copy.deepcopy(DEFAULTS), lambda c: None, page_factory=factory)
    qtbot.addWidget(w)
    w.windowed = True
    w.show()
    w.show_shell()
    games = pages["Games"]
    qtbot.waitUntil(lambda: "snes" in games.home.system_cards)
    w._games = games
    return w


def test_quick_menu_opens_the_running_games_controls(qtbot, window, emu, monkeypatch):
    from gamingcrypt.ui.controls_page import ControlsPage

    assert window._games.layout_store is not None  # the app gives the Games tab the layouts
    crash = scan(emu, BY_ID["psx"])[0]
    window.launch_rom(crash)
    window.game_watcher.phase = "playing"
    asides = []
    monkeypatch.setattr(window, "step_aside", lambda front="steam": asides.append(front))
    window.toggle_quick_menu()
    menu = window.quick_menu
    assert menu.controls_button.isVisibleTo(menu)
    menu.controls_button.click()
    page = window.controls_overlay
    assert isinstance(page, ControlsPage) and page.isVisible() and not menu.isVisible()
    assert page.system == "psx" and "Crash Bandicoot" in page.note.text() and asides == []
    assert window.nav_root() is page  # the controller stays on the page
    page.start_scan("Circle")
    page.assign("a")
    assert layouts.load(window.config, "psx") == {"a": "Circle", "b": "Cross"}
    page.gamepad_back()
    assert window.controls_overlay is None and asides == ["game"]  # back to the game


def test_controls_without_an_emulated_game_go_back_to_the_game(window, monkeypatch):
    asides = []
    monkeypatch.setattr(window, "step_aside", lambda front="steam": asides.append(front))
    window.game_watcher.appid, window.game_watcher.phase = 620, "playing"
    monkeypatch.setattr(type(window.game_watcher), "active", property(lambda self: True))
    window.open_running_controls()
    assert getattr(window, "controls_overlay", None) is None and asides == ["game"]


def test_dpad_can_be_changed(qtbot, store):
    from gamingcrypt.input import evdev as e
    from gamingcrypt.ui.controls_page import ControlsPage

    assert "Up" in layouts.console("snes") and store.labels("snes")["up"] == "Up"
    page = ControlsPage(store, "snes")
    qtbot.addWidget(page)
    page.resize(1280, 800)
    page.show()
    assert page.buttons["Up"].text() == "▲" and page.picture.captions["Up"].text() == "↑"
    page.buttons["Up"].click()
    assert page.on_event(e.EV_ABS, e.ABS_HAT0Y, 1)  # D-pad down on the controller
    assert store.get("snes") == {"down": "Up", "up": "Down"}
    assert 'input_player1_btn_down = "4"' in layouts.remap_lines("snes", store.get("snes"))
