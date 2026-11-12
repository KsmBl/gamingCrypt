"""A game gone a few seconds after it started (not quit): "… closed after 4 s - it may have crashed"
with what to try, as a notice - wherever it was started from. One that never came up: "didn't start"."""

import pytest

from gamingcrypt.emulation.library import EMU_APPID_BASE
from gamingcrypt.linux.library import LINUX_APPID_BASE
from gamingcrypt.ui import game_watcher
from gamingcrypt.wine.library import WINE_APPID_BASE
from tests.test_code_dialogs import rect_in
from tests.test_game_running import Clock, Game, make_window, watcher_for

SCREENS = [(1280, 800), (1280, 720), (1920, 1080), (1366, 768), (1024, 600)]


def run_for(w, game, clock, seconds, quit_=False):
    game.pids, game.drawing = {1}, True
    w.poll()
    clock.now += game_watcher.WINDOW_DELAY_S
    w.poll()
    clock.now += seconds - game_watcher.WINDOW_DELAY_S
    if quit_:
        w.expect_exit()
    game.pids = set()
    w.poll()
    clock.now += game_watcher.EXIT_GRACE_S + 1
    w.poll()


def test_watcher_says_ended_early(qtbot):
    game, clock = Game(), Clock()
    w, events = watcher_for(game, clock)
    early = []
    w.ended_early.connect(lambda appid, s: early.append((appid, s)))
    w.watch(620)
    run_for(w, game, clock, 4)
    assert early == [(620, 4)] and events[-1] == "finished"


@pytest.mark.parametrize("seconds,quit_", [(game_watcher.SHORT_S + 60, False), (4, True)])
def test_played_or_quit_isnt_a_crash(qtbot, seconds, quit_):
    game, clock = Game(), Clock()
    w, events = watcher_for(game, clock)
    early = []
    w.ended_early.connect(lambda appid, s: early.append(s))
    w.watch(620)
    run_for(w, game, clock, seconds, quit_)
    assert early == [] and events[-1] == "finished"


def started(qtbot, monkeypatch, appid=620):
    window, service, calls = make_window(qtbot, monkeypatch)
    game, clock = Game(), Clock()
    w = window.game_watcher
    w.processes, w.gpu, w.clock = game.processes, game.gpu, clock
    window.game_launched(appid)
    return window, w, game, clock


def test_a_steam_game_that_crashes(qtbot, monkeypatch):
    window, w, game, clock = started(qtbot, monkeypatch)
    run_for(w, game, clock, 3)
    text = window.toasts.shown[-1]
    assert text.startswith("Portal 2 closed after 3 s - it may have crashed.") and "Proton" in text


def test_a_steam_game_played_says_nothing(qtbot, monkeypatch):
    window, w, game, clock = started(qtbot, monkeypatch)
    run_for(w, game, clock, 600)
    assert not any("crashed" in t or "didn't start" in t for t in window.toasts.shown)


def test_one_that_never_came_up(qtbot, monkeypatch):
    window, w, game, clock = started(qtbot, monkeypatch)
    clock.now += w.timing.launch_timeout_s + 1
    w.poll()
    assert window.toasts.shown[-1].startswith("Portal 2 didn't start.")


@pytest.mark.parametrize("appid,tip", [(WINE_APPID_BASE + 3, "start file or Proton / Wine"),
                                       (LINUX_APPID_BASE + 3, "start file"),
                                       (EMU_APPID_BASE + 3, "another core")])
def test_what_to_try_per_kind(qtbot, monkeypatch, appid, tip):
    window, *_ = make_window(qtbot, monkeypatch)
    window.game_ended_early(appid, 2.4)
    assert "closed after 2 s" in window.toasts.shown[-1] and tip in window.toasts.shown[-1]


def test_movies_and_minecraft_say_it_themselves(qtbot, monkeypatch):
    from gamingcrypt.minecraft.library import is_minecraft_appid
    from gamingcrypt.movies.library import is_movie_appid

    window, *_ = make_window(qtbot, monkeypatch)
    before = list(window.toasts.shown)
    movie = next(a for a in range(0x60000000, 0x7fffffff, 0x100000) if is_movie_appid(a))
    craft = next(a for a in range(0x30000000, 0x7fffffff, 0x100000) if is_minecraft_appid(a))
    window.game_ended_early(movie, 2)
    window.game_ended_early(craft, 2)
    window.game_didnt_start(movie)
    assert window.toasts.shown == before


@pytest.mark.parametrize("w,h", SCREENS)
def test_the_notice_fits(qtbot, monkeypatch, w, h):
    window, *_ = make_window(qtbot, monkeypatch)
    window.resize(w, h)
    window.game_ended_early(WINE_APPID_BASE + 3, 4)
    toasts = window.toasts
    qtbot.waitUntil(toasts.isVisible)
    assert window.rect().contains(rect_in(toasts, window)), f"the notice is off the {w}x{h} screen"
