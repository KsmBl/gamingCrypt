import pytest

from gamingcrypt.helper.veracrypt_helper import mount_point_ok, validate
from gamingcrypt.unlock.veracrypt import VeraCryptUnlocker

HOME = "/home/alice"


def test_helper_accepts_what_the_unlocker_sends(tmp_path):
    u = VeraCryptUnlocker(volume="/dev/sdb1", mount_point="/mnt/games", use_sudo=False, keyfiles=["/k"], pim=3)
    assert validate(u.mount_command()[1:], HOME) is None
    assert validate(u.list_command()[1:], HOME) is None
    assert validate(u.change_password_command("new pw")[1:], HOME) is None


def test_helper_accepts_auto_mount_point():
    u = VeraCryptUnlocker(volume="/home/alice/games.vc", use_sudo=False)
    assert validate(u.mount_command()[1:], HOME) is None


@pytest.mark.parametrize("argv,needle", [
    (["--text", "--mount", "--fs-options=nosuid,nodev", "/v", "/etc"], "mount point"),
    (["--text", "--mount", "--fs-options=nosuid,nodev", "/v", "/mnt/../etc"], "mount point"),
    (["--text", "--mount", "--fs-options=nosuid,nodev", "/v", "/mnt"], "mount point"),
    (["--text", "--mount", "/v", "/mnt/x"], "nosuid"),
    (["--text", "--mount", "--fs-options=rw", "/v", "/mnt/x"], "not allowed"),
    (["--text", "--create", "/v"], "creating requires"),
    (["--text", "--filesystem=ext4", "--mount", "/v"], "not allowed"),
    (["--text", "/v"], "exactly one"),
    (["--mount", "--list", "/v"], "exactly one"),
    (["--list", "/v", "/mnt/x"], "only the volume"),
    (["--mount", "--fs-options=nosuid,nodev"], "expected a volume"),
    (["--mount", "--fs-options=nosuid,nodev", "--new-password=x", "/v"], "only allowed with -C"),
])
def test_helper_rejects(argv, needle):
    error = validate(argv, HOME)
    assert error is not None and needle in error


def test_mount_point_symlink_escape(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    (home / "link").symlink_to("/etc")
    assert not mount_point_ok(str(home / "link"), str(home))
    assert mount_point_ok(str(home / "games"), str(home))
    assert not mount_point_ok("/home/alice/x", None)
    assert not mount_point_ok("/x", "/")


def test_unlocker_uses_helper_when_installed(tmp_path):
    helper = tmp_path / "veracrypt-helper"
    u = VeraCryptUnlocker(volume="/v", sudo_helper=str(helper))
    assert u.mount_command()[:3] == ["sudo", "-n", "veracrypt"]
    helper.write_text("")
    assert u.mount_command()[:3] == ["sudo", "-n", str(helper)]
    assert "--fs-options=nosuid,nodev" in u.mount_command()


# --- create ------------------------------------------------------------------

import os  # noqa: E402
import subprocess  # noqa: E402

from gamingcrypt.helper import veracrypt_helper  # noqa: E402


def create_argv(path):
    u = VeraCryptUnlocker(volume="", use_sudo=False)
    return u.create_command(str(path), 64)[1:]


def test_create_allowed_in_own_folder(tmp_path):
    uid = os.getuid()
    assert validate(create_argv(tmp_path / "g.vc"), str(tmp_path), uid) is None


@pytest.mark.parametrize("make_path,needle", [
    (lambda t: t / "exists.vc", "already exists"),
    (lambda t: t / "missing" / "g.vc", "does not exist"),
    (lambda t: "/etc/g.vc", "below"),
    (lambda t: "/dev/null", "already exists"),
])
def test_create_rejected_targets(tmp_path, make_path, needle):
    (tmp_path / "exists.vc").write_text("")
    error = validate(create_argv(make_path(tmp_path)), str(tmp_path), os.getuid())
    assert error is not None and needle in error


def test_create_requires_folder_owned_by_user(tmp_path):
    error = validate(create_argv(tmp_path / "g.vc"), str(tmp_path), os.getuid() + 1)
    assert "belong to you" in error


def test_create_only_flags_rejected_elsewhere():
    assert "not allowed" in validate(["--mount", "--fs-options=nosuid,nodev", "--filesystem=ext4", "/v"], HOME)
    assert "not allowed" in validate(["--create", "--filesystem=ntfs", "--size=1G", "/home/alice/x"], HOME)
    assert "not allowed" in validate(["--create", "--size=99T", "--filesystem=ext4", "/home/alice/x"], HOME)


class FakeProc:
    def __init__(self, returncode=0, log=None):
        self.returncode = returncode
        self.log = log if log is not None else []

    def __call__(self, cmd, **kw):
        self.log.append(("popen", cmd))
        return self

    def communicate(self, data):
        self.log.append(("stdin", data))

    def terminate(self):
        self.log.append(("terminate",))


def test_create_volume_hands_file_and_filesystem_to_user(tmp_path):
    calls, chowns = [], []

    def run(cmd, **kw):
        calls.append((cmd, kw.get("input")))
        return subprocess.CompletedProcess(cmd, 0, "", "")

    argv = create_argv(tmp_path / "g.vc")
    proc = FakeProc()
    rc = veracrypt_helper.create_volume(argv, 1000, 1000, "pw\n", run=run, popen=proc,
                                        chown=lambda p, u, g: chowns.append((p, u, g)),
                                        mkdtemp=lambda **kw: "/run/gamingcrypt-x", rmdir=lambda p: None)
    assert rc == 0
    assert proc.log[0] == ("popen", [veracrypt_helper.VERACRYPT, *argv]) and proc.log[1] == ("stdin", "pw\n")
    assert "--mount" in calls[0][0] and calls[0][0][-1] == "/run/gamingcrypt-x" and calls[0][1] == "pw\n"
    assert "-d" in calls[1][0]
    assert chowns == [(str(tmp_path / "g.vc"), 1000, 1000), ("/run/gamingcrypt-x", 1000, 1000)]


def test_create_volume_stops_when_veracrypt_fails(tmp_path):
    rc = veracrypt_helper.create_volume(create_argv(tmp_path / "g.vc"), 1, 1, "pw\n",
                                        run=lambda *a, **k: pytest.fail("must not prepare"),
                                        popen=FakeProc(returncode=1),
                                        chown=lambda *a: pytest.fail("must not chown"))
    assert rc == 1


def test_create_volume_sigterm_stops_veracrypt_and_removes_file(tmp_path, monkeypatch):
    """Cancel: SIGTERM to the helper terminates a real child process and deletes the partial file."""
    import signal
    import threading

    target = tmp_path / "g.vc"
    target.write_text("partial")
    fake_veracrypt = tmp_path / "veracrypt"
    fake_veracrypt.write_text("#!/bin/sh\nexec sleep 30\n")
    fake_veracrypt.chmod(0o755)
    monkeypatch.setattr(veracrypt_helper, "VERACRYPT", str(fake_veracrypt))
    argv = ["--create", str(target)]
    threading.Timer(0.3, lambda: os.kill(os.getpid(), signal.SIGTERM)).start()
    rc = veracrypt_helper.create_volume(argv, os.getuid(), os.getgid(), "pw\n",
                                        run=lambda *a, **k: pytest.fail("must not prepare"))
    assert rc == 128 + signal.SIGTERM
    assert not target.exists()
    assert signal.getsignal(signal.SIGTERM) is signal.SIG_DFL  # handlers restored
