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
    (["--text", "--create", "/v"], "not allowed"),
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
