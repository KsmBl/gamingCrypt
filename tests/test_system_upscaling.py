"""Every system has its own upscaling and resolution, for its games without their own."""

import copy

from gamingcrypt.emulation import retroarch, upscaling
from tests.test_scalers import emu, items, open_options, tab  # noqa: F401 - fixtures


def test_the_games_own_choice_else_its_systems():
    config = {}
    upscaling.set_system_choice(config, "snes", "xbrz", "6x")
    assert config == {"upscaling": {"snes": {"scaler": "xbrz", "resolution": "6x"}}}
    assert upscaling.for_game(config, {}, "snes") == ("xbrz", "6x")
    assert upscaling.for_game(config, {"scaler": "hq", "resolution": "3x"}, "snes") == ("hq", "3x")
    assert upscaling.for_game(config, {"scaler": "none", "resolution": "none"}, "snes") == (None, None)  # off by choice
    assert upscaling.for_game(config, {}, "nes") == (None, None)
    assert upscaling.describe_system(config, "snes") == "xBRZ 6x" and upscaling.describe_system(config, "n64") == "None"
    upscaling.set_system_choice(config, "snes", None, None)
    assert config == {"upscaling": {}}


def test_a_core_without_that_resolution_takes_the_nearest_lower_one():
    assert retroarch.nearest_scale("pcsx2", "6x") == "4x" and retroarch.nearest_scale("pcsx2", "3x") == "2x"
    assert retroarch.nearest_scale("swanstation", "6x") == "6x"
    assert retroarch.nearest_scale("pcsx2", None) is None and retroarch.nearest_scale("snes9x", "6x") == "6x"


def test_system_page(qtbot, tab):  # noqa: F811
    config, saved = {}, []
    tab.shader_config = (config, lambda c: saved.append(copy.deepcopy(c)))
    tab.open_system("snes")
    system_page = tab.currentWidget()
    assert system_page.upscaling_button.isVisibleTo(system_page)
    system_page.upscaling_button.click()
    page = tab.currentWidget()
    assert not page.resolution_combo.isEnabled()  # no algorithm: the console's size
    page.scaler_combo.setCurrentIndex(page.scaler_combo.findData("xbrz"))
    assert [page.resolution_combo.itemData(i) for i in range(page.resolution_combo.count())] == [
        "2x", "3x", "4x", "5x", "6x"]
    page.resolution_combo.setCurrentIndex(page.resolution_combo.findData("6x"))
    assert saved[-1]["upscaling"]["snes"] == {"scaler": "xbrz", "resolution": "6x"}
    assert "xBRZ 6x" in page.info.text()
    page.scaler_combo.setCurrentIndex(page.scaler_combo.findData("scale"))  # ScaleNx has no 5x - 6x it has
    assert page.resolution_combo.currentData() == "6x"
    tab.back()
    tab.back()
    options, game = open_options(tab, "snes")
    assert options.scaler_combo.currentText() == "System default (ScaleNx)"
    assert options.resolution_combo.currentText() == "System default (6x)"
    assert options.scaling_info.text().startswith("ScaleNx 6x: 256×224 drawn at 1536×1344")
    assert tab.profiles.get(game.appid) == {}  # nothing of its own


def test_3d_system_page(qtbot, tab):  # noqa: F811
    config = {}
    tab.shader_config = (config, lambda c: None)
    page = tab.open_upscaling("n64")
    assert items(page.scaler_combo) == ["None", "Super 2xSaI", "HQx", "xBRZ"]
    assert [page.resolution_combo.itemData(i) for i in range(page.resolution_combo.count())] == [
        None, "2x", "3x", "4x", "5x", "6x"]  # the core's internal resolutions
    page.resolution_combo.setCurrentIndex(page.resolution_combo.findData("5x"))
    assert config["upscaling"]["n64"] == {"resolution": "5x"}
    ps2 = tab.open_upscaling("ps2")
    assert not ps2.scaler_combo.isEnabled() and "no texture upscaling" in ps2.scaler_combo.currentText()


def test_the_app_starts_games_with_their_systems_choice(qtbot, emu, monkeypatch):  # noqa: F811
    from gamingcrypt.app import MainWindow
    from gamingcrypt.config import DEFAULTS
    from gamingcrypt.ui.games_tab import GamesTab
    from tests.fakes import FakeService

    seen = []
    monkeypatch.setattr(retroarch, "launch", lambda *a, **k: seen.append(k) or (True, "Starting"))
    monkeypatch.setattr(retroarch, "available", lambda *a: True)
    pages = {}

    def factory(cfg):
        pages["Games"] = GamesTab(FakeService(), library_settings=cfg["libraries"], emulation_root=str(emu.root))
        return dict(pages)

    config = copy.deepcopy(DEFAULTS)
    upscaling.set_system_choice(config, "snes", "xbrz", "4x")
    w = MainWindow(config, lambda c: None, page_factory=factory)
    qtbot.addWidget(w)
    w.windowed, w.update_check_enabled = True, False
    w.show_shell()
    games = pages["Games"]
    qtbot.waitUntil(lambda: "snes" in games.roms)
    game = games.roms["snes"][0]
    w.launch_rom(game)
    assert seen[-1]["scaler"] == "xbrz" and seen[-1]["resolution"] == "4x"
    w.game_profiles.set(game.appid, "scaler", "none")  # this one without
    w.launch_rom(game)
    assert seen[-1]["scaler"] is None and seen[-1]["resolution"] == "4x"
