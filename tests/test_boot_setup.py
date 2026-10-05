"""install.sh's boot questions (GRUB menu wait, second OS) and what the app does
with the answer."""

import copy
import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

from gamingcrypt.system import boot

ROOT = Path(__file__).resolve().parent.parent
WINDOWS = boot.BootEntry("0000", "Windows Boot Manager", "HD(1)/\\EFI\\MICROSOFT\\BOOT\\BOOTMGFW.EFI")
FEDORA = boot.BootEntry("0005", "Fedora", "HD(1)/\\EFI\\FEDORA\\SHIMX64.EFI")


def test_chosen_systems():
    lister = lambda: [WINDOWS, FEDORA]  # noqa: E731
    assert boot.chosen_systems(None, lister) == [WINDOWS, FEDORA]  # not asked: everything found
    assert boot.chosen_systems("none", lister) == []  # no second OS: no button
    assert boot.chosen_systems("0005", lister) == [FEDORA]
    assert boot.chosen_systems("0009", lister) == []  # entry gone


def test_cli_lists_entries_and_saves_the_answer(tmp_path, monkeypatch, capsys):
    from gamingcrypt import app

    monkeypatch.setattr(boot, "other_systems", lambda: [WINDOWS])
    cfg = tmp_path / "config.json"
    assert app.main(["--config", str(cfg), "--list-boot-entries"]) == 0
    assert capsys.readouterr().out == "0000\tWindows\n"
    for value, saved in (("0000", "0000"), ("none", "none"), ("auto", None), ("00a1", "00A1")):
        assert app.main(["--config", str(cfg), "--other-os", value]) == 0
        assert json.loads(cfg.read_text())["system"]["other_os"] == saved


@pytest.mark.parametrize("choice,visible", [("none", False), ("0000", True), (None, True)])
def test_lock_screen_button_follows_the_answer(qtbot, tmp_path, choice, visible):
    from gamingcrypt.app import MainWindow
    from gamingcrypt.config import DEFAULTS
    from tests.test_shell import FakeUnlocker

    cfg = copy.deepcopy(DEFAULTS)
    volume = tmp_path / "games.vc"
    volume.write_text("")
    cfg["unlock"].update(method="pin", volume=str(volume))
    cfg["system"]["other_os"] = choice
    MainWindow.systems_lister = staticmethod(lambda: [WINDOWS])
    try:
        window = MainWindow(cfg, lambda c: None, FakeUnlocker)
        qtbot.addWidget(window)
        window.show()
        lock = window.stack.currentWidget()
        qtbot.waitUntil(lambda: getattr(window, "_other_systems", None) is not None)
        assert lock.windows_button.isVisible() is visible
    finally:
        MainWindow.systems_lister = None


# --- install.sh -------------------------------------------------------------------------

FUNCTIONS = ["interactive", "ask_yes_no", "grub_mkconfig", "ask_grub_timeout", "ask_other_os", "ask_boot_questions"]


def script_functions() -> str:
    text = (ROOT / "install.sh").read_text()
    out = []
    for name in FUNCTIONS:
        start = text.index(f"\n{name}() {{") + 1
        end = text.index("\n}\n", start) + 3
        out.append(text[start:end])
    return "\n".join(out)


@pytest.fixture
def setup(tmp_path):
    bin_dir = tmp_path / "bin"
    venv = tmp_path / "venv"
    (venv / "bin").mkdir(parents=True)
    bin_dir.mkdir()
    calls = tmp_path / "calls"
    python = venv / "bin" / "python"
    python.write_text(f"""#!/bin/sh
case "$*" in
  -c*) cat "{tmp_path}/current" 2>/dev/null ;;
  *--list-boot-entries*) cat "{tmp_path}/entries" 2>/dev/null ;;
  *--other-os*) echo "other-os $4" >> "{calls}" ;;
esac
""")
    mkconfig = bin_dir / "grub-mkconfig"
    mkconfig.write_text(f'#!/bin/sh\necho "mkconfig $*" >> "{calls}"\n')
    for f in (python, mkconfig):
        f.chmod(f.stat().st_mode | stat.S_IEXEC)
    grub_cfg = tmp_path / "grub.cfg"
    grub_cfg.write_text("")
    grub = tmp_path / "default-grub"
    grub.write_text('GRUB_DEFAULT=0\nGRUB_TIMEOUT=5\nGRUB_TIMEOUT_STYLE=menu\n')

    def run(answers: str, boot_setup: int = 0, tty: int = 1):
        script = f"""set -euo pipefail
info() {{ echo "INFO $*"; }}
warn() {{ echo "WARN $*"; }}
sudo() {{ if [ "$1" = test ]; then [ -e "{grub_cfg}" ]; else "$@"; fi; }}
{script_functions()}
APP_DIR="{tmp_path}/app" VENV="{venv}" BOOT_SETUP={boot_setup} GRUB_DEFAULT_FILE="{grub}"
ask_boot_questions
echo finished
"""
        script = script.replace("/boot/grub/grub.cfg /boot/grub2/grub.cfg", str(grub_cfg))
        env = dict(os.environ, PATH=f"{bin_dir}:{os.environ['PATH']}", GC_ASSUME_TTY=str(tty))
        result = subprocess.run(["bash", "-c", script], input=answers, text=True, capture_output=True, env=env)
        assert result.returncode == 0, result.stdout + result.stderr
        return result.stdout, (calls.read_text() if calls.exists() else "")

    return tmp_path, grub, run


def test_yes_sets_grub_timeout_zero_and_picks_windows(setup):
    tmp, grub, run = setup
    (tmp / "entries").write_text("0000\tWindows\n0005\tFedora\n")
    out, calls = run("y\n1\n")
    assert "GRUB_TIMEOUT=0\n" in grub.read_text() and "GRUB_TIMEOUT_STYLE=menu" in grub.read_text()
    assert "mkconfig -o" in calls and "other-os 0000" in calls
    assert "1) Windows (boot entry 0000)" in out and "2) Fedora (boot entry 0005)" in out
    assert out.strip().endswith("finished")


def test_no_and_no_second_os(setup):
    tmp, grub, run = setup
    (tmp / "entries").write_text("0000\tWindows\n")
    out, calls = run("n\n0\n")
    assert "GRUB_TIMEOUT=5" in grub.read_text() and "mkconfig" not in calls
    assert "other-os none" in calls and "no 'Restart into" in out
    # next update: the GRUB question isn't asked again, nor the OS one once answered
    (tmp / "current").write_text("none\n")
    (tmp / "calls").unlink()
    out, calls = run("")
    assert "GRUB" not in out and calls == ""


def test_boot_setup_asks_again(setup):
    tmp, grub, run = setup
    (tmp / "entries").write_text("0000\tWindows\n")
    run("n\n0\n")
    (tmp / "current").write_text("none\n")
    out, calls = run("y\n1\n", boot_setup=1)
    assert "GRUB_TIMEOUT=0" in grub.read_text() and "other-os 0000" in calls


def test_nothing_found_means_no_button_without_asking(setup):
    tmp, grub, run = setup
    out, calls = run("n\n")
    assert "other-os none" in calls and "No second operating system found" in out


def test_no_questions_without_a_terminal(setup):
    tmp, grub, run = setup
    (tmp / "entries").write_text("0000\tWindows\n")
    out, calls = run("", tty=0)
    assert out.strip() == "finished" and calls == "" and "GRUB_TIMEOUT=5" in grub.read_text()
