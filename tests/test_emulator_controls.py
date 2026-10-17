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


def test_the_wii_picture_is_the_remote_and_the_nunchuk():
    """As held: the Wii Remote upright, the Nunchuk on its cable. Every button on its controller
    (shaking aside), none of them - or the caption under it - on another."""
    from PySide6.QtCore import QRectF

    from gamingcrypt.ui import console_pictures as cp

    pic = cp.picture("wii")
    body = cp._body(pic.body)
    rects = {}
    for name, (x, y, kind) in pic.buttons.items():
        w, h = cp.SIZES[kind]
        rects[name] = QRectF(x - w / 2, y - h / 2, w, h)
    for name, rect in rects.items():
        if name in ("C", "Z"):  # on the Nunchuk's front edge, as the shoulder buttons elsewhere
            assert body.intersects(rect) and not body.contains(rect), name
        elif not name.startswith("Shake"):
            assert body.contains(rect.center()), name
        assert QRectF(0, 0, cp.W, cp.H).contains(rect), name
    caption = 22  # (what the button is on the player's controller, under it)
    names = list(rects)
    dpad = set(cp.dpad_buttons(pic))  # (their captions sit in the cross's middle, as everywhere)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if a in dpad and b in dpad:
                continue
            assert not rects[a].adjusted(0, 0, 0, caption).intersects(rects[b]), (a, b)
            assert not rects[b].adjusted(0, 0, 0, caption).intersects(rects[a]), (a, b)
    remote, nunchuk = pic.buttons["A"], pic.buttons["C"]
    assert pic.dpad[1] < remote[1] < pic.buttons["1"][1] < pic.buttons["2"][1]  # top to bottom, as held
    assert nunchuk[0] < remote[0] and any(d[0] == "cable" for d in pic.decor)
    assert cp.button_text("Home") == "⌂"


def test_select_then_press_assigns(qtbot, store):
    from gamingcrypt.input import evdev as e
    from gamingcrypt.ui.controls_page import ControlsPage

    page = ControlsPage(store, "psx", systems=["snes", "psx"])
    qtbot.addWidget(page)
    page.resize(1280, 800)
    page.show()
    assert page.title.text() == "Controls · PlayStation (PS1)" and page.buttons["Cross"].text() == "✕"
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
    from gamingcrypt.ui.modal import open_modal

    page.reset_button.click()  # asks first
    modal = open_modal(page)
    assert "default layout for" in modal.content.question.text() and store.get("psx") != {}
    modal.content.cancel_button.click()  # changed its mind: nothing happens
    assert store.get("psx") != {} and open_modal(page) is None
    page.reset_button.click()
    open_modal(page).content.action_button.click()
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
    system_page.options_button.click()  # (the console's settings are in its Options)
    assert system_page.controls_button.isVisible()
    system_page.controls_button.click()
    page = tab.currentWidget()
    assert isinstance(page, ControlsPage) and page.system == "psx"
    assert not system_page.options_popup.is_open() and not system_page.options_button.isChecked()
    page.done_button.click()
    assert tab.currentWidget() is system_page


def test_a_consoles_name_is_whole_on_1280_px_with_every_text_size(qtbot, emu, store):
    """Controls, Shaders, Upscaling, Language and Add ROMs side by side cut the console's name off
    (and pushed the page past the screen with larger text): the console's settings are in its
    ⚙ Options now - each with a line on what it does - Add ROMs stays."""
    from PySide6.QtWidgets import QLabel

    from gamingcrypt.emulation.systems import SYSTEMS
    from gamingcrypt.ui import theme

    for system in SYSTEMS:
        folder = emu.roms / system.folder
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"Game{system.extensions[0]}").write_text("x")
    tab = games_tab(qtbot, emu, store)
    try:
        for size in theme.TEXT_SIZES:
            theme.apply("dark", size=size)
            tab.setStyleSheet(theme.STYLESHEET)
            for system in SYSTEMS:
                tab.open_system(system.id)
                page = tab.currentWidget()
                page.grab()
                assert page.minimumSizeHint().width() <= 1280, (size, system.id)
                assert page.title.width() >= page.title.sizeHint().width(), (size, system.name)
                tab.back()
    finally:
        theme.apply("dark", size="normal")
    tab.open_system("wiiu")
    page = tab.currentWidget()
    top = [w for w in (page.controls_button, page.shaders_button, page.upscaling_button, page.language_button)]
    assert not any(w.isVisibleTo(page) for w in top) and page.options_button.isVisibleTo(page)
    page.options_button.click()
    texts = [label.text() for label in page.options_panel.findChildren(QLabel)]
    assert any("language its games show their text in" in t for t in texts)
    assert page.gamepad_back() and not page.options_popup.is_open()  # B: Options closes first


def test_only_the_options_a_console_has(qtbot, emu):
    """Eden (the Switch) has no shaders, upscaling or button layout of RetroArch's - its ⚙ Options
    hold only the console's language."""
    from gamingcrypt.emulation.systems import BY_ID

    folder = emu.roms / BY_ID["switch"].folder
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"Game{BY_ID['switch'].extensions[0]}").write_text("x")
    tab = games_tab(qtbot, emu)
    tab.open_system("switch")
    page = tab.currentWidget()
    assert page.options_button.isVisibleTo(page)
    assert [b for b in page._options if b.property("offered")] == [page.language_button]


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


def test_playstation_pads_as_they_were():
    """The first PlayStation pad had no sticks (no L3 / R3); the DualShock 2 has them - and the
    N64 pad shows all four C buttons, two of them only drawn."""
    from gamingcrypt.emulation import layouts
    from gamingcrypt.ui import console_pictures

    ps1, ps2 = console_pictures.picture("psx"), console_pictures.picture("ps2")
    assert not ps1.sticks and "L3" not in layouts.console("psx") and "L3" not in ps1.buttons
    assert len(ps2.sticks) == 2 and {"L3", "R3"} <= set(layouts.console("ps2")) <= set(ps2.buttons)
    assert ps1.split_dpad and ps2.split_dpad and any(d[0] == "led" for d in ps2.decor)
    n64 = console_pictures.picture("n64")
    assert n64.body == "n64" and {d[-1] for d in n64.decor if d[0] == "dot"} == {"C▲", "C▶"}


def test_gamecube_pad_as_it_was():
    """Its own body, a small D-pad and the yellow C-stick - every button on the drawing."""
    from gamingcrypt.emulation import layouts
    from gamingcrypt.ui import console_pictures

    gc = console_pictures.picture("gc")
    assert gc.body == "gc" and gc.small_dpad and len(gc.sticks) == 2
    assert any(d[0] == "dot" and d[-1] == "C" for d in gc.decor)
    assert set(layouts.console("gc")) <= set(gc.buttons)
