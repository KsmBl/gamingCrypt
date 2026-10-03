import subprocess

import pytest

from gamingcrypt.unlock import secrets
from gamingcrypt.unlock.veracrypt import VeraCryptUnlocker, explain_error


# --- secrets -----------------------------------------------------------------

def test_pin_valid():
    assert secrets.pin_to_secret("1234") == "1234"


@pytest.mark.parametrize("pin", ["123", "12a4", "", "12 34"])
def test_pin_invalid(pin):
    with pytest.raises(secrets.InvalidSecret):
        secrets.pin_to_secret(pin)


def test_password():
    assert secrets.password_to_secret("hunter2 !") == "hunter2 !"
    with pytest.raises(secrets.InvalidSecret):
        secrets.password_to_secret("")


def test_pattern_l_shape():
    assert secrets.pattern_to_secret([0, 3, 6, 7, 8]) == "14789"


@pytest.mark.parametrize("nodes", [[0, 1, 2], [0, 1, 1, 2], [0, 1, 2, 9], [-1, 0, 1, 2]])
def test_pattern_invalid(nodes):
    with pytest.raises(secrets.InvalidSecret):
        secrets.pattern_to_secret(nodes)


# --- veracrypt ---------------------------------------------------------------

class FakeRunner:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, cmd, **kwargs):
        self.calls.append((cmd, kwargs))
        resp = self.responses.pop(0)
        if isinstance(resp, Exception):
            raise resp
        rc, out, err = resp
        return subprocess.CompletedProcess(cmd, rc, out, err)


NOT_MOUNTED = (1, "", "Error: No such volume is mounted.")


def make(runner, **kw):
    return VeraCryptUnlocker(volume="/dev/sdb1", mount_point="/mnt/games", runner=runner, **kw)


def test_mount_command_uses_stdin_and_sudo():
    u = make(FakeRunner([]))
    cmd = u.mount_command()
    assert cmd[:3] == ["sudo", "-n", "veracrypt"]
    assert "--stdin" in cmd and "--non-interactive" in cmd
    assert cmd[-2:] == ["/dev/sdb1", "/mnt/games"]
    assert not any("1234" in part for part in cmd)


def test_mount_command_without_sudo_and_mountpoint():
    u = VeraCryptUnlocker(volume="/x.vc", use_sudo=False, keyfiles=["/a", "/b"], pim=5)
    cmd = u.mount_command()
    assert cmd[0] == "veracrypt"
    assert cmd[-1] == "/x.vc"
    assert "--keyfiles=/a,/b" in cmd and "--pim=5" in cmd


def test_unlock_success_passes_secret_via_stdin():
    runner = FakeRunner([NOT_MOUNTED, (0, "", "")])
    result = make(runner).unlock("1234")
    assert result.success
    _, kwargs = runner.calls[1]
    assert kwargs["input"] == "1234\n"


def test_unlock_wrong_password():
    runner = FakeRunner([NOT_MOUNTED, (1, "", "Error: Incorrect password or not a VeraCrypt volume.")])
    result = make(runner).unlock("0000")
    assert not result.success
    assert "Wrong code" in result.message


def test_unlock_already_mounted_skips_mount():
    runner = FakeRunner([(0, "1: /dev/sdb1 /dev/mapper/veracrypt1 /mnt/games", "")])
    result = make(runner).unlock("1234")
    assert result.success
    assert len(runner.calls) == 1


def test_unlock_not_configured():
    result = VeraCryptUnlocker(volume="").unlock("1234")
    assert not result.success


def test_unlock_binary_missing():
    runner = FakeRunner([NOT_MOUNTED, FileNotFoundError()])
    assert "not found" in make(runner).unlock("1234").message


def test_unlock_timeout():
    runner = FakeRunner([NOT_MOUNTED, subprocess.TimeoutExpired("veracrypt", 1)])
    assert "timed out" in make(runner).unlock("1234").message


