"""Settings -> Services: SSH on / off, and the whole drive as a permanent network share that
runs next to the upload pages' temporary share in one Samba without breaking it."""

import os
import re
import signal
import subprocess

import pytest

from gamingcrypt.emulation import sharing
from gamingcrypt.emulation.sharing import DriveShare, SmbShare
from gamingcrypt.helper import veracrypt_helper as helper
from gamingcrypt.system.ssh import Ssh, SshState


@pytest.fixture(autouse=True)
def no_drive_share(monkeypatch):
    monkeypatch.setitem(sharing._drive, "password", "")


@pytest.fixture
def samba(monkeypatch):
    monkeypatch.setitem(helper.SMB_TOOLS, "smbd", ["/bin/true"])
    monkeypatch.setitem(helper.SMB_TOOLS, "smbpasswd", ["/bin/true"])


class FakeSmbd:
    """smbd as the helper sees it: started by `smbd -D` (writes its pid file), signals."""

    def __init__(self, run_dir):
        self.run_dir, self.pid, self.alive, self.signals, self.calls = run_dir, 4000, set(), [], []

    def run(self, cmd, **kw):
        self.calls.append((cmd, kw.get("input")))
        if cmd[-1] == "-D":
            self.pid += 1
            self.alive.add(self.pid)
            with open(os.path.join(self.run_dir, "smbd.pid"), "w") as fh:
                fh.write(str(self.pid))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    def kill(self, pid, sig):
        if pid not in self.alive:
            raise ProcessLookupError
        if sig:
            self.signals.append((pid, sig))
        if sig == signal.SIGTERM:
            self.alive.discard(pid)

    def conf(self):
        with open(os.path.join(self.run_dir, "smb.conf")) as fh:
            return fh.read()


@pytest.fixture
def drive(tmp_path):
    home = tmp_path / "home"
    folder = home / "GamingCrypt"
    (folder / "Emulation").mkdir(parents=True)
    return home, folder


def start(smbd, key, folder, home, password="MapleOtterSwan"):
    return helper.smb_start([str(folder)], password, str(home), "deck", smbd.run, smbd.run_dir, key=key,
                            uid=os.getuid(), kill=smbd.kill)


# --- helper: one Samba, two shares --------------------------------------------------------------

def test_both_shares_run_in_one_samba(tmp_path, samba, drive):
    home, folder = drive
    smbd = FakeSmbd(str(tmp_path / "run"))
    assert start(smbd, "drive", folder, home) == 0
    assert smbd.alive == {4001}
    assert start(smbd, "temp", folder / "Emulation", home) == 0
    assert smbd.alive == {4001} and smbd.signals == [(4001, signal.SIGHUP)]  # reloaded, not restarted
    conf = smbd.conf()
    assert f"[GamingCrypt-Drive]\npath = {folder}\n" in conf and f"[GamingCrypt]\npath = {folder}/Emulation\n" in conf
    # leaving the upload page: the drive share keeps running in the same smbd
    assert helper.smb_unshare("temp", smbd.run, smbd.run_dir, smbd.kill) == 0
    assert smbd.alive == {4001} and smbd.signals[-1] == (4001, signal.SIGHUP)
    assert "[GamingCrypt]\n" not in smbd.conf() and "[GamingCrypt-Drive]" in smbd.conf()
    assert "valid users = deck" in smbd.conf()
    # the last share ends Samba
    assert helper.smb_unshare("drive", smbd.run, smbd.run_dir, smbd.kill) == 0
    assert smbd.alive == set() and not (tmp_path / "run").exists()


def test_removing_the_drive_share_restarts_samba(tmp_path, samba, drive):
    """Before locking: no connection may keep the drive busy - the temporary share goes on."""
    home, folder = drive
    smbd = FakeSmbd(str(tmp_path / "run"))
    start(smbd, "temp", folder / "Emulation", home)
    start(smbd, "drive", folder, home)
    assert helper.smb_unshare("drive", smbd.run, smbd.run_dir, smbd.kill) == 0
    assert (4001, signal.SIGTERM) in smbd.signals and smbd.alive == {4002}
    assert "[GamingCrypt-Drive]" not in smbd.conf() and "[GamingCrypt]\n" in smbd.conf()


def test_a_dead_smbd_starts_fresh(tmp_path, samba, drive):
    home, folder = drive
    smbd = FakeSmbd(str(tmp_path / "run"))
    start(smbd, "drive", folder, home)
    smbd.alive.clear()  # crashed
    assert start(smbd, "temp", folder / "Emulation", home) == 0
    assert "[GamingCrypt-Drive]" not in smbd.conf() and smbd.alive == {4002}


