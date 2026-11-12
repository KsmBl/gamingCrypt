"""Shutting down, restarting, sleeping, leaving gaming mode or locking while a game is being moved or a
stick formatted: asked first (or, locking, the move stopped and the format waited for)."""

import threading

import pytest

from gamingcrypt import moving, ongoing
from gamingcrypt.moving import MoveError, Place, Progress
from gamingcrypt.system import removable
from gamingcrypt.ui.modal import ConfirmBox, open_modal
from tests.test_code_dialogs import rect_in
from tests.test_moving import emu, rom, stick  # noqa: F401 - fixtures
from tests.test_panic_lock import Unlocker, window  # noqa: F401 - fixture

SCREENS = [(1280, 800), (1280, 720), (1920, 1080), (1366, 768), (1024, 600)]


@pytest.fixture
def powered(window, monkeypatch):  # noqa: F811
    calls = []
    monkeypatch.setattr(window, "power_runner", lambda kind: calls.append(kind) or (True, ""))
    window._power_calls = calls
    return window


def question(window):
    modal = open_modal(window)
    return modal.content if modal is not None and isinstance(modal.content, ConfirmBox) else None


# --- what's going on --------------------------------------------------------------------------

def test_jobs_come_and_go():
    with ongoing.running("Formatting GAMES"):
        part = [0.5]
        job = ongoing.start(ongoing.Job("Moving Celeste to GAMES", lambda: part[0]))
        assert ongoing.busy()
        assert ongoing.summary() == "Formatting GAMES\nMoving Celeste to GAMES (50 %)"
        ongoing.end(job)
    assert not ongoing.busy() and ongoing.summary() == ""


def test_only_what_can_stop_is_stopped():
    stopped = []
    ongoing.start(ongoing.Job("Moving Celeste", cancel=lambda: stopped.append(1)))
    ongoing.start(ongoing.Job("Formatting GAMES"))
    left = ongoing.cancel_what_can_stop()
    assert stopped == [1] and [j.text for j in left] == ["Formatting GAMES"]


def test_a_move_is_a_job_while_it_runs(emu, stick, monkeypatch):  # noqa: F811
    mario = rom(emu, "snes")
    seen = []
    real = moving._copy_file

    def copy(source, dest, progress):
        seen.append(ongoing.summary())
        real(source, dest, progress)

    monkeypatch.setattr(moving, "_copy_file", copy)
    moving.move(mario, Place(stick), emu)
    assert seen == ["Moving Super Mario World to STICK (0 %)"]
    assert not ongoing.busy()


def test_stopping_a_move_job_stops_the_move(emu, stick, monkeypatch):  # noqa: F811
    story = rom(emu, "psx")
    real = moving._copy_file

    def copy(source, dest, progress):
        ongoing.cancel_what_can_stop()  # (locking, half way)
        real(source, dest, progress)

    monkeypatch.setattr(moving, "_copy_file", copy)
    with pytest.raises(MoveError, match="Cancelled"):
        moving.move(story, Place(stick), emu, Progress())
    assert all(d.exists() for d in story.discs) and not ongoing.busy()


def test_formatting_and_repairing_are_jobs(stick, monkeypatch):  # noqa: F811
    seen = []
    monkeypatch.setattr(removable, "_format", lambda *a, **k: seen.append(ongoing.summary()) or stick)
    removable.format_drive(stick, "exfat", "GAMES")
    assert seen == ["Formatting STICK"] and not ongoing.busy()

    def run(args, **_k):
        import subprocess

        seen.append(ongoing.summary())
        return subprocess.CompletedProcess(args, 1, "", "nope")

    with pytest.raises(removable.FormatError):
        removable.repair(stick, run)
    assert seen[-1] == "Repairing STICK" and not ongoing.busy()


def test_new_code_on_a_stick_is_a_job(monkeypatch, tmp_path):
    from gamingcrypt.system import stick_crypt

    seen = []
    monkeypatch.setattr(stick_crypt, "_rekey", lambda *a, **k: seen.append(ongoing.summary()) or True)
    assert stick_crypt.rekey(tmp_path / "GamingCrypt.vc", "old", "new", {})
    assert seen == ["Giving a USB stick your new code"] and not ongoing.busy()


# --- power ------------------------------------------------------------------------------------