def test_error_in_output_with_rc_zero_is_failure():
    runner = FakeRunner([NOT_MOUNTED, (0, "", "Error: Failed to obtain administrator privileges.")])
    result = make(runner).unlock("1234")
    assert not result.success
    assert "install.sh" in result.message


def test_from_config():
    u = VeraCryptUnlocker.from_config({"volume": "/v", "use_sudo": False, "pim": "7"})
    assert u.volume == "/v" and u.use_sudo is False and u.pim == 7


def test_explain_error_fallback():
    assert explain_error("foo\nbar baz\n") == "bar baz"
    assert explain_error("") == "Unlocking failed"


def test_change_password_command_reads_current_from_stdin():
    runner = FakeRunner([(0, "Password, PIM and/or keyfile(s) successfully changed.", "")])
    result = make(runner).change_password("1234", "14789")
    assert result.success
    cmd, kwargs = runner.calls[0]
    assert kwargs["input"] == "1234\n"
    assert "--new-password=14789" in cmd
    assert cmd[-2:] == ["-C", "/dev/sdb1"]
    assert not any("1234" in part for part in cmd)


def test_change_password_wrong_current():
    runner = FakeRunner([(1, "", "Error: Operation failed due to one or more of the following:\n - Incorrect password.")])
    result = make(runner).change_password("0000", "1111")
    assert not result.success and "Wrong code" in result.message


def test_change_password_same_secret_is_noop():
    runner = FakeRunner([])
    assert make(runner).change_password("1234", "1234").success
    assert runner.calls == []


# --- real VeraCrypt (container files don't need root to re-key) -------------

import shutil  # noqa: E402

needs_veracrypt = pytest.mark.skipif(shutil.which("veracrypt") is None, reason="veracrypt not installed")


@needs_veracrypt
def test_real_change_password_roundtrip(tmp_path):
    volume = tmp_path / "test.vc"
    created = subprocess.run(
        ["veracrypt", "--text", "--non-interactive", "--stdin", "--create", str(volume), "--size=2M",
         "--volume-type=normal", "--encryption=AES", "--hash=SHA-512", "--filesystem=none",
         "--pim=0", "--keyfiles=", "--random-source=/dev/urandom"],
        input="1234\n", capture_output=True, text=True, timeout=120,
    )
    assert created.returncode == 0, created.stderr
    unlocker = VeraCryptUnlocker(volume=str(volume), use_sudo=False)
    assert unlocker.change_password("1234", "14789").success
    wrong = unlocker.change_password("1234", "0000")
    assert not wrong.success and "Wrong code" in wrong.message
    assert unlocker.change_password("14789", "pass word!").success


def test_dot_grid_secret_keeps_order_and_repeats():
    assert secrets.dot_grid_to_secret([0, 6, 12, 24]) == "1-7-13-25"
    assert secrets.dot_grid_to_secret([4, 4, 0, 4]) == "5-5-1-5"
    # dashes keep 1,2 and 12 apart
    assert secrets.dot_grid_to_secret([0, 1, 0, 1]) != secrets.dot_grid_to_secret([11, 0, 1, 0])


@pytest.mark.parametrize("nodes", [[0, 1, 2], [0, 1, 2, 25], [-1, 0, 1, 2]])
def test_dot_grid_invalid(nodes):
    with pytest.raises(secrets.InvalidSecret):
        secrets.dot_grid_to_secret(nodes)


# --- container creation --------------------------------------------------------

import io  # noqa: E402


class ChunkedReader:
    """Delivers output piece by piece, like a pipe from a slowly progressing process."""

    def __init__(self, chunks):
        self.chunks = list(chunks)

    def read(self, _n):
        return self.chunks.pop(0) if self.chunks else ""


class FakePopen:
    def __init__(self, output, returncode=0):
        self.output = output if isinstance(output, list) else [output]
        self.returncode = returncode
        self.cmd = None
        self.stdin = io.StringIO()

    def __call__(self, cmd, **kwargs):
        self.cmd = cmd
        self.stdout = ChunkedReader(self.output)
        self.stdin.close = lambda: None
        return self

    def wait(self, timeout=None):
        return self.returncode

    def poll(self):
        return self.returncode

    def terminate(self):
        pass