def test_stopping_what_never_ran(tmp_path):
    smbd = FakeSmbd(str(tmp_path / "run"))
    assert helper.smb_unshare("drive", smbd.run, smbd.run_dir, smbd.kill) == 0
    assert smbd.calls == []


def test_password_goes_to_samba_on_stdin(tmp_path, samba, drive):
    home, folder = drive
    smbd = FakeSmbd(str(tmp_path / "run"))
    start(smbd, "drive", folder, home, "MapleOtterSwan")
    cmd, given = smbd.calls[0]
    assert "-a" in cmd and given == "MapleOtterSwan\nMapleOtterSwan\n"
    assert all("MapleOtterSwan" not in part for part in cmd)
    assert start(smbd, "drive", folder, home, "short") == 2


def test_which_folders_may_be_shared(tmp_path, monkeypatch):
    home = str(tmp_path / "home")
    os.makedirs(home + "/GamingCrypt")
    mine = os.getuid()
    assert helper.share_folder_ok("drive", home + "/GamingCrypt", home, mine) is None
    assert helper.share_folder_ok("temp", home + "/GamingCrypt", home, mine) is None
    assert "only your own" in helper.share_folder_ok("drive", home + "/GamingCrypt", home, mine + 1)
    assert "inside your home" in helper.share_folder_ok("temp", "/etc", home, mine)
    assert "/mnt" in helper.share_folder_ok("drive", "/etc", home, mine)
    assert helper.share_folder_ok("drive", home + "/x\ny", home, mine) == "bad folder name"
    assert "isn't there" in helper.share_folder_ok("drive", home + "/gone", home, mine)
    # a drive mounted below /mnt, if it's yours (a container's ext4 is handed to its user)
    mnt = tmp_path / "mnt"
    (mnt / "games").mkdir(parents=True)
    monkeypatch.setattr(helper, "MOUNT_ROOTS", [str(mnt)])
    assert helper.share_folder_ok("drive", str(mnt / "games"), home, mine) is None
    assert helper.share_folder_ok("drive", str(mnt), home, mine) is not None  # not the root itself
    assert helper.share_folder_ok("temp", str(mnt / "games"), home, mine) is not None


def test_main_dispatches_the_drive_share_and_ssh(monkeypatch):
    seen = []
    monkeypatch.setattr(helper, "invoking_user", lambda: (os.getuid(), os.getgid(), "/home/deck"))
    monkeypatch.setattr(helper.sys, "stdin", type("In", (), {"readline": lambda self: "Pw12345678\n"})())
    monkeypatch.setattr(helper, "smb_start", lambda args, pw, home, name, key, uid: seen.append((args, pw, key)) or 0)
    monkeypatch.setattr(helper, "set_ssh", lambda args: seen.append(args) or 0)
    assert helper.main(["smb-drive-start", "/home/deck/GamingCrypt"]) == 0
    assert helper.main(["smb-start", "/home/deck/GamingCrypt/Emulation"]) == 0
    assert helper.main(["ssh", "on"]) == 0
    assert seen == [(["/home/deck/GamingCrypt"], "Pw12345678", "drive"),
                    (["/home/deck/GamingCrypt/Emulation"], "Pw12345678", "temp"), ["on"]]


# --- helper: SSH ----------------------------------------------------------------------------------

def test_ssh_on_and_off_through_systemctl():
    calls = []
    exists = {"/usr/lib/systemd/system/sshd.service", "/usr/bin/systemctl"}.__contains__

    def run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    assert helper.set_ssh(["on"], run, exists) == 0
    assert helper.set_ssh(["off"], run, exists) == 0
    assert calls == [["/usr/bin/systemctl", "enable", "--now", "sshd.service"],
                     ["/usr/bin/systemctl", "disable", "--now", "sshd.service"]]
    debian = {"/lib/systemd/system/ssh.service", "/bin/systemctl"}.__contains__
    assert helper.set_ssh(["on"], run, debian) == 0 and calls[-1][-1] == "ssh.service"


def test_ssh_refuses_anything_else(capsys):
    run = lambda cmd, **kw: pytest.fail("ran")  # noqa: E731
    assert helper.set_ssh(["on", "now"], run, lambda p: True) == 2
    assert helper.set_ssh(["restart"], run, lambda p: True) == 2
    assert helper.set_ssh(["on"], run, lambda p: False) == 2
    assert "OpenSSH is not installed" in capsys.readouterr().err


# --- clients --------------------------------------------------------------------------------------

