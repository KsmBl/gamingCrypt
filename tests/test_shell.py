import copy

from PySide6.QtWidgets import QLabel

from gamingcrypt.app import MainWindow
from gamingcrypt.config import DEFAULTS
from gamingcrypt.ui.auth_setup import AuthSetupWizard
from gamingcrypt.ui.lock_screen import LockScreen
from gamingcrypt.ui.settings_tab import SettingsTab
from gamingcrypt.ui.shell import TABS, Shell
from gamingcrypt.ui.widgets import ComingSoon
from gamingcrypt.unlock.veracrypt import UnlockResult


class FakeUnlocker:
    configured = True

    def __init__(self, cfg=None):
        self.cfg = cfg or {}

    def unlock(self, secret):
        return UnlockResult(secret == "1234", "")

    def change_password(self, current, new, new_kdf=None):
        return UnlockResult(current == "1234", "Wrong code" if current != "1234" else "")


def configured():
    cfg = copy.deepcopy(DEFAULTS)
    cfg["unlock"].update(method="pin", volume="/dev/sdb1")
    return cfg


def test_shell_has_all_tabs_and_coming_soon(qtbot):
    shell = Shell()
    qtbot.addWidget(shell)
    assert list(shell.tab_buttons) == TABS
    assert shell.current_tab == "Games"
    for name in ["Movies", "Shows", "Music", "Pictures"]:
        shell.tab_buttons[name].click()
        assert shell.current_tab == name
        page = shell.stack.currentWidget()
        assert isinstance(page, ComingSoon)
        assert "Coming soon" in page.findChild(QLabel).text()


def test_shell_uses_given_pages(qtbot):
    custom = QLabel("games!")
    shell = Shell({"Games": custom})
    qtbot.addWidget(shell)
    assert shell.stack.currentWidget() is custom


def test_power_menu_options(qtbot):
    shell = Shell()
    qtbot.addWidget(shell)
    shell.resize(1280, 800)
    shell.show()
    events = []
    shell.exit_requested.connect(lambda: events.append("desktop"))
    shell.power_requested.connect(events.append)
    assert not shell.power_menu.isVisible()
    shell.exit_button.click()
    menu = shell.power_menu
    assert menu.isVisible() and menu.geometry() == shell.rect()
    assert shell.focusWidget() is menu.cancel_button  # controller A can't shut down by accident
    menu.shutdown_button.click()
    menu.restart_button.click()
    menu.desktop_button.click()
    assert events == ["shutdown", "restart", "desktop"]
    menu.cancel_button.click()
    assert not menu.isVisible()


def test_power_menu_closes_with_back(qtbot):
    shell = Shell()
    qtbot.addWidget(shell)
    shell.show()
    assert not shell.power_menu.gamepad_back()
    shell.open_power_menu()
    assert shell.power_menu.gamepad_back() and not shell.power_menu.isVisible()


def test_power_actions_run_systemctl():
    import subprocess

    from gamingcrypt.system.session import power_action

    calls = []

    def runner(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    assert power_action("shutdown", runner) == (True, "Shutting down…")
    assert power_action("restart", runner)[0]
    assert calls == [["systemctl", "poweroff"], ["systemctl", "reboot"]]
    failing = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "Access denied")  # noqa: E731
    assert power_action("shutdown", failing) == (False, "Access denied")

    def missing(cmd, **kw):
        raise FileNotFoundError("systemctl")

    assert not power_action("restart", missing)[0]


def test_main_window_power_actions(qtbot, monkeypatch):
    window = MainWindow(configured(), lambda c: None, FakeUnlocker)
    qtbot.addWidget(window)
    window.show()
    window.show_shell()
    ran = []
    monkeypatch.setattr(window, "power_runner", lambda kind: ran.append(kind) or (False, "Access denied"))
    window.shell.open_power_menu()
    window.shell.power_menu.shutdown_button.click()
    assert ran == ["shutdown"]
    assert "Access denied" in window.shell.power_menu.status.text()
    assert window.nav_root() is window.shell.power_menu  # controller stays in the menu
    closed = []
    monkeypatch.setattr(window, "close", lambda: closed.append(1))
    window.shell.exit_requested.disconnect()
    window.shell.exit_requested.connect(window.close)
    window.shell.power_menu.desktop_button.click()
    assert closed == [1]


def test_main_window_first_start_shows_setup(qtbot):
    window = MainWindow(copy.deepcopy(DEFAULTS), lambda c: None, FakeUnlocker)
    qtbot.addWidget(window)
    assert window.screen_name == "setup"
    assert isinstance(window.stack.currentWidget(), AuthSetupWizard)
    window.stack.currentWidget().cancel_button.click()
    assert window.screen_name == "shell"