def test_create_command():
    u = VeraCryptUnlocker(volume="", use_sudo=False)
    cmd = u.create_command("/home/a/g.vc", 64)
    assert cmd[:2] == ["veracrypt", "--text"]
    assert "--create" in cmd and "/home/a/g.vc" in cmd
    assert "--size=64G" in cmd and "--filesystem=ext4" in cmd and "--quick" in cmd
    assert "--quick" not in u.create_command("/x", 1, quick=False)


def test_create_volume_reports_progress_and_sends_secret():
    out = ["Done:   0.000%  Speed: x\r", "Done:  42.500%  Speed: y\r",
           "Done: 100.000%\n\nThe VeraCrypt volume has been successfully created.\n"]
    popen = FakePopen(out)
    seen = []
    result = VeraCryptUnlocker(volume="", use_sudo=False).create_volume("/x.vc", 2, "s3cret", progress=seen.append, popen=popen)
    assert result.success
    assert popen.stdin.getvalue() == "s3cret\n"
    assert 42.5 in seen and seen[-1] == 100.0
    assert not any("s3cret" in part for part in popen.cmd)


def test_create_volume_failure_messages():
    u = VeraCryptUnlocker(volume="", use_sudo=False)
    r = u.create_volume("/x.vc", 2, "s", popen=FakePopen("Error: Failed to obtain administrator privileges.\n", 1))
    assert not r.success and "install.sh" in r.message
    r = u.create_volume("/x.vc", 2, "s", popen=FakePopen("Error: helper: the container file already exists\n", 2))
    assert "already exists" in r.message


def test_create_volume_missing_binary():
    def boom(cmd, **kw):
        raise FileNotFoundError

    r = VeraCryptUnlocker(volume="", use_sudo=False).create_volume("/x.vc", 2, "s", popen=boom)
    assert not r.success and "not found" in r.message


def test_unlock_creates_mount_point(tmp_path):
    runner = FakeRunner([NOT_MOUNTED, (0, "", "")])
    target = tmp_path / "GamingCrypt"
    VeraCryptUnlocker(volume="/v", mount_point=str(target), runner=runner).unlock("x")
    assert target.is_dir()


def test_from_config_expands_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    u = VeraCryptUnlocker.from_config({"volume": "~/g.vc", "mount_point": "~/Games"})
    assert u.volume == str(tmp_path / "g.vc") and u.mount_point == str(tmp_path / "Games")


@needs_veracrypt
def test_real_create_volume(tmp_path):
    # ext4 needs root; without a filesystem it works as a normal user
    path = tmp_path / "new.vc"
    seen = []
    u = VeraCryptUnlocker(volume=str(path), use_sudo=False)
    # sizes are whole GB in the app; shrink to 2 MB for the test
    u.create_command = lambda p, s, q=True, f="ext4": [
        "--size=2M" if a.startswith("--size=") else a
        for a in VeraCryptUnlocker.create_command(u, p, s, q, "none")
    ]
    result = u.create_volume(str(path), 1, "first", progress=seen.append)
    assert result.success, result.message
    assert path.stat().st_size == 2 * 1024 * 1024
    assert seen[-1] == 100.0
    assert u.change_password("first", "second").success


# --- KDF integration -----------------------------------------------------------

from gamingcrypt.unlock import kdf  # noqa: E402

FAST_KDF = {"algorithm": "scrypt", "salt": "ab" * 16, "n": 1024, "r": 8, "p": 1}


def test_unlock_sends_derived_password():
    runner = FakeRunner([NOT_MOUNTED, (0, "", "")])
    u = VeraCryptUnlocker(volume="/v", runner=runner, kdf=FAST_KDF)
    assert u.unlock("1234").success
    sent = runner.calls[1][1]["input"]
    assert sent == kdf.derive_password("1234", FAST_KDF) + "\n"
    assert "1234" not in sent


