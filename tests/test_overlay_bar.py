"""The performance overlay over games as a bar: position, size, opacity, what's on it."""

import copy

from gamingcrypt.system import gamescope_ctl as gs
from gamingcrypt.system import overlay_bar


def lines(text: str) -> set[str]:
    return set(text.splitlines())


def test_the_bar_as_mangohud_config():
    text = overlay_bar.mangohud_config({"position": "bottom", "size": "large", "opacity": 30,
                                         "modules": ["fps", "battery", "time"]})
    got = lines(text)
    assert {"horizontal", "horizontal_stretch", "position=bottom-center", "font_size=32",
            "background_alpha=0.30", "fps=1", "battery=1", "time=1"} <= got
    assert {"cpu_stats=0", "gpu_stats=0", "ram=0", "frametime=0", "battery_watt=0", "frame_timing=0"} <= got
    assert "position=top-center" in overlay_bar.mangohud_config({"position": "top"})


def test_settings_are_completed_and_checked():
    assert overlay_bar.settings_of({}) == overlay_bar.DEFAULT
    odd = overlay_bar.settings_of({"overlay_bar": {"position": "left", "size": "huge", "opacity": "x",
                                                    "modules": ["time", "nonsense", "fps"]}})
    assert odd["position"] == "bottom" and odd["size"] == "medium" and odd["opacity"] == 50
    assert odd["modules"] == ["fps", "time"]  # known ones, in the bar's order
    assert overlay_bar.settings_of({"overlay_bar": {"opacity": 250}})["opacity"] == 100


def test_switching_it_on_shows_the_bar_as_set(tmp_path):
    env = {"XDG_CONFIG_HOME": str(tmp_path)}
    gs.set_overlay(True, env)
    assert "position=bottom-center" in gs.overlay_config(env).read_text()  # the default bar
    gs.set_overlay(False, env)
    gs.set_bar(overlay_bar.mangohud_config({"position": "top", "modules": ["fps"]}), env)
    assert not gs.overlay_shown(env)  # set while off: stays off
    gs.set_overlay(True, env)
    assert "position=top-center" in gs.overlay_config(env).read_text()
    gs.set_bar(overlay_bar.mangohud_config({"position": "bottom", "modules": ["fps"]}), env)
    assert "position=bottom-center" in gs.overlay_config(env).read_text()  # shown now: changed at once


def test_settings_section(qtbot):
    from gamingcrypt.config import DEFAULTS
    from gamingcrypt.ui.system_settings import OverlayBarSection

    config = copy.deepcopy(DEFAULTS)
    saved, written = [], []
    section = OverlayBarSection(config, lambda c: saved.append(copy.deepcopy(c)), write=written.append)
    qtbot.addWidget(section)
    assert section.choices["position"]["bottom"].isChecked() and section.choices["size"]["medium"].isChecked()
    assert section.module_buttons["fps"].text() == "✓  FPS" and section.module_buttons["time"].text() == "Time"
    section.choices["size"]["large"].click()
    section.module_buttons["time"].click()
    section.module_buttons["cpu"].click()
    assert saved[-1]["overlay_bar"]["size"] == "large"
    assert saved[-1]["overlay_bar"]["modules"] == ["fps", "frametime", "gpu", "ram", "battery", "time"]
    assert "time=1" in written[-1] and "cpu_stats=0" in written[-1] and "font_size=32" in written[-1]
    count = len(saved)
    for value in (40, 30, 20):
        section.opacity.setValue(value)
    assert len(saved) == count and section.opacity_value.text() == "20 %"  # (kept once it stops)
    qtbot.waitUntil(lambda: len(saved) == count + 1)
    assert saved[-1]["overlay_bar"]["opacity"] == 20 and "background_alpha=0.20" in written[-1]


def test_on_the_device_page(qtbot):
    from gamingcrypt.config import DEFAULTS
    from gamingcrypt.ui.settings_tab import SettingsTab

    tab = SettingsTab(copy.deepcopy(DEFAULTS), lambda c: None)
    qtbot.addWidget(tab)
    assert tab.sub_pages["Device"].isAncestorOf(tab.overlay_bar_section)