def test_main_window_setup_then_lock_then_shell(qtbot):
    saved = []
    window = MainWindow(copy.deepcopy(DEFAULTS), saved.append, FakeUnlocker)
    qtbot.addWidget(window)
    wizard = window.stack.currentWidget()
    wizard.submit_volume("/v.vc", "")
    wizard.submit_current("1234")
    wizard.choose_method("pin")
    wizard.submit_new("5555")
    wizard.submit_confirm("5555")
    qtbot.waitUntil(lambda: window.screen_name == "lock")
    assert isinstance(window.stack.currentWidget(), LockScreen)
    assert saved and saved[-1]["unlock"]["method"] == "pin"


def test_main_window_configured_unlock_to_shell(qtbot):
    window = MainWindow(configured(), lambda c: None, FakeUnlocker)
    qtbot.addWidget(window)
    assert window.screen_name == "lock"
    lock = window.stack.currentWidget()
    for key in "1234✓":
        lock.input.widget.press(key)
    qtbot.waitUntil(lambda: window.screen_name == "shell")
    assert isinstance(window.shell.pages["Settings"], SettingsTab)


def test_settings_reset_authentication(qtbot):
    cfg = configured()
    saved = []
    tab = SettingsTab(cfg, saved.append, FakeUnlocker)
    qtbot.addWidget(tab)
    assert "PIN" in tab.method_label.text()
    assert "/dev/sdb1" in tab.volume_label.text()
    tab.reset_button.click()
    wizard = tab.wizard
    assert tab.currentWidget() is wizard and not wizard.first_start
    assert wizard.input_page.method == "pin"
    wizard.submit_current("1234")
    wizard.choose_method("pattern")
    wizard.submit_new("14789")
    wizard.submit_confirm("14789")
    qtbot.waitUntil(lambda: tab.currentWidget() is tab.overview)
    assert "Swipe pattern" in tab.method_label.text()
    assert "changed" in tab.status.text()
    assert saved[-1]["unlock"]["method"] == "pattern"


def test_settings_reset_cancel(qtbot):
    tab = SettingsTab(configured(), lambda c: None, FakeUnlocker)
    qtbot.addWidget(tab)
    tab.reset_button.click()
    tab.wizard.cancel_button.click()
    assert tab.currentWidget() is tab.overview and tab.wizard is None


def test_settings_reset_without_volume_asks_for_volume(qtbot):
    tab = SettingsTab(copy.deepcopy(DEFAULTS), lambda c: None, FakeUnlocker)
    qtbot.addWidget(tab)
    tab.reset_button.click()
    assert tab.wizard.step == "source"


def test_settings_shows_kdf(qtbot):
    cfg = configured()
    tab = SettingsTab(cfg, lambda c: None, FakeUnlocker)
    qtbot.addWidget(tab)
    assert "legacy" in tab.kdf_label.text()
    cfg["unlock"]["kdf"] = {"algorithm": "scrypt", "salt": "aa" * 16, "n": 2**18, "r": 8, "p": 1}
    tab.refresh()
    assert "scrypt" in tab.kdf_label.text() and "Back up" in tab.kdf_label.text()


def test_volume_password_recovery(tmp_path):
    import json

    from gamingcrypt.app import main, print_volume_password
    from gamingcrypt.unlock import kdf

    params = {"algorithm": "scrypt", "salt": "aa" * 16, "n": 1024, "r": 8, "p": 1}
    cfg = configured()
    cfg["unlock"]["kdf"] = params
    lines = []
    assert print_volume_password(cfg, read_secret=lambda: "1234", out=lines.append) == 0
    assert lines == [kdf.derive_password("1234", params)]
    cfg["unlock"]["kdf"] = {"algorithm": "nope"}
    assert print_volume_password(cfg, read_secret=lambda: "1234", out=lines.append) == 1

    path = tmp_path / "config.json"
    path.write_text(json.dumps({"unlock": {"method": "pin", "kdf": params}}))
    import getpass
    orig = getpass.getpass
    getpass.getpass = lambda prompt: "1234"
    try:
        assert main(["--config", str(path), "--volume-password"]) == 0
    finally:
        getpass.getpass = orig


def test_default_pages_pass_mount_point_to_games(monkeypatch):
    from gamingcrypt import app
    from gamingcrypt.ui import games_tab

    seen = {}

    class Probe:
        def __init__(self, service, library_path=""):
            seen["path"] = library_path

    monkeypatch.setattr(games_tab, "GamesTab", Probe)
    cfg = configured()
    cfg["unlock"]["mount_point"] = "~/GamingCrypt"
    app.default_pages(cfg)
    assert seen["path"].endswith("/GamingCrypt") and not seen["path"].startswith("~")
    cfg["steam"]["auto_library"] = False
    app.default_pages(cfg)
    assert seen["path"] == ""
