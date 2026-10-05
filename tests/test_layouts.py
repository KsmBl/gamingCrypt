"""Controller layout per emulated system: defaults, editing in the controller test, RetroArch remaps."""

import copy

import pytest

from gamingcrypt.config import DEFAULTS
from gamingcrypt.emulation import layouts, retroarch
from gamingcrypt.emulation.library import EmulationPaths, scan
from gamingcrypt.emulation.systems import BY_ID, SYSTEMS
from gamingcrypt.input import evdev as e


def test_default_meanings():
    snes = layouts.labels("snes")
    assert snes["a"] == "B" and snes["b"] == "A" and snes["x"] == "Y" and snes["y"] == "X"  # by position
    n64 = layouts.labels("n64")
    assert n64["a"] == "A" and n64["x"] == "B" and n64["lt"] == "Z" and n64["r3"] == "C-buttons (stick)"
    assert layouts.labels("psx")["a"] == "Cross" and layouts.labels("megadrive")["x"] == "A"
    assert all(layouts.console(s.id) for s in SYSTEMS)  # every system has a layout
    assert layouts.labels("snes", {"a": "A"})["a"] == "A"


def test_remap_lines_swap_a_and_b():
    lines = layouts.remap_lines("snes", {"a": "A", "b": "B"})
    assert 'input_player1_btn_b = "8"' in lines  # Xbox A (RetroPad B) now sends RetroPad A
    assert 'input_player1_btn_a = "0"' in lines
    assert 'input_player1_btn_y = "1"' in lines  # untouched: itself
    assert lines[0] == 'input_remap_port_p1 = "0"'


def test_remap_file_names_and_defaults(tmp_path):
    info = tmp_path / "info"
    info.mkdir()
    (info / "snes9x_libretro.info").write_text('display_name = "Nintendo - SNES (Snes9x)"\ncorename = "Snes9x"\n')
    assert layouts.core_name("snes9x_libretro.so", info) == "Snes9x"
    assert layouts.core_name("mupen64plus_next_libretro.so", info) == "Mupen64Plus-Next"  # known name
    path = layouts.write_remap(tmp_path / "remaps", "snes9x_libretro.so", "snes", {"a": "A"}, info)
    assert path == tmp_path / "remaps" / "Snes9x" / "Snes9x.rmp" and "btn_b" in path.read_text()
    assert layouts.write_remap(tmp_path / "remaps", "snes9x_libretro.so", "snes", {}, info) is None
    assert not path.exists()  # default layout: RetroArch's own, no file


def test_config_store_validates():
    cfg = {"input": {"layouts": {"snes": {"a": "A", "zz": "B", "b": "Nonsense"}}}}
    assert layouts.load(cfg, "snes") == {"a": "A"}
    layouts.save(cfg, "snes", {})
    assert "snes" not in cfg["input"]["layouts"]


def test_launch_writes_the_layout(tmp_path, monkeypatch):
    monkeypatch.setattr(retroarch, "CORE_DIRS", ())
    monkeypatch.setattr(layouts, "INFO_DIR", tmp_path / "noinfo")
    paths = EmulationPaths(tmp_path / "Emulation")
    paths.ensure()
    (paths.roms / "snes" / "Game.sfc").write_text("x")
    (paths.cores / "snes9x_libretro.so").write_text("core")
    game = scan(paths, BY_ID["snes"])[0]
    retroarch.launch(game, paths, tmp_path / "data", tmp_path / "logs", popen=lambda *a, **k: None,
                     which=lambda t: "/usr/bin/retroarch", layout={"a": "A"})
    remap = paths.config / "remaps" / "Snes9x" / "Snes9x.rmp"
    assert remap.exists() and 'input_player1_btn_b = "8"' in remap.read_text()
    assert 'auto_remaps_enable = "true"' in (paths.config / "gamingcrypt.cfg").read_text()


# --- editing in the controller test ------------------------------------------------------------

