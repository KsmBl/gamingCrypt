"""First-start tour and "What's new" after an update."""

import copy
import subprocess
from pathlib import Path

import pytest

from gamingcrypt.ui import tour as tour_mod

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def window(qtbot, monkeypatch, tmp_path):
    from gamingcrypt.app import MainWindow
    from gamingcrypt.config import DEFAULTS

    monkeypatch.setattr(MainWindow, "welcome_enabled", True)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    saved = []
    w = MainWindow(copy.deepcopy(DEFAULTS), saved.append)
    qtbot.addWidget(w)
    w.resize(1280, 800)
    w.show()
    w._saved = saved
    return w


def test_tour_on_first_start_only(qtbot, window):
    window.show_shell()
    qtbot.waitUntil(lambda: getattr(window, "tour", None) is not None and window.tour.isVisible())
    tour = window.tour
    assert window.nav_root() is tour and tour.title.text() == "Welcome to GamingCrypt"
    assert not tour.back_button.isEnabled()
    for _ in range(len(tour_mod.TOUR) - 1):
        tour.next_button.click()
    assert tour.next_button.text() == "Let's go" and not tour.skip_button.isVisible()
    assert tour.gamepad_back() and tour.step == len(tour_mod.TOUR) - 2  # B: one step back
    tour.next_button.click()
    tour.next_button.click()
    assert not tour.isVisible() and window._saved[-1]["tour_done"] is True
    window.tour = None
    window.show_shell()  # next start
    qtbot.wait(20)
    assert window.tour is None


def test_skip(qtbot, window):
    window.show_shell()
    qtbot.waitUntil(lambda: getattr(window, "tour", None) is not None)
    window.tour.skip_button.click()
    assert window.config["tour_done"] and not window.tour.isVisible()


def test_whats_new_once_after_an_update(qtbot, window):
    window.config["tour_done"] = True
    news = tour_mod.news_file()
    news.parent.mkdir(parents=True)
    news.write_text("Sleep on the power button\nRelease 0.5.2\n\nRestart into Windows\n")
    window.show_shell()
    qtbot.waitUntil(lambda: getattr(window, "whats_new", None) is not None and window.whats_new.isVisible())
    assert window.whats_new.text.text() == "• Sleep on the power button\n• Restart into Windows"
    assert window.nav_root() is window.whats_new
    window.whats_new.ok_button.click()
    assert not news.exists() and news.with_suffix(".seen").exists()
    window.whats_new = None
    window.show_shell()
    qtbot.wait(20)
    assert window.whats_new is None  # read: not again


def test_long_news_are_shortened(qtbot):
    from PySide6.QtWidgets import QWidget

    host = QWidget()
    qtbot.addWidget(host)
    host.show()
    news = tour_mod.WhatsNew(host)
    news.open_news([f"change {i}" for i in range(20)])
    assert news.text.text().endswith("… and 8 more")


def test_install_script_records_the_changes(tmp_path):
    repo, app_dir = tmp_path / "repo", tmp_path / "app"
    app_dir.mkdir()
    git = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True, capture_output=True, text=True)  # noqa
    repo.mkdir()
    git("init", "-q")
    git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "first")
    function = subprocess.run(["sed", "-n", "/^record_whats_new()/,/^}/p", str(ROOT / "install.sh")],
                              capture_output=True, text=True).stdout
    run = lambda: subprocess.run(["bash", "-c", f'{function}\nSRC_DIR="{repo}" APP_DIR="{app_dir}" record_whats_new'],  # noqa
                                 check=True)
    run()  # first install: nothing is "new"
    assert not (app_dir / "whats-new.txt").exists()
    git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "Sleep on the power button")
    git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "Health page")
    run()
    assert (app_dir / "whats-new.txt").read_text() == "Health page\nSleep on the power button\n"
    run()  # same version again: nothing added
    assert (app_dir / "whats-new.txt").read_text().count("\n") == 2
