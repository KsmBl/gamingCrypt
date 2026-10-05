"""Restart into another system (Windows) via UEFI BootNext - from the power menu and
the lock screen."""

import copy
import subprocess

import pytest

from gamingcrypt.helper import veracrypt_helper as helper
from gamingcrypt.system import boot

# efibootmgr output of the AYANEO test device (Linux is BootCurrent 0001)
LISTING = """BootCurrent: 0001
Timeout: 1 seconds
BootOrder: 0001,0000,0002,0003,0004
Boot0000* Windows Boot Manager\tHD(1,GPT,256e82de-aa06-44af-9bc7-809865088cde,0x800,0x32000)/\\EFI\\MICROSOFT\\BOOT\\BOOTMGFW.EFI57494e44
Boot0001* UEFI OS\tHD(5,GPT,501460ed-95cc-4535-b217-002fd6f8081f,0x56648800,0x200000)/\\EFI\\BOOT\\BOOTX64.EFI0000424f
Boot0002* UEFI:CD/DVD Drive\tBBS(129,,0x0)
Boot0003* UEFI:Removable Device\tBBS(130,,0x0)
Boot0004* UEFI:Network Device\tBBS(131,,0x0)
Boot0005  Old Fedora\tHD(1,GPT,1111,0x800,0x32000)/\\EFI\\FEDORA\\SHIMX64.EFI
"""


def runner_for(listing=LISTING, codes=None):
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        code = (codes or {}).get(cmd[0], 0)
        out = listing if cmd[-1] == "efibootmgr" or cmd == ["/usr/bin/efibootmgr"] else ""
        return subprocess.CompletedProcess(cmd, code, out, "Error: gamingcrypt helper: nope" if code else "")

    return run, calls


def test_parse_and_find_windows():
    current, entries = boot.parse(LISTING)
    assert current == "0001" and [e.num for e in entries] == ["0000", "0001", "0002", "0003", "0004", "0005"]
    windows = entries[0]
    assert windows.windows and windows.on_disk and windows.name == "Windows"
    assert not entries[3].on_disk  # USB / network / CD firmware entries
    run, _ = runner_for()
    others = boot.other_systems(run, which=lambda tool: "/usr/bin/efibootmgr")
    assert others == [windows]  # not the running Linux, not inactive or firmware entries


def test_no_uefi_no_systems():
    run, _ = runner_for()
    assert boot.other_systems(run, which=lambda tool: None) == []
    failing = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 2, "", "EFI variables are not supported")  # noqa
    assert boot.other_systems(failing, which=lambda tool: "/usr/bin/efibootmgr") == []


def test_reboot_into_sets_boot_next_then_restarts():
    run, calls = runner_for()
    windows = boot.parse(LISTING)[1][0]
    ok, message = boot.reboot_into(windows, run, helper="/h", exists=lambda p: True)
    assert ok and message == "Restarting into Windows…"
    assert calls == [["sudo", "-n", "/h", "boot-next", "0000"], ["systemctl", "reboot"]]


def test_reboot_into_does_not_restart_when_boot_next_fails():
    run, calls = runner_for(codes={"sudo": 1})
    windows = boot.parse(LISTING)[1][0]
    ok, message = boot.reboot_into(windows, run, helper="/h", exists=lambda p: True)
    assert not ok and message == "nope" and ["systemctl", "reboot"] not in calls  # stays in Linux
    assert boot.reboot_into(windows, run, helper="/h", exists=lambda p: False)[1].startswith("Run install.sh")


def test_power_action_boot(monkeypatch):
    from gamingcrypt.system.session import power_action

    run, calls = runner_for()
    monkeypatch.setattr(boot.shutil, "which", lambda tool: "/usr/bin/efibootmgr")
    monkeypatch.setattr(boot.os.path, "exists", lambda p: True)
    assert power_action("boot:0000", run) == (True, "Restarting into Windows…")
    assert power_action("boot:0003", run)[0] is False  # not offered -> refused


# --- root helper ----------------------------------------------------------------------