def helper_runner(calls, code=0, stderr=""):
    def run(cmd, **kw):
        if cmd[-1] == "version":
            return subprocess.CompletedProcess(cmd, 0, f"{helper.HELPER_VERSION}\n", "")
        calls.append((cmd, kw.get("input")))
        return subprocess.CompletedProcess(cmd, code, "", stderr)
    return run


def test_temporary_share_uses_the_drive_share_password():
    """Samba keeps one password per user: a new one would lock the drive share's users out."""
    calls = []
    run = helper_runner(calls)
    drive = DriveShare(helper="/h", runner=run, exists=lambda p: True, user="deck")
    assert drive.start("/home/deck/GamingCrypt", "MapleOtterSwan") == (True, "")
    assert calls[0] == (["sudo", "-n", "/h", "smb-drive-start", "/home/deck/GamingCrypt"], "MapleOtterSwan\n")
    temp = SmbShare(helper="/h", runner=run, exists=lambda p: True, user="deck")
    assert temp.start("/home/deck/GamingCrypt/Emulation")[0]
    assert temp.password == "MapleOtterSwan" and calls[1][1] == "MapleOtterSwan\n"
    temp.stop()
    drive.stop()
    assert [c[0][-1] for c in calls[2:]] == ["smb-stop", "smb-drive-stop"]
    assert sharing.drive_share_password() == ""
    assert temp.start("/x")[0] and re.fullmatch(r"([A-Z][a-z]+){2}", temp.password)  # its own again


def test_failed_drive_share_keeps_no_password():
    drive = DriveShare(helper="/h", runner=helper_runner([], 2, "Error: gamingcrypt helper: the drive isn't there"),
                       exists=lambda p: True)
    assert drive.start("/x", "MapleOtterSwan") == (False, "the drive isn't there")
    assert not drive.running and sharing.drive_share_password() == ""


def test_forced_stop_before_locking():
    calls = []
    DriveShare(helper="/h", runner=helper_runner(calls), exists=lambda p: True).stop(force=True)
    assert calls[0][0][-1] == "smb-drive-stop"


def test_ssh_state_and_switching():
    calls = []
    unit = "/usr/lib/systemd/system/sshd.service"

    def run(cmd, **kw):
        calls.append(cmd)
        if cmd[-1] == "version":
            return subprocess.CompletedProcess(cmd, 0, f"{helper.HELPER_VERSION}\n", "")
        return subprocess.CompletedProcess(cmd, 0 if cmd[1] == "is-enabled" or cmd[-1] == "on" else 3, "", "")

    ssh = Ssh(helper="/h", runner=run, exists=lambda p: p in (unit, "/h"))
    assert ssh.state() == SshState(True, enabled=True, active=False)
    assert ["systemctl", "is-active", "sshd.service"] in calls
    assert ssh.set(True) == (True, "")
    assert calls[-1] == ["sudo", "-n", "/h", "ssh", "on"]
    assert Ssh(helper="/h", runner=run, exists=lambda p: False).state() == SshState(False)
    assert Ssh(helper="/h", runner=run, exists=lambda p: p == unit).set(True)[1].startswith("Run ./install.sh")


# --- the page -------------------------------------------------------------------------------------

class FakeShare:
    STOP = "smb-drive-stop"

    def __init__(self, ok=True):
        self.ok, self.user, self.password, self.running, self.calls = ok, "deck", "", False, []

    def start(self, folder, password=None):
        self.calls.append(("start", folder, password))
        if not self.ok:
            return False, "Samba is not installed (run ./install.sh)"
        self.password, self.running = password, True
        return True, ""

    def stop(self, force=False):
        self.calls.append(("stop",))
        self.running = False


class FakeSsh:
    def __init__(self, state=SshState(True)):
        self.current, self.calls = state, []

    def state(self):
        return self.current

    def set(self, on):
        self.calls.append(on)
        self.current = SshState(True, on, on)
        return True, ""


def page_for(qtbot, config=None, share=None, ssh=None, mounted=True):
    from gamingcrypt.ui.services_page import ServicesPage

    config = config if config is not None else {"unlock": {"mount_point": "/home/deck/GamingCrypt"}}
    saved = []
    page = ServicesPage(config, lambda c: saved.append(dict(c["services"])), ssh=ssh or FakeSsh(),
                        share=share or FakeShare(), ip=lambda: "192.168.1.50", mounted=lambda p: mounted)
    qtbot.addWidget(page)
    page.saved = saved
    return page


