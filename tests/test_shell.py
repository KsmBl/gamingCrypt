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

    def change_password(self, current, new):
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
    for name in ["Movies", "Series", "Music", "Pictures"]:
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


def test_exit_needs_two_taps(qtbot):
    shell = Shell()
    qtbot.addWidget(shell)
    exits = []
    shell.exit_requested.connect(lambda: exits.append(1))
    shell.exit_button.click()
    assert exits == [] and "again" in shell.exit_button.text()
    shell.exit_button.click()
    assert exits == [1]


def test_exit_disarms(qtbot):
    shell = Shell()
    qtbot.addWidget(shell)
    shell.exit_button.click()
    shell._disarm_exit()
    assert shell.exit_button.text() == "⏻"


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
    assert "Pattern" in tab.method_label.text()
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
    assert tab.wizard.step == "volume"