@pytest.fixture
def page(qtbot):
    from gamingcrypt.ui.controller_test import ControllerTestPage
    from gamingcrypt.ui.settings_tab import SettingsTab

    cfg = copy.deepcopy(DEFAULTS)
    saved = []
    tab = SettingsTab(cfg, saved.append)
    qtbot.addWidget(tab)
    p = ControllerTestPage(**tab.controller_test_options())
    qtbot.addWidget(p)
    p.show()
    p._cfg, p._saved = cfg, saved
    return p


def test_change_a_button_for_a_system(qtbot, page):
    assert not page.edit_button.isVisible()  # plain controller: nothing to change
    page.system_combo.setCurrentIndex(page.system_combo.findData("snes"))
    assert page.edit_button.isVisible() and page.schematic.labels["x"] == "Y"
    page.edit_button.click()
    assert "Press the button" in page.hint.text()
    assert page.on_event(e.EV_KEY, e.BTN_NORTH, 1) is True  # Xbox X picked
    assert page.editing == "choose" and page.choices_box.isVisible()
    assert page.on_event(e.EV_ABS, e.ABS_HAT0X, 1) is False  # now the D-pad moves among the choices
    names = [page.choices.itemAt(i).widget().text() for i in range(page.choices.count())]
    assert "A" in names and "Start" in names
    page.choose("A")
    assert page._saved[-1]["input"]["layouts"]["snes"] == {"x": "A"}
    assert page.schematic.labels["x"] == "A" and page.reset_button.isVisible()
    assert page.schematic.value_text("x").startswith("A  ·  X")
    page.reset_button.click()
    assert "snes" not in page._cfg["input"]["layouts"] and page.schematic.labels["x"] == "Y"


def test_triggers_can_be_changed_and_default_choice_clears(qtbot, page):
    page.system_combo.setCurrentIndex(page.system_combo.findData("n64"))
    page.start_edit()
    page.on_event(e.EV_ABS, e.ABS_Z, 40)  # barely touched: not picked
    assert page.editing == "pick"
    page.on_event(e.EV_ABS, e.ABS_Z, 200)
    assert page.picked == "lt"
    page.choose("Z")  # that's the default anyway
    assert "n64" not in page._cfg["input"].get("layouts", {})


def test_launch_uses_the_saved_layout(qtbot, tmp_path, monkeypatch):
    from gamingcrypt.app import MainWindow
    from gamingcrypt.emulation.library import RomGame
    from gamingcrypt.ui.games_tab import GamesTab
    from tests.fakes import FakeService

    cfg = copy.deepcopy(DEFAULTS)
    layouts.save(cfg, "snes", {"a": "A"})
    seen = []
    monkeypatch.setattr(retroarch, "launch", lambda game, paths, data, logs, core=None, layout=None:
                        seen.append(layout) or (False, "x"))
    window = MainWindow(cfg, lambda c: None, page_factory=lambda c: {
        "Games": GamesTab(FakeService(), library_settings=c["libraries"], emulation_root=str(tmp_path))})
    qtbot.addWidget(window)
    window.show_shell()
    window.launch_rom(RomGame(BY_ID["snes"], tmp_path / "Game.sfc", "Game", 1))
    assert seen == [{"a": "A"}]


def test_every_value_fits_next_to_the_controller(qtbot):
    from PySide6.QtGui import QFont, QFontMetrics

    from gamingcrypt.ui import controller_test as ct
    from gamingcrypt.ui.controller_test import ControllerTestPage

    page = ControllerTestPage(labels_for=lambda system: layouts.labels(system),
                              systems=[(s.id, s.name) for s in SYSTEMS])
    qtbot.addWidget(page)
    font = QFont(page.font())
    font.setPixelSize(24)
    metrics = QFontMetrics(font)
    for i in range(page.system_combo.count()):
        page.system_combo.setCurrentIndex(i)
        for row in ct.LEFT_ROWS + ct.RIGHT_ROWS:
            text = page.schematic.value_text(row)
            assert metrics.horizontalAdvance(text) <= ct.COLUMN, (page.system_combo.currentText(), text)
