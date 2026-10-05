"""An outdated root helper (in-app updates can't replace it) is detected, and the update
can be finished with the password - the old one broke the SMB share."""

import subprocess
from pathlib import Path

from gamingcrypt.emulation.sharing import SmbShare
from gamingcrypt.helper import veracrypt_helper as helper
from gamingcrypt.system import helper_status
from gamingcrypt.system.updater import finish_install


def test_helper_reports_its_version(capsys):
    assert helper.main(["version"]) == 0
    assert capsys.readouterr().out.strip() == str(helper.HELPER_VERSION)


def runner_for(stdout="", code=0, stderr=""):
    return lambda cmd, **kw: subprocess.CompletedProcess(cmd, code, stdout, stderr)


def test_versions():
    yes = lambda p: True  # noqa: E731
    assert helper_status.installed_version("/h", runner_for(f"{helper.HELPER_VERSION}\n"), yes) == helper.HELPER_VERSION
    old = runner_for("", 2, "Error: gamingcrypt helper: exactly one of --mount, --list, -C, --create is required")
    assert helper_status.installed_version("/h", old, yes) == 1  # from before versions: treats it as veracrypt args
    assert helper_status.outdated("/h", old, yes)
    assert helper_status.outdated("/h", runner_for("", 1, "sudo: a password is required"), yes)
    assert helper_status.installed_version("/h", runner_for("2"), lambda p: False) is None
    assert not helper_status.outdated("/h", runner_for(f"{helper.HELPER_VERSION}"), yes)


def test_share_explains_an_old_helper():
    old = runner_for("", 2, "Error: gamingcrypt helper: exactly one of --mount, --list, -C, --create is required")
    ok, message = SmbShare(helper="/h", runner=old, exists=lambda p: True).start("/x")
    assert not ok and message == helper_status.OUTDATED


def test_finish_install_with_the_password(tmp_path):
    source = tmp_path / "src"
    source.mkdir()
    seen = {}

    def run(cmd, **kw):
        env = kw["env"]
        askpass = Path(env["SUDO_ASKPASS"])
        seen.setdefault("password", subprocess.run([str(askpass)], capture_output=True, text=True).stdout)
        seen.setdefault("wrapper", (Path(env["PATH"].split(":")[0]) / "sudo").read_text())
        seen.setdefault("mode", oct(askpass.parent.stat().st_mode & 0o777))
        seen.setdefault("folder", askpass.parent)
        seen.setdefault("calls", []).append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    ok, message = finish_install(source, "hunter22", run, which=lambda t: "/usr/bin/sudo")
    assert ok and message == "Update finished"
    assert seen["password"] == "hunter22\n" and "/usr/bin/sudo\" -A" in seen["wrapper"]
    assert seen["mode"] == "0o700"
    assert seen["calls"] == [["/usr/bin/sudo", "-A", "-k", "-v"], [str(source / "install.sh")]]
    assert not seen["folder"].exists()  # the password file is gone right after


def test_finish_install_wrong_password(tmp_path):
    calls = []
    run = lambda cmd, **kw: calls.append(cmd) or subprocess.CompletedProcess(cmd, 1, "", "Sorry")  # noqa: E731
    assert finish_install(tmp_path, "nope", run, which=lambda t: "/usr/bin/sudo") == (False, "Wrong password")
    assert len(calls) == 1  # install.sh never ran
    assert finish_install(None, "x", run)[0] is False


def test_updates_page_asks_when_the_helper_is_old(qtbot):
    from gamingcrypt.system.updater import UpdateInfo
    from gamingcrypt.ui.updates_page import UpdatesPage
    from tests.test_updater import FakeUpdater

    page = UpdatesPage(FakeUpdater(UpdateInfo(True, 0, [], "Up to date")), helper_outdated=lambda: True,
                       finisher=lambda source, pw: (False, "Wrong password"))
    qtbot.addWidget(page)
    page.show()
    page.check()
    qtbot.waitUntil(lambda: page.finish_box.isVisible())  # nothing to pull, but the helper is old
    page.password.setText("bad")
    page.finish_button.click()
    qtbot.waitUntil(lambda: "Wrong password" in page.status.text())
    assert page.finish_box.isVisible()


def test_health_names_an_old_helper():
    from gamingcrypt.system.health import Health

    def run(cmd, **kw):
        if cmd[-1] == "version":
            return subprocess.CompletedProcess(cmd, 2, "", "Error: exactly one of --mount ...")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    check = Health(runner=run, exists=lambda p: True, helper="/h").helper_allowed()
    assert not check.ok and "outdated" in check.detail and "Settings → Updates" in check.fix
