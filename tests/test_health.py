"""Settings -> Health: every dependency with a clear fix."""

import subprocess

from gamingcrypt.input.evdev import DeviceInfo
from gamingcrypt.system.boot import BootEntry
from gamingcrypt.system.health import REINSTALL, Check, Health
from gamingcrypt.system.power import PowerLimit


def ok_runner(outputs=None, codes=None):
    def run(cmd, **kw):
        key = cmd[0] if cmd[0] != "sudo" else "sudo"
        return subprocess.CompletedProcess(cmd, (codes or {}).get(key, 0), (outputs or {}).get(key, ""), "")
    return run


def healthy(**over):
    args = dict(runner=ok_runner({"fc-list": "Noto Color Emoji\n", "busctl": 's "yes"\n'}),
                which=lambda tool: f"/usr/bin/{tool}", exists=lambda p: True, access=lambda p, m: True,
                env={"GAMINGCRYPT_SESSION": "1"}, helper="/h")
    args.update(over)
    return Health(**args)


def test_everything_fine():
    h = healthy()
    assert h.veracrypt().ok and h.helper_allowed().ok and h.xprop().ok and h.emoji_font().ok and h.sleep().ok
    assert h.steam_mode(lambda: "gamescope -e -f -- gamingcrypt").ok
    assert h.buttons(lambda: [DeviceInfo("/dev/input/event3", "AT Translated Set 2 keyboard")]).ok
    assert h.power_limit(lambda: PowerLimit(15, 5, 28, "AMD Renoir SMU")).detail == "5-28 W (AMD Renoir SMU)"
    assert h.other_system(lambda: [BootEntry("0000", "Windows Boot Manager", "HD()/\\EFI\\X\\BOOTMGFW.EFI")]).detail \
        == "Windows"
    assert h.steam(lambda: "/home/u/.local/share/Steam").ok


def test_problems_name_the_fix():
    h = healthy(which=lambda tool: None, exists=lambda p: False, access=lambda p, m: False,
                runner=ok_runner(codes={"sudo": 1, "busctl": 1}))
    assert h.veracrypt().fix.startswith("Install VeraCrypt")
    helper = h.helper_allowed()
    assert not helper.ok and helper.fix == REINSTALL
    assert not h.xprop().ok and "xorg-xprop" in h.xprop().fix
    assert not h.emoji_font().ok and "noto-fonts-emoji" in h.emoji_font().fix
    buttons = h.buttons(lambda: [DeviceInfo("/dev/input/event3", "kbd")])
    assert not buttons.ok and buttons.detail == "0 of 1 readable" and "--session" in buttons.fix
    assert not h.steam_mode(lambda: "gamescope -f -- gamingcrypt").ok
    assert not h.session().ok and h.session().optional  # gaming mode is optional
    assert not h.power_limit(lambda: PowerLimit(15, 5, 28, "x")).ok  # helper missing
    assert h.power_limit(lambda: None).optional
    assert not h.other_system().ok and h.other_system().optional


def test_sudo_rule_check_is_harmless():
    seen = []
    h = healthy(runner=lambda cmd, **kw: seen.append(cmd) or subprocess.CompletedProcess(cmd, 0, "", ""))
    h.helper_allowed()
    assert seen == [["sudo", "-n", "-l", "/h"]]  # only asks whether it's allowed - runs nothing


def test_steam_mode_outside_gaming_mode_is_fine():
    assert healthy(env={}).steam_mode(lambda: None).ok


def test_one_broken_probe_does_not_hide_the_others():
    h = healthy()
    h.veracrypt = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    h.steam = lambda: Check("Steam", True)
    h.buttons = lambda: Check("Buttons", True)
    h.power_limit = lambda: Check("Power", True)
    h.other_system = lambda: Check("Windows", True)
    checks = h.run()
    assert checks[0].ok is False and "boom" in checks[0].detail and len(checks) == 12


def test_health_page_in_settings(qtbot):
    from gamingcrypt.config import DEFAULTS
    from gamingcrypt.ui.settings_tab import SettingsTab

    class Fake:
        runs = 0

        def run(self):
            Fake.runs += 1
            return [Check("VeraCrypt", True, "installed"), Check("xprop", False, "missing", "Install xorg-xprop"),
                    Check("Gaming mode", False, "not installed", "Run ./install.sh --session", optional=True)]

    import copy
    tab = SettingsTab(copy.deepcopy(DEFAULTS), lambda c: None, health=Fake())
    qtbot.addWidget(tab)
    page = tab.health_page
    assert Fake.runs == 0  # only when opened
    tab.sub_buttons["Health"].click()
    qtbot.waitUntil(lambda: len(page.checks) == 3)
    texts = [page.grid.itemAt(i).widget().text() for i in range(page.grid.count())]
    assert texts[:3] == ["✓", "VeraCrypt", "installed"] and "→ Install xorg-xprop" in texts[5]
    assert texts[6] == "–"  # optional: not shown as an error
    assert page.status.text() == "1 problem(s) found"
    page.recheck_button.click()
    qtbot.waitUntil(lambda: Fake.runs == 2)
