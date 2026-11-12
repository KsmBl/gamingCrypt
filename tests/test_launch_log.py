"""Steam's own log says why a game didn't start (gamingcrypt/steam/launch_log.py)."""

from datetime import datetime

import pytest

from gamingcrypt.steam import launch_log

START = datetime(2026, 11, 12, 20, 1, 0).timestamp()


def write(root, *lines):
    logs = root / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "console_log.txt").write_text("\n".join(lines) + "\n")


def at(second, text, appid=620):
    return f"[2026-11-12 20:01:{second:02d}] GameAction [AppID {appid}, ActionID 3] : {text}"


@pytest.mark.parametrize("line,words", [
    ('LaunchApp waiting for user response to ShowEula ""', "accept the game's license"),
    ('LaunchApp waiting for user response to CloudConflict ""', "two different saves"),
    ('LaunchApp waiting for user response to ShowSomethingNew ""', "(ShowSomethingNew)"),
    ('LaunchApp changed task to Failed with "Missing executable"', "can't find the game's start file"),
    ('LaunchApp changed task to Failed with "Invalid platform"', "choose a Proton version"),
    ('LaunchApp changed task to Failed with "App already running"', "still running"),
    ('LaunchApp changed task to Failed with "Not enough disk space"', "enough room"),
    ('LaunchApp changed task to Failed with "Something odd"', "Steam says: Something odd"),
])
def test_what_steam_said(tmp_path, line, words):
    write(tmp_path, at(1, 'LaunchApp changed task to ProcessingInstallScript with ""'), at(2, line))
    assert words in launch_log.explain(tmp_path, 620, START)


def test_only_this_game_and_only_since_it_was_started(tmp_path):
    write(tmp_path,
          "[2026-11-12 19:00:00] GameAction [AppID 620, ActionID 1] : LaunchApp changed task to Failed with "
          '"Missing executable"',  # (an hour ago)
          at(2, 'LaunchApp waiting for user response to ShowEula ""', appid=440),  # (another game)
          at(3, 'LaunchApp changed task to Completed with ""'))
    assert launch_log.explain(tmp_path, 620, START) is None


def test_the_last_reason_counts(tmp_path):
    write(tmp_path, at(1, 'LaunchApp waiting for user response to ShowEula ""'),
          at(4, 'LaunchApp changed task to Failed with "Missing executable"'))
    assert "start file" in launch_log.explain(tmp_path, 620, START)


def test_no_log_no_reason(tmp_path):
    assert launch_log.explain(tmp_path, 620, START) is None
    assert launch_log.explain("", 620, START) is None
    write(tmp_path, "garbage", "[not a time] [AppID 620, x] : Missing executable")
    assert launch_log.explain(tmp_path, 620, START) is None


def test_only_the_end_of_a_long_log_is_read(tmp_path, monkeypatch):
    monkeypatch.setattr(launch_log, "TAIL_BYTES", 400)
    write(tmp_path, *["x" * 100] * 50, at(2, 'LaunchApp changed task to Failed with "Missing executable"'))
    assert "start file" in launch_log.explain(tmp_path, 620, START)


# --- where it's said ------------------------------------------------------------------------------

@pytest.fixture
def steam_log(tmp_path, monkeypatch):
    """The fake Steam service reads a real log (as SteamService does)."""
    from gamingcrypt.steam.service import SteamService
    from tests.fakes import FakeService

    monkeypatch.setattr(FakeService, "root", tmp_path, raising=False)
    monkeypatch.setattr(FakeService, "launch_problem", SteamService.launch_problem, raising=False)
    return tmp_path


def now_line(text, appid=620):
    from datetime import datetime as dt

    return f"[{dt.now():%Y-%m-%d %H:%M:%S}] GameAction [AppID {appid}, ActionID 7] : {text}"


def test_the_notice_says_why(qtbot, monkeypatch, steam_log):
    from tests.test_crash_notice import started

    window, w, game, clock = started(qtbot, monkeypatch)
    write(steam_log, now_line('LaunchApp waiting for user response to ShowEula ""'))
    clock.now += w.timing.launch_timeout_s + 1
    w.poll()
    assert window.toasts.shown[-1].startswith("Portal 2 didn't start: Steam wants you to accept the game's license")


def test_nothing_in_the_log_the_tip_as_before(qtbot, monkeypatch, steam_log):
    from tests.test_crash_notice import started

    window, w, game, clock = started(qtbot, monkeypatch)
    write(steam_log, "[2020-01-01 00:00:00] GameAction [AppID 620, ActionID 1] : Missing executable")  # (old)
    clock.now += w.timing.launch_timeout_s + 1
    w.poll()
    assert window.toasts.shown[-1].startswith("Portal 2 didn't start. If it's a Windows game")


def test_not_asked_for_gamingcryptS_own_games(qtbot, monkeypatch, steam_log):
    from gamingcrypt.wine.library import WINE_APPID_BASE
    from tests.test_game_running import make_window

    window, *_ = make_window(qtbot, monkeypatch)
    asked = []
    monkeypatch.setattr(type(window.shell.pages["Games"].service), "launch_problem",
                        lambda self, appid, since: asked.append(appid) or "nope", raising=False)
    window.game_didnt_start(WINE_APPID_BASE + 3)
    assert asked == [] and "start file or Proton / Wine" in window.toasts.shown[-1]


def test_the_games_page_says_why(qtbot, steam_log):
    from tests.test_game_detail import silent_tab

    tab = silent_tab(qtbot)
    game = tab.home.installed[0]
    tab.open_game(game.appid)
    page = tab.currentWidget()
    page.main_action()  # Play
    assert page.launched_at > 0
    write(steam_log, now_line('LaunchApp changed task to Failed with "Missing executable"', game.appid))
    page.game_session_ended(game.appid, True)
    assert page.status.text() == f"{game.name} didn't start: Steam can't find the game's start file - check its " \
                                 "files in Steam (Properties → Installed Files → Verify)."
    write(steam_log, "")
    page.game_session_ended(game.appid, True)
    assert page.status.text() == f"{game.name} didn't start - check Steam"


SCREENS = [(1280, 800), (1280, 720), (1920, 1080), (1366, 768), (1024, 600)]


@pytest.mark.parametrize("w,h", SCREENS)
def test_the_longest_reason_fits(qtbot, monkeypatch, steam_log, w, h):
    from tests.test_code_dialogs import rect_in
    from tests.test_crash_notice import started

    window, watcher, game, clock = started(qtbot, monkeypatch)
    window.resize(w, h)
    longest = max(launch_log.WAITING.values(), key=len)
    write(steam_log, now_line('LaunchApp waiting for user response to ShowEula ""'))
    assert len(launch_log.WAITING["showeula"]) == len(longest)
    clock.now += watcher.timing.launch_timeout_s + 1
    watcher.poll()
    qtbot.waitUntil(window.toasts.isVisible)
    assert window.rect().contains(rect_in(window.toasts, window)), f"the notice is off the {w}x{h} screen"
