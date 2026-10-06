"""Shaders for emulated games: tick them per system or per game, one preset, a preview."""

import copy

import pytest
from PySide6.QtCore import QSize
from PySide6.QtGui import QColor, QImage

from gamingcrypt.emulation import retroarch, shaders
from gamingcrypt.emulation.library import EmulationPaths, scan
from gamingcrypt.emulation.systems import BY_ID
from gamingcrypt.ui import shader_preview


# --- choosing ----------------------------------------------------------------------------------

def test_ticking_keeps_the_chain_order_and_one_final_picture():
    ids = shaders.toggle([], "crt", True)
    ids = shaders.toggle(ids, "ntsc", True)
    assert ids == ["ntsc", "crt"]  # colors first, the look last - whatever was ticked first
    ids = shaders.toggle(ids, "lcd", True)
    assert ids == ["ntsc", "lcd"]  # a screen effect unticks the other one
    ids = shaders.toggle(ids, "sharpen", True)
    assert ids == ["ntsc", "sharpen", "lcd"]
    assert shaders.toggle(ids, "ntsc", False) == ["sharpen", "lcd"]
    assert shaders.clean(["crt", "nope", "xbrz"]) == ["xbrz"]  # unknown ones go, the last final one wins
    assert shaders.toggle(["ntsc", "crt"], "scalefx", True) == ["ntsc", "scalefx"]  # an upscaler unticks the CRT
    assert shaders.toggle(["xbrz"], "sharp_pixels", True) == ["sharp_pixels"]  # and the other upscaler
    assert shaders.describe(["ntsc", "crt"]) == "TV signal (NTSC) + CRT TV" and shaders.describe([]) == "None"


def test_system_and_game_choices():
    config = {}
    assert shaders.system_shaders(config, "snes") == []
    shaders.set_system_shaders(config, "snes", ["crt"])
    assert config["shaders"] == {"snes": ["crt"]}
    assert shaders.for_game(config, {}, "snes") == ["crt"]  # nothing of its own: the system's
    assert shaders.for_game(config, {"shaders": ["lcd"]}, "snes") == ["lcd"]
    assert shaders.for_game(config, {"shaders": []}, "snes") == []  # its own: none
    assert shaders.own_shaders({}) is None and shaders.own_shaders({"shaders": []}) == []
    shaders.set_system_shaders(config, "snes", [])
    assert config["shaders"] == {}


# --- one preset ---------------------------------------------------------------------------------

@pytest.fixture
def slang(tmp_path):
    """A small shaders folder in the slang shaders' layout."""
    root = tmp_path / "shaders_slang"
    (root / "crt" / "shaders").mkdir(parents=True)
    (root / "stock.slang").write_text("//")
    (root / "crt" / "shaders" / "crt.slang").write_text("//")
    (root / "crt" / "mask.png").write_bytes(b"png")
    (root / "crt" / "crt-easymode.slangp").write_text(
        'shaders = 2\n\nshader0 = ../stock.slang\nalias0 = "Pre"\n'
        "shader1 = shaders/crt.slang  # the screen\nfilter_linear1 = false\nscale_type1 = viewport\n\n"
        'textures = "MASK"\nMASK = mask.png\nMASK_linear = true\n\nparameters = "GLOW"\nGLOW = "0.3"\n')
    (root / "crt" / "soft.slangp").write_text('#reference "crt-easymode.slangp"\nGLOW = "0.6"\nfilter_linear1 = true\n')
    (root / "ntsc").mkdir()
    (root / "ntsc" / "ntsc-adaptive.slangp").write_text("shaders = 1\nshader0 = ../stock.slang\nscale_x0 = 4.0\n")
    return root


def test_read_preset(slang):
    preset = shaders.read_preset(slang / "crt" / "crt-easymode.slangp")
    assert [p["shader"] for p in preset.passes] == [str(slang / "stock.slang"), str(slang / "crt/shaders/crt.slang")]
    assert preset.passes[0]["alias"] == "Pre" and preset.passes[1]["scale_type"] == "viewport"
    assert preset.textures == {"MASK": {"": str(slang / "crt" / "mask.png"), "_linear": "true"}}
    assert preset.values == {"GLOW": "0.3"}
    soft = shaders.read_preset(slang / "crt" / "soft.slangp")  # #reference + its overrides
    assert len(soft.passes) == 2 and soft.passes[1]["filter_linear"] == "true" and soft.values["GLOW"] == "0.6"


