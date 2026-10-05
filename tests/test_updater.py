"""Updates from inside GamingCrypt (Settings -> Updates)."""

import stat
import subprocess

import pytest

from gamingcrypt.system import updater as upd
from gamingcrypt.system.updater import UpdateInfo, Updater


def git(path, *args):
    return subprocess.run(["git", "-C", str(path), "-c", "user.email=t@t", "-c", "user.name=t", *args],
                          check=True, capture_output=True, text=True).stdout


@pytest.fixture
def repos(tmp_path):
    """A "GitHub" repo and the clone GamingCrypt was installed from."""
    origin = tmp_path / "origin"
    origin.mkdir()
    git(origin, "init", "-q", "-b", "main")
    install = origin / "install.sh"
    install.write_text(f'#!/bin/sh\necho "$@" > "{tmp_path}/install-args"\n')
    install.chmod(install.stat().st_mode | stat.S_IEXEC)
    (origin / "app.py").write_text("v1\n")
    git(origin, "add", ".")
    git(origin, "commit", "-q", "-m", "first")
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(origin), str(clone)], check=True)
    return origin, clone, tmp_path


def commit(origin, path, text, message):
    (origin / path).parent.mkdir(parents=True, exist_ok=True)
    (origin / path).write_text(text)
    git(origin, "add", ".")
    git(origin, "commit", "-q", "-m", message)


def test_up_to_date(repos):
    origin, clone, _ = repos
    info = Updater(clone).check()
    assert info.ok and not info.available and info.message == "Up to date"


def test_update_available_then_applied(repos):
    origin, clone, tmp = repos
    commit(origin, "app.py", "v2\n", "Wi-Fi settings")
    commit(origin, "app.py", "v3\n", "Bluetooth settings")
    info = Updater(clone).check()
    assert info.available and info.behind == 2 and info.changes == ["Bluetooth settings", "Wi-Fi settings"]
    ok, message, root_parts = Updater(clone).apply()
    assert ok and (clone / "app.py").read_text() == "v3\n" and root_parts == []
    assert (tmp / "install-args").read_text().strip() == "--no-sudo"  # no password in the app


def test_root_parts_need_a_terminal(repos):
    origin, clone, _ = repos
    commit(origin, "gamingcrypt/helper/veracrypt_helper.py", "new helper\n", "helper: boot-next")
    ok, _message, root_parts = Updater(clone).apply()
    assert ok and root_parts == ["gamingcrypt/helper"]


def test_local_changes_block_a_pull(repos):
    origin, clone, _ = repos
    commit(origin, "app.py", "v2\n", "change")
    (clone / "app.py").write_text("my own edit\n")
    ok, message, _ = Updater(clone).apply()
    assert not ok and message.startswith("git pull failed")


def test_not_installed_from_git(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    assert upd.source_dir() is None
    (tmp_path / "gamingcrypt").mkdir()
    (tmp_path / "gamingcrypt" / "source-dir").write_text(str(tmp_path / "nowhere"))
    assert upd.source_dir() is None
    assert not Updater(None).check().ok


def test_no_network(repos):
    origin, clone, _ = repos
    git(clone, "remote", "set-url", "origin", "/does/not/exist")
    info = Updater(clone).check()
    assert not info.ok and "Could not reach" in info.message


class FakeUpdater:
    def __init__(self, info, result=(True, "Updated", [])):
        self.info, self.result, self.applied = info, result, 0

    def check(self):
        return self.info

    def apply(self):
        self.applied += 1
        return self.result


def test_updates_page(qtbot):
    from gamingcrypt.ui.updates_page import UpdatesPage

    restarted = []
    fake = FakeUpdater(UpdateInfo(True, 2, ["Wi-Fi settings", "Bluetooth settings"], "2 update(s) available"),
                       result=(True, "Updated", ["install.sh"]))
    page = UpdatesPage(fake, restart=lambda: restarted.append(1))
    qtbot.addWidget(page)
    page.show()
    assert not page.update_button.isVisible()
    page.check_button.click()
    qtbot.waitUntil(lambda: page.update_button.isVisible())
    assert page.changes.text() == "• Wi-Fi settings\n• Bluetooth settings"
    page.update_button.click()
    qtbot.waitUntil(lambda: restarted == [1])
    assert fake.applied == 1 and "./install.sh" in page.status.text()


def test_updates_page_errors(qtbot):
    from gamingcrypt.ui.updates_page import UpdatesPage

    page = UpdatesPage(FakeUpdater(UpdateInfo(False, message="Could not reach GitHub: no network?")))
    qtbot.addWidget(page)
    page.show()
    page.check()
    qtbot.waitUntil(lambda: "Could not reach" in page.status.text())
    assert page.status.property("error") is True and not page.update_button.isVisible()


def test_settings_opens_updates_and_checks(qtbot):
    import copy

    from gamingcrypt.config import DEFAULTS
    from gamingcrypt.ui.settings_tab import SettingsTab

    fake = FakeUpdater(UpdateInfo(True, 0, [], "Up to date"))
    tab = SettingsTab(copy.deepcopy(DEFAULTS), lambda c: None, updater=fake)
    qtbot.addWidget(tab)
    tab.sub_buttons["Updates"].click()
    qtbot.waitUntil(lambda: tab.updates_page.status.text() == "Up to date")


def test_startup_check_notifies(qtbot, monkeypatch):
    import copy

    from gamingcrypt.app import MainWindow
    from gamingcrypt.config import DEFAULTS

    monkeypatch.setattr(upd, "Updater", lambda: FakeUpdater(UpdateInfo(True, 3, ["a", "b", "c"], "")))
    window = MainWindow(copy.deepcopy(DEFAULTS), lambda c: None)
    qtbot.addWidget(window)
    window.show()
    window.check_for_update()
    qtbot.waitUntil(lambda: any("Update available (3 changes)" in t for t in window.toasts.shown))