def test_helper_boot_next_only_for_systems_on_disks():
    run, calls = runner_for()
    assert helper.set_boot_next(["0000"], run=run, efibootmgr="/usr/bin/efibootmgr") == 0
    assert calls[-1] == ["/usr/bin/efibootmgr", "--bootnext", "0000"]
    for bad in (["0003"], ["0004"], ["0005"], ["9999"], ["00"], ["0000; reboot"], [], ["0000", "x"]):
        calls.clear()
        assert helper.set_boot_next(bad, run=run, efibootmgr="/usr/bin/efibootmgr") == 2, bad
        assert not any("--bootnext" in c for c in calls), bad  # USB / network / inactive: never


def test_helper_main_dispatches_boot_next(monkeypatch):
    seen = []
    monkeypatch.setattr(helper, "set_boot_next", lambda args: seen.append(args) or 0)
    assert helper.main(["boot-next", "0000"]) == 0 and seen == [["0000"]]


# --- UI ---------------------------------------------------------------------------------

WINDOWS = boot.BootEntry("0000", "Windows Boot Manager", "HD(1)/\\EFI\\MICROSOFT\\BOOT\\BOOTMGFW.EFI")


def test_power_menu_restart_into_windows(qtbot):
    from gamingcrypt.ui.shell import Shell

    shell = Shell()
    qtbot.addWidget(shell)
    shell.show()
    requested = []
    shell.power_requested.connect(requested.append)
    menu = shell.power_menu
    menu.set_systems([WINDOWS])
    button = menu.system_buttons["0000"]
    assert button.text() == "⊞  Restart into Windows"
    assert menu.box.indexOf(button) == menu.box.indexOf(menu.restart_button) + 1
    shell.open_power_menu()
    button.click()
    assert requested == ["boot:0000"]
    import shiboken6

    menu.set_systems([])
    assert menu.system_buttons == {}
    qtbot.waitUntil(lambda: not shiboken6.isValid(button))  # removed again


@pytest.fixture
def lock(qtbot):
    from gamingcrypt.ui.lock_screen import LockScreen
    from tests.test_lock_screen import FakeUnlocker

    screen = LockScreen(FakeUnlocker(), "pin")
    qtbot.addWidget(screen)
    screen.show()
    return screen


def test_lock_screen_power_buttons(lock):
    requested = []
    lock.power_requested.connect(requested.append)
    assert lock.shutdown_button.isVisible() and lock.restart_button.isVisible()
    assert not lock.windows_button.isVisible()  # no other system known (yet)
    lock.shutdown_button.click()
    lock.restart_button.click()
    lock.set_systems([boot.BootEntry("0005", "Fedora", "HD(1)/\\EFI\\FEDORA\\SHIMX64.EFI"), WINDOWS])
    assert lock.windows_button.isVisible() and lock.windows_button.text() == "⊞  Restart into Windows"
    lock.windows_button.click()
    assert requested == ["shutdown", "restart", "boot:0000"]  # Windows preferred


def test_main_window_lock_screen_power(qtbot, tmp_path, monkeypatch):
    from gamingcrypt.app import MainWindow
    from gamingcrypt.config import DEFAULTS
    from gamingcrypt.ui.lock_screen import LockScreen
    from tests.test_shell import FakeUnlocker

    cfg = copy.deepcopy(DEFAULTS)
    volume = tmp_path / "games.vc"
    volume.write_text("")
    cfg["unlock"].update(method="pin", volume=str(volume))
    MainWindow.systems_lister = staticmethod(lambda: [WINDOWS])
    try:
        window = MainWindow(cfg, lambda c: None, FakeUnlocker)
        qtbot.addWidget(window)
        window.show()
        lock = window.stack.currentWidget()
        assert isinstance(lock, LockScreen)
        qtbot.waitUntil(lambda: lock.windows_button.isVisible())  # found in the background
        ran = []
        monkeypatch.setattr(window, "power_runner", lambda kind: ran.append(kind) or (False, "Access denied"))
        lock.windows_button.click()
        assert ran == ["boot:0000"] and "Access denied" in lock.status.text()  # error on the lock screen
        window.show_shell()
        qtbot.waitUntil(lambda: "0000" in window.shell.power_menu.system_buttons)  # cached, same list
    finally:
        MainWindow.systems_lister = None