def test_presets_chained_into_one(slang, monkeypatch, tmp_path):
    monkeypatch.setitem(shaders.BY_ID, "crt", shaders.Shader("crt", "CRT", "", "crt/crt-easymode.slangp", "screen"))
    monkeypatch.setitem(shaders.BY_ID, "ntsc", shaders.Shader("ntsc", "NTSC", "", "ntsc/ntsc-adaptive.slangp", "color"))
    target = shaders.write_preset(["crt", "ntsc"], tmp_path / "out" / "x.slangp", slang)
    text = target.read_text()
    assert text.startswith("shaders = 3\n")
    assert f'shader0 = "{slang / "stock.slang"}"' in text and 'scale_x0 = "4.0"' in text  # NTSC first
    assert f'shader2 = "{slang / "crt/shaders/crt.slang"}"' in text and 'scale_type2 = "viewport"' in text
    assert 'alias1 = "Pre"' in text and 'textures = "MASK"' in text and 'MASK_linear = "true"' in text
    assert 'GLOW = "0.3"' in text
    assert shaders.write_preset([], tmp_path / "none.slangp", slang) is None
    assert shaders.write_preset(["lcd"], tmp_path / "gone.slangp", slang) is None  # its preset isn't there
    assert shaders.folder([tmp_path / "nothing", slang]) == slang and shaders.folder([tmp_path]) is None


def test_every_shader_is_in_a_group():
    assert {s.group for s in shaders.SHADERS} == set(shaders.GROUPS)
    upscalers = [s.id for s in shaders.SHADERS if s.group == "upscale"]
    assert upscalers == ["sharp_pixels", "xbrz", "scalefx"]  # apart from the screen effects
    assert all(s.final for s in shaders.SHADERS if s.group in ("upscale", "screen"))
    assert not any(s.final for s in shaders.SHADERS if s.group in ("color", "3d"))
    assert len(shaders.BY_ID) == len(shaders.SHADERS)


# --- RetroArch ------------------------------------------------------------------------------------

@pytest.fixture
def emu(tmp_path, monkeypatch):
    monkeypatch.setattr(retroarch, "CORE_DIRS", (tmp_path / "system-cores",))
    paths = EmulationPaths(tmp_path / "Emulation")
    paths.ensure()
    (paths.roms / "snes" / "Super Mario World.sfc").write_text("rom")
    (paths.cores / "snes9x_libretro.so").write_text("core")
    return paths


def launch(emu, tmp_path, **kw):
    started = []
    ok, _ = retroarch.launch(scan(emu, BY_ID["snes"])[0], emu, tmp_path / "data", tmp_path / "logs",
                             popen=lambda cmd, **k: started.append(cmd), which=lambda t: "/usr/bin/retroarch", **kw)
    assert ok
    return started[-1], (emu.config / "gamingcrypt.cfg").read_text()


def test_launch_with_shaders(emu, tmp_path, slang, monkeypatch):
    monkeypatch.setitem(shaders.BY_ID, "crt", shaders.Shader("crt", "CRT", "", "crt/crt-easymode.slangp", "screen"))
    cmd, cfg = launch(emu, tmp_path, shaders=["crt"], shader_dirs=[slang])
    preset = emu.config / "shaders" / retroarch.SHADER_PRESET
    assert f"--set-shader={preset}" in cmd and preset.read_text().startswith("shaders = 2")
    assert cmd.index(f"--set-shader={preset}") < cmd.index("-L")
    assert 'video_shader_enable = "true"' in cfg and 'video_driver = "glcore"' in cfg  # "gl" can't run slang
    cmd, cfg = launch(emu, tmp_path, shaders=[], shader_dirs=[slang])
    assert not any(a.startswith("--set-shader") for a in cmd) and "video_shader_enable" not in cfg
    cmd, cfg = launch(emu, tmp_path, shaders=["crt"], shader_dirs=[tmp_path / "not-installed"])
    assert not any(a.startswith("--set-shader") for a in cmd)  # not installed: plays without


# --- the preview -------------------------------------------------------------------------------

def picture(w=64, h=48) -> QImage:
    image = QImage(w, h, shader_preview.FORMAT)
    image.fill(QColor(200, 200, 200))
    return image


