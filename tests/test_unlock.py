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
