"""The games drive is a container of a fixed size: a download that won't fit is asked about first, the
game's page says how much room there is, and a nearly full drive is said once after unlocking."""

import os

import pytest

from gamingcrypt.system import drive_space
from gamingcrypt.ui.modal import ConfirmBox, open_modal
from tests.test_code_dialogs import rect_in
from tests.test_game_detail import silent_tab
from tests.test_game_running import make_window

GB = 1024 ** 3
SCREENS = [(1280, 800), (1280, 720), (1920, 1080), (1366, 768), (1024, 600)]


def test_rules():
    assert drive_space.fits(None, 1) and drive_space.fits(5, None) and drive_space.fits(5, 5)
    assert not drive_space.fits(6, 5)
    assert drive_space.is_low(3 * GB) and not drive_space.is_low(50 * GB) and not drive_space.is_low(None)


def test_free_of_a_folder(tmp_path):
    assert drive_space.free(tmp_path) > 0
    assert drive_space.free(tmp_path / "gone") is None and drive_space.free("") is None


def test_the_service_asks_where_downloads_go(tmp_path):
    from gamingcrypt.steam.service import SteamService

    svc = SteamService({"command": "steam"}, tmp_path)
    svc.target_library = lambda: tmp_path
    assert svc.free_space() == drive_space.free(tmp_path)


def witcher_page(qtbot, free, size=40 * GB):
    tab = silent_tab(qtbot)
    tab.service.free_space = lambda: free
    game = tab.games[292030]
    game.store_size = size
    tab.open_game(292030)
    page = tab.currentWidget()
    qtbot.waitUntil(lambda: page.free_bytes == free)
    return tab, page


def test_room_is_said_on_the_page(qtbot):
    tab, page = witcher_page(qtbot, 100 * GB)
    assert "Free on your games drive: 100" in page.room_text()
    _, short = witcher_page(qtbot, 12 * GB)
    assert short.room_text().startswith("⚠ Only 12")


def test_it_fits_no_question(qtbot):
    tab, page = witcher_page(qtbot, 100 * GB)
    page.main_button.click()
    assert open_modal(page.window(), on_screen=False) is None
    qtbot.waitUntil(lambda: tab.service.installs == [292030])


def test_it_doesnt_fit_asked_first(qtbot):
    tab, page = witcher_page(qtbot, 12 * GB)
    page.main_button.click()
    modal = open_modal(page.window(), on_screen=False)
    assert isinstance(modal.content, ConfirmBox)
    text = modal.content.question.text()
    assert "The Witcher 3 needs about 40" in text and "only 12" in text and "Settings → Storage" in text
    modal.content.cancel_button.click()
    qtbot.wait(30)
    assert tab.service.installs == [] and not page.downloading
    page.main_button.click()
    open_modal(page.window(), on_screen=False).content.action_button.click()
    qtbot.waitUntil(lambda: tab.service.installs == [292030])


def test_installed_games_say_nothing_about_room(qtbot):
    tab = silent_tab(qtbot)
    tab.service.free_space = lambda: 1 * GB
    tab.open_game(620)
    page = tab.currentWidget()
    qtbot.wait(50)
    assert page.room_text() == ""


@pytest.mark.parametrize("w,h", SCREENS)
def test_the_question_fits(qtbot, w, h):
    tab, page = witcher_page(qtbot, 12 * GB)
    tab.resize(w, h)
    tab.show()
    page.main_button.click()
    box = open_modal(page.window(), on_screen=False).content
    qtbot.waitUntil(box.isVisible)
    host = page.window()
    for part in (box.question, box.cancel_button, box.action_button):
        assert host.rect().contains(rect_in(part, host)), f"{part} is off the {w}x{h} screen"


# --- nearly full -------------------------------------------------------------------------------

@pytest.fixture
def unlocked(qtbot, monkeypatch, tmp_path):
    window, service, calls = make_window(qtbot, monkeypatch)
    window.config["unlock"]["mount_point"] = str(tmp_path)
    real = os.path.ismount
    monkeypatch.setattr(os.path, "ismount", lambda p: str(p) == str(tmp_path) or real(p))
    return window


def warnings(window):
    return [t for t in window.toasts.shown if "almost full" in t]


def test_nearly_full_is_said_once(qtbot, unlocked, monkeypatch):
    monkeypatch.setattr(drive_space, "free", lambda path: 3 * GB)
    unlocked.check_drive_space()
    qtbot.waitUntil(lambda: warnings(unlocked) != [])
    assert "3.0 GB free" in warnings(unlocked)[0] and "Settings → Storage" in warnings(unlocked)[0]
    unlocked.check_drive_space()  # (a download finished: not again)
    qtbot.wait(50)
    assert len(warnings(unlocked)) == 1


def test_room_enough_nothing_said(qtbot, unlocked, monkeypatch):
    monkeypatch.setattr(drive_space, "free", lambda path: 200 * GB)
    unlocked.check_drive_space()
    qtbot.wait(50)
    assert warnings(unlocked) == []


def test_said_again_after_locking(qtbot, unlocked, monkeypatch):
    monkeypatch.setattr(drive_space, "free", lambda path: 3 * GB)
    unlocked.space_warned = True
    unlocked.show_lock()
    assert not unlocked.space_warned


def test_checked_when_a_download_finished_and_after_unlocking(qtbot, monkeypatch, tmp_path):
    from gamingcrypt.app import MainWindow

    checked = []
    monkeypatch.setattr(MainWindow, "SPACE_CHECK_MS", 0)
    monkeypatch.setattr(MainWindow, "check_drive_space", lambda self: checked.append(1))
    from tests.fakes import FakeService

    monkeypatch.setattr(FakeService, "downloads", lambda self: [], raising=False)
    window, *_ = make_window(qtbot, monkeypatch)
    qtbot.waitUntil(lambda: checked != [])
    before = len(checked)
    window.download_notifier.message.emit("⬇", "Download finished: Hades")
    assert len(checked) == before + 1
    window.download_notifier.message.emit("↻", "Update available for Hades")
    assert len(checked) == before + 1