def brightness(image: QImage, x: int, y: int) -> int:
    c = image.pixelColor(x, y)
    return c.red() + c.green() + c.blue()


def test_preview_size_and_letterbox(qtbot):
    out = shader_preview.render(picture(), [], QSize(400, 200))
    assert out.size() == QSize(400, 200)
    assert brightness(out, 5, 100) == 0 and brightness(out, 200, 100) == 600  # bars beside a 4:3 picture


def test_preview_scanlines_and_grid(qtbot):
    size = QSize(64 * 8, 48 * 8)  # 8 screen pixels per console pixel
    plain = shader_preview.render(picture(), [], size)
    lines = shader_preview.render(picture(), ["scanlines"], size)
    assert brightness(lines, 100, 2) == brightness(plain, 100, 2)  # top of a row: bright
    assert brightness(lines, 100, 7) < brightness(plain, 100, 7) * 0.8  # its bottom: darker
    grid = shader_preview.render(picture(), ["lcd"], size)
    assert brightness(grid, 7, 100) < brightness(grid, 3, 100)  # lines between the columns too
    curved = shader_preview.render(picture(), ["crt_curved"], size)
    assert brightness(curved, 0, 0) == 0  # round corners


def test_preview_colors(qtbot):
    red = QImage(8, 8, shader_preview.FORMAT)
    red.fill(QColor(255, 0, 0))
    soft = shader_preview.handheld_colors(red).pixelColor(4, 4)
    assert soft.red() < 255 and soft.green() > 0  # less saturated
    green = shader_preview.render(picture(), ["gameboy"], QSize(64, 48)).pixelColor(32, 24)
    assert green.green() > green.red() and green.green() > green.blue()
    assert shader_preview.sharpen(picture()).size() == QSize(64, 48)
    assert shader_preview.fxaa(picture()).size() == QSize(64, 48)
    assert shader_preview.ntsc(picture()).size() == QSize(64, 48)


def test_scale2x_rounds_a_diagonal(qtbot):
    image = QImage(2, 2, shader_preview.FORMAT)
    black, white = QColor(0, 0, 0), QColor(255, 255, 255)
    for (x, y), color in {(0, 0): black, (1, 0): white, (0, 1): white, (1, 1): white}.items():
        image.setPixelColor(x, y, color)
    big = shader_preview.scale2x(image)
    assert big.size() == QSize(4, 4)
    assert big.pixelColor(0, 0) == black and big.pixelColor(1, 1) == white  # the stair's corner filled in
    assert big.pixelColor(3, 3) == white


def test_the_picture_is_the_newest_screenshot(qtbot, tmp_path):
    import os

    old, new = tmp_path / "Super_Mario_World_2025-01-01.png", tmp_path / "sub" / "Super Mario World-250102-1200.png"
    new.parent.mkdir()
    shot = QImage(1280, 800, shader_preview.FORMAT)
    shot.fill(QColor(0, 0, 0))
    for y in range(100, 700):
        for x in range(200, 1080, 40):
            shot.setPixelColor(x, y, QColor(255, 255, 255))
    shot.save(str(old))
    shot.save(str(new))
    os.utime(old, (1, 1))
    assert shader_preview.find_screenshot(["Super Mario World"], [tmp_path]) == new
    assert shader_preview.find_screenshot(["Zelda"], [tmp_path]) is None
    cropped = shader_preview.crop_borders(shot)
    assert cropped.width() < 1000 and cropped.height() < 700  # without the black bars
    assert shader_preview.sample("snes", new).size() == QSize(256, 224)  # at the console's size
    assert shader_preview.sample("ps2").size() == QSize(320, 224)  # 3D consoles: smaller
    assert not shader_preview.sample("gba").isNull()  # no screenshot: the little scene


# --- the pages ---------------------------------------------------------------------------------

@pytest.fixture
def tab(qtbot, emu):
    from gamingcrypt.config import DEFAULTS
    from gamingcrypt.ui.games_tab import GamesTab
    from tests.fakes import FakeService

    t = GamesTab(FakeService(), library_settings=copy.deepcopy(DEFAULTS)["libraries"], emulation_root=str(emu.root))
    t.covers = None
    saved = []
    t.shader_config = ({}, saved.append)
    t._saved = saved
    qtbot.addWidget(t)
    t.resize(1280, 730)
    t.show()
    qtbot.waitUntil(lambda: "snes" in t.roms)
    return t


