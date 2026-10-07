"""Upscaling algorithms of emulated games: the whole picture on 2D consoles, the textures on 3D
ones; Resolution is the algorithm's factor (2D) or the internal resolution (3D)."""

import copy

import pytest

from gamingcrypt.emulation import retroarch, scalers, shaders
from gamingcrypt.emulation.library import EmulationPaths, scan
from gamingcrypt.emulation.systems import BY_ID


def test_what_each_kind_of_core_offers():
    assert scalers.choices("snes9x") == ["supereagle", "super2xsai", "hq", "scale", "xbr", "xbrz"]  # 2D: all
    assert scalers.choices("mupen64plus_next") == ["super2xsai", "hq", "xbrz"]  # GLideN64's texture ones
    assert scalers.choices("swanstation") == ["xbr"] and scalers.choices("mednafen_psx_hw") == ["xbr"]
    assert scalers.choices("ppsspp") == ["xbrz"] and scalers.choices("flycast") == ["xbrz"]
    assert scalers.choices("pcsx2") == []  # no texture upscaling in the PS2 core
    assert scalers.resolutions("snes9x", None) == ["1x"]  # nothing to draw bigger
    assert scalers.resolutions("snes9x", "supereagle") == ["2x", "4x"]
    assert scalers.resolutions("snes9x", "hq") == ["2x", "3x", "4x"]
    assert scalers.resolutions("pcsx2", None) == retroarch.scales("pcsx2")  # 3D: the internal resolution
    assert scalers.fit_resolution("snes9x", "supereagle", "3x") in ("2x", "4x")  # one it has
    assert scalers.fit_resolution("snes9x", "hq", None) == "2x"  # an algorithm draws at least 2x
    assert scalers.fit_resolution("snes9x", None, "2x") is None
    assert scalers.fit_resolution("pcsx2", None, "4x") == "4x"


def test_the_target_resolution_info():
    assert scalers.describe("snes", "snes9x", "hq", "2x") == (
        "HQx 2x: 256×224 drawn at 512×448, then scaled to the screen (1280×800)")
    assert scalers.describe("snes", "snes9x", None, None) == "The console's 256×224, then scaled to the screen (1280×800)"
    assert scalers.describe("n64", "mupen64plus_next", "xbrz", "2x") == (
        "Renders at 640×480 (2x the console's 320×240), textures smoothed with xBRZ - then scaled to the screen "
        "(1280×800)")
    assert scalers.describe("ps2", "pcsx2", "xbrz", None) == (
        "Renders at 640×448 (the console's own) - then scaled to the screen (1280×800)")  # no textures there


def test_texture_options_of_3d_cores():
    assert scalers.texture_options("mupen64plus_next", "xbrz", "4x") == {"mupen64plus-txEnhancementMode": "4xBRZ"}
    assert scalers.texture_options("mupen64plus_next", "hq", "2x") == {"mupen64plus-txEnhancementMode": "HQ2X"}
    assert scalers.texture_options("mupen64plus_next", "hq", "4x") == {"mupen64plus-txEnhancementMode": "HQ4X"}
    assert scalers.texture_options("parallel_n64", "super2xsai", None) == {
        "parallel-n64-gliden64-txEnhancementMode": "X2SAI"}
    assert scalers.texture_options("swanstation", "xbr", None) == {"swanstation_GPU_TextureFilter": "xBR"}
    assert scalers.texture_options("ppsspp", "xbrz", "3x") == {"ppsspp_texture_scaling_type": "xbrz",
                                                               "ppsspp_texture_scaling_level": "3x"}
    assert scalers.texture_options("flycast", "xbrz", "3x") == {"reicast_texupscale": "4"}
    assert scalers.texture_options("swanstation", None, None) == {"swanstation_GPU_TextureFilter": "Nearest"}  # off
    assert scalers.texture_options("pcsx2", "xbrz", "2x") == {}


@pytest.fixture
def pack(tmp_path):
    """The files the algorithms and the last pass use, in the slang pack's layout."""
    root = tmp_path / "shaders_slang"
    for scaler in scalers.SCALERS:
        for n in scaler.factors:
            for settings in scaler.passes[n]:
                (root / settings["shader"]).parent.mkdir(parents=True, exist_ok=True)
                (root / settings["shader"]).write_text("//")
    (root / scalers.TO_SCREEN["shader"]).parent.mkdir(parents=True, exist_ok=True)
    (root / scalers.TO_SCREEN["shader"]).write_text("//")
    (root / "crt" / "shaders").mkdir(parents=True)
    (root / "crt" / "shaders" / "crt.slang").write_text("//")
    (root / "crt" / "crt-easymode.slangp").write_text("shaders = 1\nshader0 = shaders/crt.slang\nscale_type0 = viewport\n")
    return root


