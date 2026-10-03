import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "install.sh"


def run(*args, home: Path, timeout=600):
    env = {"PATH": os.environ["PATH"], "HOME": str(home)}
    return subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, env=env, timeout=timeout)


def test_syntax():
    assert subprocess.run(["bash", "-n", str(SCRIPT)]).returncode == 0


def test_help(tmp_path):
    result = run("--help", home=tmp_path)
    assert result.returncode == 0
    assert "--uninstall" in result.stdout and "--autostart" in result.stdout


def test_unknown_option(tmp_path):
    result = run("--bogus", home=tmp_path)
    assert result.returncode != 0
    assert "unknown option" in result.stderr


@pytest.mark.skipif(os.path.exists("/usr/local/lib/gamingcrypt/veracrypt-helper"),
                    reason="would remove the real system helper via sudo")
def test_uninstall_on_clean_home(tmp_path):
    result = run("--uninstall", home=tmp_path)
    assert result.returncode == 0
    assert "kept" in result.stdout


@pytest.mark.skipif(not os.environ.get("RUN_INSTALL_TEST"), reason="set RUN_INSTALL_TEST=1 (needs network, slow)")
def test_full_user_install_and_uninstall(tmp_path):
    result = run("--no-sudo", "--autostart", home=tmp_path)
    assert result.returncode == 0, result.stderr
    launcher = tmp_path / ".local/bin/gamingcrypt"
    assert launcher.exists()
    assert (tmp_path / ".config/autostart/gamingcrypt.desktop").exists()
    venv_python = tmp_path / ".local/share/gamingcrypt/venv/bin/python"
    check = subprocess.run([str(venv_python), "-c", "import gamingcrypt.app"], capture_output=True)
    assert check.returncode == 0
    if not os.path.exists("/usr/local/lib/gamingcrypt/veracrypt-helper"):
        assert run("--uninstall", home=tmp_path).returncode == 0
        assert not launcher.exists()