def test_change_password_derives_both_sides():
    new_kdf = dict(FAST_KDF, salt="cd" * 16)
    runner = FakeRunner([(0, "", "")])
    u = VeraCryptUnlocker(volume="/v", runner=runner, kdf=FAST_KDF)
    assert u.change_password("1234", "1234", new_kdf).success  # same secret, new salt -> real change
    cmd, kwargs = runner.calls[0]
    assert kwargs["input"] == kdf.derive_password("1234", FAST_KDF) + "\n"
    assert f"--new-password={kdf.derive_password('1234', new_kdf)}" in cmd


def test_broken_kdf_config_is_reported():
    u = VeraCryptUnlocker(volume="/v", runner=FakeRunner([NOT_MOUNTED]), kdf={"algorithm": "rot13"})
    result = u.unlock("1234")
    assert not result.success and "unsupported" in result.message


def test_from_config_reads_kdf():
    assert VeraCryptUnlocker.from_config({"volume": "/v", "kdf": FAST_KDF}).kdf == FAST_KDF
    assert VeraCryptUnlocker.from_config({"volume": "/v"}).kdf is None


@needs_veracrypt
def test_real_kdf_protected_volume(tmp_path):
    """Create with KDF, re-key to a new salt, and check that the plain PIN no longer works."""
    path = tmp_path / "kdf.vc"
    u = VeraCryptUnlocker(volume=str(path), use_sudo=False, kdf=FAST_KDF)
    u.create_command = lambda p, s, q=True, f="ext4": [
        "--size=2M" if a.startswith("--size=") else a
        for a in VeraCryptUnlocker.create_command(u, p, s, q, "none")
    ]
    assert u.create_volume(str(path), 1, "1234").success
    plain = VeraCryptUnlocker(volume=str(path), use_sudo=False)
    assert not plain.change_password("1234", "x").success  # raw PIN is not the password
    new_kdf = dict(FAST_KDF, salt="ef" * 16)
    assert u.change_password("1234", "5678", new_kdf).success
    u2 = VeraCryptUnlocker(volume=str(path), use_sudo=False, kdf=new_kdf)
    assert u2.change_password("5678", "5678", FAST_KDF).success


def test_create_volume_refuses_existing_file(tmp_path):
    (tmp_path / "x.vc").write_text("")
    r = VeraCryptUnlocker(volume="", use_sudo=False).create_volume(str(tmp_path / "x.vc"), 1, "s", popen=FakePopen(""))
    assert not r.success and "already exists" in r.message


def test_create_volume_cancelled_removes_partial_file(tmp_path):
    import threading

    target = tmp_path / "x.vc"

    class Writing(FakePopen):
        def __call__(self, cmd, **kw):
            target.write_text("partial")
            return super().__call__(cmd, **kw)

    cancel = threading.Event()
    cancel.set()
    r = VeraCryptUnlocker(volume="", use_sudo=False).create_volume(
        str(target), 1, "s", popen=Writing(["Done: 10.0%\r"], returncode=143), cancel=cancel)
    assert r.cancelled and not r.success and "cancelled" in r.message
    assert not target.exists()


@needs_veracrypt
def test_real_create_cancel(tmp_path):
    import threading

    path = tmp_path / "big.vc"
    u = VeraCryptUnlocker(volume=str(path), use_sudo=False)
    # full (non-quick) format of 2 GB takes long enough to cancel in the middle
    u.create_command = lambda p, s, q=True, f="ext4": VeraCryptUnlocker.create_command(u, p, s, False, "none")
    cancel = threading.Event()
    seen = []

    def progress(value):
        seen.append(value)
        cancel.set()

    result = u.create_volume(str(path), 2, "pw", progress=progress, cancel=cancel)
    assert result.cancelled
    assert not path.exists()
    assert seen and seen[0] < 100