def test_the_algorithm_at_its_factor_then_to_the_screen(pack, tmp_path, monkeypatch):
    text = shaders.write_preset([], tmp_path / "a.slangp", pack, "hq", "3x").read_text()
    assert text.startswith("shaders = 4\n")  # 3 HQx passes + the rest of the way
    assert 'scale2 = "3"' in text and "hq3x.slang" in text and 'LUT = "' in text and "hq3x.png" in text
    assert 'scale_type3 = "viewport"' in text and "bicubic.slang" in text
    four = shaders.write_preset([], tmp_path / "b.slangp", pack, "supereagle", "4x").read_text()
    assert four.startswith("shaders = 3\n")  # a 2x algorithm drawn twice
    monkeypatch.setitem(shaders.BY_ID, "crt", shaders.Shader("crt", "CRT", "", "crt/crt-easymode.slangp", "screen"))
    crt = shaders.write_preset(["crt"], tmp_path / "c.slangp", pack, "xbrz", "2x").read_text()
    assert crt.startswith("shaders = 2\n") and "xbrz-freescale" in crt and "crt.slang" in crt  # the CRT, last
    assert "bicubic" not in crt  # the screen effect goes to the screen itself
    assert shaders.write_preset([], tmp_path / "d.slangp", pack, None, "2x") is None


@pytest.fixture
def emu(tmp_path, monkeypatch):
    monkeypatch.setattr(retroarch, "CORE_DIRS", ())
    paths = EmulationPaths(tmp_path / "Emulation")
    paths.ensure()
    (paths.roms / "snes" / "Mario.sfc").write_text("x")
    (paths.roms / "n64" / "Zelda.z64").write_text("x")
    for core in ("snes9x", "mupen64plus_next"):
        (paths.cores / f"{core}_libretro.so").write_text("x")
    return paths


def start(emu, tmp_path, system, **kw):
    started = []
    game = scan(emu, BY_ID[system])[0]
    assert retroarch.launch(game, emu, tmp_path / "d", tmp_path / "l", popen=lambda cmd, **k: started.append(cmd),
                            which=lambda t: "/usr/bin/retroarch", **kw)[0]
    return started[-1], game


def test_2d_game_gets_the_algorithm_as_shader(emu, tmp_path, pack):
    cmd, game = start(emu, tmp_path, "snes", scaler="xbr", resolution="3x", shader_dirs=[pack], shaders=[])
    preset = emu.config / "shaders" / retroarch.SHADER_PRESET
    assert f"--set-shader={preset}" in cmd
    text = preset.read_text()
    assert "xbr-lv2-pass1.slang" in text and 'scale2 = "3"' in text
    assert not retroarch.core_options_file(emu, game).exists()  # nothing for the core


def test_3d_game_gets_the_algorithm_on_its_textures(emu, tmp_path, pack):
    cmd, game = start(emu, tmp_path, "n64", scaler="xbrz", resolution="2x", shader_dirs=[pack], shaders=[])
    options = retroarch.core_options_file(emu, game).read_text()
    assert 'mupen64plus-txEnhancementMode = "2xBRZ"' in options and 'mupen64plus-EnableNativeResFactor = "2"' in options
    assert not any(a.startswith("--set-shader") for a in cmd)  # not on the whole picture
    start(emu, tmp_path, "n64", scaler=None, resolution="2x", shader_dirs=[pack], shaders=[])
    assert 'mupen64plus-txEnhancementMode = "None"' in retroarch.core_options_file(emu, game).read_text()  # undone


@pytest.fixture
def tab(qtbot, emu):
    from gamingcrypt.config import DEFAULTS
    from gamingcrypt.ui.games_tab import GamesTab
    from tests.fakes import FakeService

    (emu.roms / "ps2" / "NFS.iso").write_text("x")
    t = GamesTab(FakeService(), library_settings=copy.deepcopy(DEFAULTS)["libraries"], emulation_root=str(emu.root))
    t.covers = None
    qtbot.addWidget(t)
    qtbot.waitUntil(lambda: {"snes", "n64", "ps2"} <= set(t.roms))
    return t


def open_options(tab, system):
    game = tab.roms[system][0]
    tab.open_rom(game)
    page = tab.currentWidget()
    page.screen_size = lambda: (1280, 800)
    return page, game


def items(combo) -> list[str]:
    return [combo.itemText(i) for i in range(combo.count())]


