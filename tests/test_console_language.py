"""The console's language - for every console that has one."""

import copy

import pytest

from gamingcrypt.config import DEFAULTS
from gamingcrypt.emulation import languages, retroarch
from gamingcrypt.emulation.library import EmulationPaths, scan
from gamingcrypt.emulation.systems import BY_ID

GERMAN = {"LANG": "de_DE.UTF-8"}


def test_which_systems_have_one():
    with_one = ("wii", "wiiu", "gc", "nds", "3ds", "ps2", "psp", "dreamcast", "switch")
    assert all(languages.has_language(BY_ID[s]) for s in with_one)
    assert [s for s in BY_ID if languages.has_language(BY_ID[s])] == [s for s in BY_ID if s in with_one]
    assert not languages.has_language(BY_ID["snes"]) and not languages.has_language(BY_ID["psx"])
    assert "Portuguese" in languages.languages(BY_ID["wiiu"]) and "Portuguese" not in languages.languages(BY_ID["wii"])


def test_without_a_choice_the_devices_language():
    wii = BY_ID["wii"]
    config = copy.deepcopy(DEFAULTS)
    assert languages.for_system(config, wii, GERMAN) == "German"
    assert languages.for_system(config, wii, {"LANG": "pt_BR.UTF-8"}) == "English"  # the Wii hasn't it
    assert languages.for_system(config, BY_ID["wiiu"], {"LANG": "pt_BR.UTF-8"}) == "Portuguese"
    assert languages.for_system(config, wii, {"LANG": "zh_TW.UTF-8"}) == "Traditional Chinese"
    assert languages.for_system(config, BY_ID["wiiu"], {"LANG": "zh_TW.UTF-8"}) == "Taiwanese"
    assert languages.for_system(config, wii, {}) == "English"
    assert languages.for_system(config, BY_ID["snes"], GERMAN) is None
    languages.set_chosen(config, "wii", "French")
    assert languages.for_system(config, wii, GERMAN) == "French"
    languages.set_chosen(config, "wii", None)
    assert "wii" not in config["console_language"]


def test_what_the_cores_get():
    assert languages.core_options("dolphin", "German") == {"dolphin_language": "2"}
    assert languages.core_options("dolphin", "Japanese") == {"dolphin_language": "0"}
    assert languages.core_options("cemu", "German") == {"cemu_console_language": "German"}
    assert languages.core_options("snes9x", "German") == {} and languages.core_options("cemu", None) == {}


@pytest.mark.parametrize("core, wanted", [
    ("azahar", {"citra_language_value": "German"}),
    ("citra", {"citra_language": "German"}),
    ("melonds", {"melonds_use_fw_settings": "disabled", "melonds_language": "German"}),  # (not the firmware's)
    ("desmume", {"desmume_firmware_language": "German"}),
    ("ppsspp", {"ppsspp_language": "German"}),
    ("flycast", {"reicast_language": "German"}),
    ("pcsx2", {}),  # no option: its own settings (ps2_nvram)
])
def test_the_other_consoles_cores_get_it(core, wanted):
    """The options as the cores name them (their libretro_core_options.h / core_settings.cpp)."""
    assert languages.core_options(core, "German") == wanted


def test_names_the_cores_spell_differently():
    assert languages.core_options("ppsspp", "Simplified Chinese") == {"ppsspp_language": "Chinese Simplified"}
    assert languages.core_options("flycast", "Korean") == {"reicast_language": "English"}  # it hasn't it
    assert languages.for_system({}, BY_ID["switch"], {"LANG": "en_GB.UTF-8"}) == "British English"
    assert languages.for_system({}, BY_ID["3ds"], {"LANG": "en_GB.UTF-8"}) == "English"
    assert languages.for_system({}, BY_ID["ps2"], GERMAN) == "German"
    assert languages.for_system({}, BY_ID["nds"], {"LANG": "ru_RU.UTF-8"}) == "English"  # a DS hasn't Russian


def test_a_switch_game_starts_in_it(tmp_path):
    from gamingcrypt.emulation import eden

    emu = EmulationPaths(tmp_path / "Emulation")
    emu.ensure()
    eden.prepare(emu, "German")
    ini = (emu.config / "switch" / "eden" / "qt-config.ini").read_text().splitlines()
    assert "[System]" in ini and "language_index=3" in ini and "language_index\\default=false" in ini
    eden.prepare(emu, "Japanese")
    ini = (emu.config / "switch" / "eden" / "qt-config.ini").read_text().splitlines()
    assert "language_index=0" in ini and "language_index=3" not in ini


@pytest.fixture
def paths(tmp_path, monkeypatch):
    monkeypatch.setattr(retroarch, "CORE_DIRS", ())
    p = EmulationPaths(tmp_path / "Emulation")
    p.ensure()
    return p


def test_a_game_starts_in_it(paths, tmp_path):
    (paths.cores / "dolphin_libretro.so").write_text("x")
    (paths.roms_for(BY_ID["wii"]) / "Wii Sports.wbfs").write_text("x")
    game = scan(paths, BY_ID["wii"])[0]
    run = dict(popen=lambda cmd, **k: None, which=lambda n: "/usr/bin/retroarch")
    retroarch.launch(game, paths, tmp_path / "d", tmp_path / "l", language="German", **run)
    options = retroarch.core_options_file(paths, game).read_text()
    assert 'dolphin_language = "2"' in options
    assert 'global_core_options = "true"' in (paths.config / "gamingcrypt.cfg").read_text()
    retroarch.launch(game, paths, tmp_path / "d", tmp_path / "l", language="English", **run)
    assert 'dolphin_language = "1"' in retroarch.core_options_file(paths, game).read_text()  # changed back


def test_the_system_page_sets_it(qtbot, paths):
    from gamingcrypt.ui.emulation_pages import SystemPage
    from gamingcrypt.ui.games_tab import GamesTab
    from tests.fakes import FakeService

    (paths.roms_for(BY_ID["wiiu"]) / "Mario Kart 8.wua").write_text("x")
    config, saved = copy.deepcopy(DEFAULTS), []
    tab = GamesTab(FakeService(), emulation_root=str(paths.root))
    tab.shader_config = (config, lambda c: saved.append(copy.deepcopy(c)))
    qtbot.addWidget(tab)
    tab.show()
    page = SystemPage(tab, BY_ID["wiiu"], scan(paths, BY_ID["wiiu"]))
    assert not page.language_button.isHidden()
    snes = SystemPage(tab, BY_ID["snes"], [])
    assert snes.language_button.isHidden()
    for system in ("ps2", "3ds", "switch"):
        assert not SystemPage(tab, BY_ID[system], []).language_button.isHidden(), system
    page.language_button.click()
    language = tab.currentWidget()
    assert language.combo.currentData() is None and language.combo.currentText().startswith("Like the device")
    language.combo.setCurrentIndex(language.combo.findData("Japanese"))
    assert saved[-1]["console_language"] == {"wiiu": "Japanese"}
    assert languages.for_system(config, BY_ID["wiiu"], GERMAN) == "Japanese"
    language.combo.setCurrentIndex(0)
    assert saved[-1]["console_language"] == {}