def test_nothing_going_on_nothing_asked(qtbot, powered):
    powered.power_action("shutdown")
    assert powered._power_calls == ["shutdown"] and question(powered) is None


@pytest.mark.parametrize("kind,word", [("shutdown", "Shut down"), ("restart", "Restart"),
                                       ("boot:0003", "Restart")])
def test_asked_while_formatting(qtbot, powered, kind, word):
    job = ongoing.start(ongoing.Job("Formatting GAMES"))
    powered.power_action(kind)
    box = question(powered)
    assert box is not None and powered._power_calls == []
    assert "Formatting GAMES" in box.question.text() and box.action_button.text() == f"{word} anyway"
    box.cancel_button.click()  # wait
    assert powered._power_calls == [] and question(powered) is None
    powered.power_action(kind)
    question(powered).action_button.click()
    assert powered._power_calls == [kind]
    ongoing.end(job)


def test_from_the_power_menu(qtbot, powered):
    ongoing.start(ongoing.Job("Moving Celeste to GAMES", lambda: 0.62))
    powered.shell.open_power_menu()
    powered.shell.power_menu.shutdown_button.click()
    box = question(powered)
    assert "Moving Celeste to GAMES (62 %)" in box.question.text()
    assert powered._power_calls == []


def test_sleep_and_gaming_mode_and_desktop(qtbot, powered, monkeypatch):
    done = []
    monkeypatch.setattr(powered, "go_to_sleep", lambda: done.append("sleep"))
    monkeypatch.setattr(powered, "leave_gaming_mode", lambda target: done.append(target))
    monkeypatch.setattr(powered, "_desktop_now", lambda: done.append("desktop"))
    ongoing.start(ongoing.Job("Formatting GAMES"))
    for act in (lambda: powered.power_action("sleep"), powered.restart_gaming_mode, powered.desktop_mode):
        act()
        box = question(powered)
        assert box is not None and done == []
        box.cancel_button.click()
    powered.config["system"]["power_button"] = "sleep"
    powered._last_power_press = -1e9
    powered.power_button()  # (the device's power button, set to sleep)
    assert question(powered) is not None and done == []
    question(powered).action_button.click()
    assert done == ["sleep"]
    ongoing.clear()
    powered.restart_gaming_mode()
    assert done == ["sleep", "restart"]


@pytest.mark.parametrize("w,h", SCREENS)
def test_the_question_fits(qtbot, powered, w, h):
    powered.resize(w, h)
    ongoing.start(ongoing.Job("Moving Ori and the Blind Forest - Definitive Edition to GAMES", lambda: 0.3))
    ongoing.start(ongoing.Job("Formatting SANDISK"))
    powered.power_action("shutdown")
    box = question(powered)
    qtbot.waitUntil(lambda: box.isVisible())
    for part in (box.question, box.cancel_button, box.action_button):
        assert powered.rect().contains(rect_in(part, powered)), f"{part} is off the {w}x{h} screen"


# --- locking ----------------------------------------------------------------------------------

def test_locking_stops_a_move_and_waits_for_a_format(qtbot, window, monkeypatch):  # noqa: F811
    window.JOBS_POLL_MS = 20
    stopped = threading.Event()
    move = ongoing.start(ongoing.Job("Moving Celeste to GAMES", cancel=stopped.set))
    format_ = ongoing.start(ongoing.Job("Formatting GAMES"))
    window.power_action("lock")
    assert window.screen_name == "lock" and stopped.is_set()  # the lock screen right away
    lock = window.stack.currentWidget()
    qtbot.waitUntil(lambda: "Formatting GAMES" in lock.status.text())
    assert "Locking when this is done" in lock.status.text()
    ongoing.end(move)  # (the move finished stopping)
    qtbot.wait(80)
    assert Unlocker.dismounted == [] and lock.busy  # the format goes on: not unmounted, no unlocking
    for key in "1234✓":
        lock.input.widget.press(key)
    qtbot.wait(50)
    assert window.screen_name == "lock"
    ongoing.end(format_)
    qtbot.waitUntil(lambda: lock.status.text() == "Locked")
    assert Unlocker.dismounted == [1] and not lock.busy


def test_locking_with_nothing_going_on_is_as_before(qtbot, window):  # noqa: F811
    window.power_action("lock")
    lock = window.stack.currentWidget()
    qtbot.waitUntil(lambda: lock.status.text() == "Locked")
    assert Unlocker.dismounted == [1]