def test_2d_options(qtbot, tab):
    page, game = open_options(tab, "snes")
    assert items(page.scaler_combo) == ["None", "SuperEagle", "Super 2xSaI", "HQx", "ScaleNx", "xBR", "xBRZ"]
    assert not page.resolution_combo.isEnabled()  # no algorithm: the console's size
    page.scaler_combo.setCurrentIndex(page.scaler_combo.findData("hq"))
    assert page.resolution_combo.isEnabled() and [page.resolution_combo.itemData(i) for i in range(3)] == [
        "2x", "3x", "4x"]
    assert tab.profiles.get(game.appid) == {"scaler": "hq", "resolution": "2x"}  # at least 2x
    assert page.scaling_info.text().startswith("HQx 2x: 256×224 drawn at 512×448, then scaled to the screen")
    page.resolution_combo.setCurrentIndex(page.resolution_combo.findData("4x"))
    assert "drawn at 1024×896" in page.scaling_info.text()
    page.scaler_combo.setCurrentIndex(page.scaler_combo.findData("super2xsai"))  # has 2x and 4x
    assert [page.resolution_combo.itemData(i) for i in range(page.resolution_combo.count())] == ["2x", "4x"]
    assert tab.profiles.get(game.appid)["resolution"] == "4x"


def test_3d_options(qtbot, tab):
    page, game = open_options(tab, "n64")
    assert items(page.scaler_combo) == ["None", "Super 2xSaI", "HQx", "xBRZ"]  # the core's texture ones
    page.scaler_combo.setCurrentIndex(page.scaler_combo.findData("xbrz"))
    page.resolution_combo.setCurrentIndex(page.resolution_combo.findData("3x"))  # both together
    assert tab.profiles.get(game.appid) == {"scaler": "xbrz", "resolution": "3x"}
    assert page.scaling_info.text().startswith("Renders at 960×720 (3x the console's 320×240), textures smoothed with xBRZ")
    tab.back()
    page, game = open_options(tab, "ps2")
    assert not page.scaler_combo.isEnabled() and "no texture upscaling" in page.scaler_combo.currentText()
    assert page.resolution_combo.isEnabled()


def test_app_passes_the_algorithm(qtbot, emu, monkeypatch):
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

    w = MainWindow(copy.deepcopy(DEFAULTS), lambda c: None, page_factory=factory)
    qtbot.addWidget(w)
    w.windowed, w.update_check_enabled = True, False
    w.show_shell()
    games = pages["Games"]
    qtbot.waitUntil(lambda: "snes" in games.roms)
    game = games.roms["snes"][0]
    w.game_profiles.set(game.appid, "scaler", "xbrz")
    w.game_profiles.set(game.appid, "resolution", "3x")
    w.launch_rom(game)
    assert seen[-1]["scaler"] == "xbrz" and seen[-1]["resolution"] == "3x"


def test_5x_and_6x():
    """xBRZ draws any factor up to 6x, ScaleNx 6x as 3x then 2x; the 3D cores that have them
    render at 5x / 6x (the PS2 core and Beetle PSX don't)."""
    assert scalers.resolutions("snes9x", "xbrz") == ["2x", "3x", "4x", "5x", "6x"]
    assert scalers.resolutions("snes9x", "scale") == ["2x", "3x", "4x", "6x"]
    assert scalers.resolutions("snes9x", "hq") == ["2x", "3x", "4x"]  # (its passes can't be chained)
    passes, _t, _v = scalers.preset("scale", "6x", "/pack")
    assert [p["shader"].rsplit("/", 1)[1] for p in passes] == ["scale3x.slang", "scale2x.slang"]
    assert [p["scale"] for p in passes] == ["3", "2"]  # 3x, then that 2x: 6x
    assert scalers.preset("xbrz", "5x", "/pack")[0][0]["scale"] == "5"
    assert scalers.fit_resolution("snes9x", "scale", "5x") == "4x"  # what it has, nearest
    assert scalers.describe("snes", "snes9x", "xbrz", "6x") == (
        "xBRZ 6x: 256×224 drawn at 1536×1344, then scaled to the screen (1280×800)")
    for core in ("swanstation", "mupen64plus_next", "parallel_n64", "flycast", "ppsspp", "desmume"):
        assert retroarch.scales(core)[-2:] == ["5x", "6x"], core
    assert retroarch.UPSCALE["flycast"]["6x"] == {"reicast_internal_resolution": "3840x2880"}
    assert retroarch.scales("pcsx2") == ["1x", "2x", "4x"] and "5x" not in retroarch.scales("mednafen_psx_hw")
    assert scalers.texture_options("mupen64plus_next", "xbrz", "6x") == {"mupen64plus-txEnhancementMode": "6xBRZ"}