def test_switching_the_drive_share_on_and_off(qtbot):
    page = page_for(qtbot)
    assert not page.share_toggle.isChecked() and page.share.calls == []
    page.share_toggle.click()
    qtbot.waitUntil(lambda: page.share.running)
    qtbot.waitUntil(lambda: "Password:" in page.share_info.text())
    password = page.config["services"]["smb_password"]
    assert re.fullmatch(r"([A-Z][a-z]+){3}", password)  # three words: it's on all the time
    assert page.share.calls == [("start", "/home/deck/GamingCrypt", password)]
    assert page.config["services"]["smb_drive"] and page.saved
    assert "\\\\192.168.1.50\\GamingCrypt-Drive" in page.share_info.text() and "User: deck" in page.share_info.text()
    assert page.share_qr.qr_text == f"smb://deck:{password}@192.168.1.50/GamingCrypt-Drive"
    page.share_toggle.click()
    qtbot.waitUntil(lambda: page.share.calls[-1] == ("stop",))
    qtbot.waitUntil(lambda: page.share_info.text() == "")
    assert not page.config["services"]["smb_drive"] and page.config["services"]["smb_password"] == password
    assert not page.share_qr.isVisible()


def test_drive_share_starts_again_after_unlocking(qtbot):
    config = {"unlock": {"mount_point": "/home/deck/GamingCrypt"},
              "services": {"smb_drive": True, "smb_password": "MapleOtterSwan"}}
    page = page_for(qtbot, config)
    qtbot.waitUntil(lambda: page.share.running)
    assert page.share.calls == [("start", "/home/deck/GamingCrypt", "MapleOtterSwan")]
    assert page.share_toggle.isChecked()


def test_drive_share_needs_the_mounted_drive(qtbot):
    page = page_for(qtbot, mounted=False)
    page.share_toggle.click()
    assert page.share.calls == [] and page.share_status.property("error")
    page2 = page_for(qtbot, {"unlock": {"mount_point": ""}})
    page2.share_toggle.click()
    assert page2.share.calls == [] and "mount point" in page2.share_status.text()


def test_drive_share_that_fails_switches_back_off(qtbot):
    page = page_for(qtbot, share=FakeShare(ok=False))
    page.share_toggle.click()
    qtbot.waitUntil(lambda: "Not available" in page.share_status.text())
    assert not page.share_toggle.isChecked() and not page.config["services"]["smb_drive"]
    assert page.share_toggle.isEnabled()


def test_new_password_for_the_running_share(qtbot):
    page = page_for(qtbot)
    page.share_toggle.click()
    qtbot.waitUntil(lambda: page.share.running)
    old = page.config["services"]["smb_password"]
    page.new_password_button.click()
    new = page.config["services"]["smb_password"]
    assert new != old
    qtbot.waitUntil(lambda: page.share.calls[-1] == ("start", "/home/deck/GamingCrypt", new))
    qtbot.waitUntil(lambda: f"Password: {new}" in page.share_info.text())


def test_ssh_switch(qtbot):
    page = page_for(qtbot)
    page.refresh()
    qtbot.waitUntil(lambda: page.ssh_toggle.text() == "Off")
    page.ssh_toggle.click()
    qtbot.waitUntil(lambda: page.ssh.calls == [True])
    qtbot.waitUntil(lambda: page.ssh_info.text() == f"ssh {__import__('getpass').getuser()}@192.168.1.50")
    assert page.ssh_toggle.isChecked() and page.ssh_toggle.text() == "On"
    page.ssh_toggle.click()
    qtbot.waitUntil(lambda: page.ssh.calls == [True, False])
    qtbot.waitUntil(lambda: page.ssh_info.text() == "")


def test_ssh_not_installed(qtbot):
    page = page_for(qtbot, ssh=FakeSsh(SshState(False)))
    page.refresh()
    qtbot.waitUntil(lambda: "OpenSSH isn't installed" in page.ssh_status.text())
    assert page.ssh_toggle.isHidden()


def test_services_tab_in_settings(qtbot, monkeypatch):
    import copy

    from gamingcrypt.config import DEFAULTS
    from gamingcrypt.ui.settings_tab import SettingsTab

    cfg = copy.deepcopy(DEFAULTS)
    ssh = FakeSsh()
    tab = SettingsTab(cfg, lambda c: None, ssh=ssh, drive_share=FakeShare())
    qtbot.addWidget(tab)
    tab.sub_buttons["Network"].click()  # services are on the Network page
    assert tab.current_sub_tab == "Network" and tab.sub_pages["Network"].isAncestorOf(tab.services_page)
    qtbot.waitUntil(lambda: tab.services_page.ssh_toggle.text() == "Off")
