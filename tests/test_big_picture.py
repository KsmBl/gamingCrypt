import subprocess

from gamingcrypt.steam.client import SteamClient
from gamingcrypt.system import x11windows
from gamingcrypt.ui import big_picture
from gamingcrypt.ui.big_picture import BigPictureWatcher

# what gamescope on the real device returned (window, app id, pid triples)
GAMESCOPE_ROOT = """_NET_ACTIVE_WINDOW(WINDOW): window id # 0x400007
GAMESCOPE_FOCUSABLE_WINDOWS(CARDINAL) = 4194311, 4194311, 759, 8388609, 769, 2000
"""
DESKTOP_ROOT = "_NET_CLIENT_LIST(WINDOW): window id # 0x400007, 0x800001\n"
NAMES = {"4194311": '_NET_WM_NAME(UTF8_STRING) = "GamingCrypt"\n',
         "8388609": '_NET_WM_NAME(UTF8_STRING) = "Steam Big Picture Mode"\n',
         "0x400007": "", "4194311x": ""}


def runner_for(root, names):
    def run(cmd, **kw):
        if cmd[1] == "-root":
            return subprocess.CompletedProcess(cmd, 0, root, "")
        wid = cmd[2]
        return subprocess.CompletedProcess(cmd, 0, names.get(wid, 'WM_NAME(STRING) = "Other"\n'), "")
    return run


def test_windows_under_gamescope():
    run = runner_for(GAMESCOPE_ROOT, NAMES)
    assert x11windows.window_ids(run) == [4194311, 8388609]
    assert x11windows.window_titles(run) == ["GamingCrypt", "Steam Big Picture Mode"]
    assert x11windows.big_picture_open(run)


def test_windows_on_the_desktop():
    run = runner_for(DESKTOP_ROOT, {str(0x400007): 'WM_NAME(STRING) = "GamingCrypt"\n'})
    assert x11windows.window_ids(run) == [0x400007, 0x800001]
    assert not x11windows.big_picture_open(run)


def test_no_x11_or_no_xprop():
    def missing(cmd, **kw):
        raise FileNotFoundError("xprop")

    assert x11windows.window_ids(missing) == [] and not x11windows.big_picture_open(missing)
    failing = lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "unable to open display")  # noqa: E731
    assert x11windows.window_titles(failing) == []


def test_client_opens_big_picture():
    calls, opened = [], []
    client = SteamClient(["steam"], launcher=lambda cmd, **kw: calls.append(cmd))
    client.on_big_picture = lambda: opened.append(1)
    assert client.open_big_picture()
    assert calls == [["steam", "steam://open/bigpicture"]] and opened == [1]


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def run_watcher(qtbot, states, clock=None):
    clock = clock or Clock()
    seq = iter(states)
    watcher = BigPictureWatcher(is_open=lambda: next(seq), clock=clock)
    closed = []
    watcher.closed.connect(lambda: closed.append(1))
    watcher.watch()
    watcher.timer.stop()  # poll by hand
    return watcher, closed, clock


def poll(qtbot, watcher):
    watcher.poll()
    qtbot.waitUntil(lambda: not watcher.checking)


def test_comes_back_when_big_picture_closes(qtbot):
    watcher, closed, clock = run_watcher(qtbot, [False, True, True, False])
    poll(qtbot, watcher)  # Steam still starting
    assert closed == []
    poll(qtbot, watcher)
    poll(qtbot, watcher)  # open: stay away
    assert closed == [] and watcher.seen
    poll(qtbot, watcher)  # closed
    assert closed == [1] and not watcher.active


def test_comes_back_if_big_picture_never_opens(qtbot):
    watcher, closed, clock = run_watcher(qtbot, [False, False])
    poll(qtbot, watcher)
    clock.now = big_picture.APPEAR_TIMEOUT_S + 1
    poll(qtbot, watcher)
    assert closed == [1]


def test_detection_errors_count_as_closed(qtbot):
    clock = Clock()

    def boom():
        raise RuntimeError("X11 gone")

    watcher = BigPictureWatcher(is_open=boom, clock=clock)
    closed = []
    watcher.closed.connect(lambda: closed.append(1))
    watcher.watch()
    watcher.timer.stop()
    clock.now = big_picture.APPEAR_TIMEOUT_S + 1
    poll(qtbot, watcher)
    assert closed == [1]


def test_button_on_steam_page_and_launcher_steps_aside(qtbot, monkeypatch):
    import copy

    from gamingcrypt.app import MainWindow
    from gamingcrypt.config import DEFAULTS
    from gamingcrypt.ui.games_tab import GamesTab
    from gamingcrypt.ui.steam_page import SteamLibraryPage
    from tests.fakes import FakeService

    SteamLibraryPage.FETCH_DELAY_MS = 0
    service = FakeService()
    service.client.open_big_picture = lambda: (service.on_big_picture(), True)[1]
    window = MainWindow(copy.deepcopy(DEFAULTS), lambda c: None,
                        page_factory=lambda cfg: {"Games": GamesTab(service)})
    qtbot.addWidget(window)
    window.show()
    window.show_shell()
    calls = []
    monkeypatch.setattr(window, "step_aside", lambda: calls.append("aside"))
    monkeypatch.setattr(window, "bring_to_front", lambda: calls.append("back"))
    games = window.shell.pages["Games"]
    games.open_steam()
    page = games.currentWidget()
    qtbot.waitUntil(lambda: not page.loading)
    page.big_picture_button.click()
    assert calls == ["aside"] and window.big_picture.active
    window.big_picture.closed.disconnect()
    window.big_picture.closed.connect(window.bring_to_front)
    window.big_picture.stop()
    window.big_picture.closed.emit()
    assert calls == ["aside", "back"]


def test_unreachable_steam(qtbot):
    from gamingcrypt.ui.games_tab import GamesTab
    from gamingcrypt.ui.steam_page import SteamLibraryPage
    from tests.fakes import FakeService

    SteamLibraryPage.FETCH_DELAY_MS = 0
    service = FakeService()
    service.client.open_big_picture = lambda: False
    tab = GamesTab(service)
    qtbot.addWidget(tab)
    tab.open_steam()
    page = tab.currentWidget()
    qtbot.waitUntil(lambda: not page.loading)
    page.big_picture_button.click()
    assert "Could not reach Steam" in page.status.text()