def test_system_page_sets_the_systems_shaders(qtbot, tab):
    from gamingcrypt.ui.shader_page import ShaderPage

    tab.open_system("snes")
    system_page = tab.currentWidget()
    assert system_page.shaders_button.isVisible() and "Shaders" in system_page.shaders_button.text()
    system_page.shaders_button.click()
    page = tab.currentWidget()
    assert isinstance(page, ShaderPage) and page.same_button is None  # the system's own: no "same as"
    page.rows["crt"].click()
    page.rows["ntsc"].click()
    assert tab.shader_config[0]["shaders"]["snes"] == ["ntsc", "crt"] and tab._saved
    assert page.rows["crt"].isChecked() and page.rows["crt"].text().startswith("☑")
    page.rows["lcd"].click()  # the other screen effect goes
    assert not page.rows["crt"].isChecked() and tab.shader_config[0]["shaders"]["snes"] == ["ntsc", "lcd"]
    assert page.summary.text() == "TV signal (NTSC) + LCD grid"
    page.clear_button.click()
    assert "snes" not in tab.shader_config[0]["shaders"] and not page.rows["ntsc"].isChecked()


def test_game_options_choose_own_or_the_systems(qtbot, tab):
    shaders.set_system_shaders(tab.shader_config[0], "snes", ["crt"])
    game = tab.roms["snes"][0]
    tab.open_rom(game)
    game_page = tab.currentWidget()
    assert game_page.shaders_button.text() == "✨ Same as SNES: CRT TV"
    game_page.shaders_button.click()
    page = tab.currentWidget()
    assert page.same_button.isChecked() and page.rows["crt"].isChecked()
    page.rows["sharpen"].click()  # changing it: the game's own from now on
    assert page.own_button.isChecked() and tab.profiles.get(game.appid)["shaders"] == ["sharpen", "crt"]
    assert game_page.shaders_button.text() == "✨ Sharpen + CRT TV"
    page.clear_button.click()
    assert tab.profiles.get(game.appid)["shaders"] == []  # own: none (not the system's)
    assert game_page.shaders_button.text() == "✨ None"
    page.same_button.click()
    assert "shaders" not in tab.profiles.get(game.appid) and page.rows["crt"].isChecked()
    assert game_page.shaders_button.text() == "✨ Same as SNES: CRT TV"
    page.about.clear()
    page.rows["lcd"].setFocus()
    assert "LCD grid" in page.about.text()  # what the focused one does
    assert "one upscaler or screen effect at a time" in page.about.text()
    from PySide6.QtWidgets import QLabel

    headings = [label.text() for label in page.findChildren(QLabel) if label.objectName() == "section"]
    assert headings == ["Colors", "3D games", "Upscalers", "Screen effects"]


def test_app_starts_with_the_games_shaders(qtbot, emu, monkeypatch):
    from gamingcrypt.app import MainWindow
    from gamingcrypt.config import DEFAULTS
    from gamingcrypt.ui.games_tab import GamesTab
    from tests.fakes import FakeService

    seen = []
    monkeypatch.setattr(retroarch, "launch", lambda *a, **k: seen.append(k.get("shaders")) or (True, "Starting"))
    monkeypatch.setattr(retroarch, "available", lambda *a: True)
    pages = {}

    def factory(cfg):
        pages["Games"] = GamesTab(FakeService(), library_settings=cfg["libraries"], emulation_root=str(emu.root))
        return dict(pages)

    cfg = copy.deepcopy(DEFAULTS)
    cfg["shaders"] = {"snes": ["scanlines"]}
    w = MainWindow(cfg, lambda c: None, page_factory=factory)
    qtbot.addWidget(w)
    w.windowed, w.update_check_enabled = True, False
    w.show_shell()
    games = pages["Games"]
    qtbot.waitUntil(lambda: "snes" in games.roms)
    assert games.shader_config[0] is w.config  # the app's config: saved with it
    game = games.roms["snes"][0]
    w.launch_rom(game)
    w.game_profiles.set(game.appid, "shaders", ["lcd"])
    w.launch_rom(game)
    assert seen == [["scanlines"], ["lcd"]]


def test_install_script_installs_the_shaders():
    from pathlib import Path

    script = (Path(__file__).parent.parent / "install.sh").read_text()
    assert "install_shaders() {" in script and "libretro-shaders-slang" in script
    assert "\n    install_shaders\n" in script
