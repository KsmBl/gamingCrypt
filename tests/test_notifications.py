"""Toasts (download finished, updates, battery 15 %), the 10 % warning and the time
left in the battery display."""

import copy

import pytest

from gamingcrypt.system.battery import BatteryState, read_battery
from gamingcrypt.ui.battery_warning import BatteryMonitor, BatteryWarning
from gamingcrypt.ui.download_notifier import DownloadNotifier
from gamingcrypt.ui.toast import Toasts


def supply(root, name, **files):
    d = root / "class/power_supply" / name
    d.mkdir(parents=True)
    for key, value in files.items():
        (d / key).write_text(f"{value}\n")


def test_time_left_on_battery_and_to_full(tmp_path):
    # AYANEO: energy in µWh, power in µW
    supply(tmp_path, "BAT0", type="Battery", status="Discharging", capacity=64,
           energy_now=30_000_000, energy_full=47_000_000, power_now=12_000_000)
    state = read_battery(tmp_path)
    assert state.minutes == 150 and state.label == "🔋 64% · 2:30"
    other = tmp_path / "b"
    supply(other, "BAT0", type="Battery", status="Charging", capacity=64,
           energy_now=30_000_000, energy_full=47_000_000, power_now=17_000_000)
    assert read_battery(other).label == "⚡ 64% · 1:00 to full"
    idle = tmp_path / "c"
    supply(idle, "BAT0", type="Battery", status="Full", capacity=100, energy_now=1, energy_full=1, power_now=0)
    assert read_battery(idle).label == "⚡ 100%"  # nothing to count


def test_toasts_wait_while_hidden(qtbot):
    from PySide6.QtWidgets import QWidget

    host = QWidget()
    qtbot.addWidget(host)
    host.resize(1280, 800)
    toasts = Toasts(host)
    toasts.notify("Download finished: Hades", "⬇")
    assert not toasts.isVisible() and toasts.shown == []  # a game is in front
    host.show()
    toasts.flush()
    assert toasts.isVisible() and toasts.text.text() == "Download finished: Hades"
    assert toasts.x() + toasts.width() <= host.width()


def test_monitor_notices_once_per_discharge(qtbot):
    states = [BatteryState(20, False, False), BatteryState(15, False, False), BatteryState(14, False, False),
              BatteryState(10, False, False), BatteryState(9, False, False), BatteryState(9, True, True),
              BatteryState(14, False, False)]
    monitor = BatteryMonitor(lambda: states.pop(0), interval_ms=60_000)
    events = []
    monitor.notice.connect(lambda p: events.append(("notice", p)))
    monitor.warning.connect(lambda p: events.append(("warning", p)))
    for _ in range(7):
        monitor.check()
    assert events == [("notice", 15), ("warning", 10), ("notice", 14)]  # plugged in -> fresh again


def test_again_at_5_percent(qtbot):
    states = [BatteryState(15, False, False), BatteryState(6, False, False), BatteryState(5, False, False),
              BatteryState(3, False, False), BatteryState(50, True, True), BatteryState(4, False, False)]
    monitor = BatteryMonitor(lambda: states.pop(0), interval_ms=60_000)
    events = []
    for name in ("notice", "warning", "critical"):
        getattr(monitor, name).connect(lambda p, n=name: events.append((n, p)))
    for _ in range(6):
        monitor.check()
    assert events == [("notice", 15), ("warning", 6), ("critical", 5),  # once each
                      ("critical", 4), ("warning", 4)]  # plugged in, then straight down to 4 %: both again


def test_red_border_and_message_for_10_seconds(qtbot, monkeypatch):
    from PySide6.QtWidgets import QWidget

    from gamingcrypt.ui import battery_edge

    monkeypatch.setattr(battery_edge, "SHOW_MS", 100)
    host = QWidget()
    qtbot.addWidget(host)
    host.resize(1280, 800)
    host.show()
    edge = battery_edge.BatteryEdge(host)
    edge.alert(15)
    assert edge.isVisible() and edge.geometry() == host.rect()
    assert edge.text.text() == "Battery at 15 % - plug in the charger"
    card = edge.card.geometry()
    assert card.right() < 1280 and card.top() < 60 and card.left() > 640  # at the top right
    image = edge.grab().toImage()
    assert image.pixelColor(5, 400).name() == battery_edge.RED and image.pixelColor(1275, 400).name() == battery_edge.RED
    assert edge.testAttribute(battery_edge.Qt.WidgetAttribute.WA_TransparentForMouseEvents)  # never in the way
    qtbot.waitUntil(lambda: not edge.isVisible(), timeout=2000)


def test_over_a_game_it_is_gamescopes_overlay(qtbot, monkeypatch):
    from gamingcrypt.ui import battery_edge

    monkeypatch.setattr(battery_edge, "SHOW_MS", 100)
    monkeypatch.setattr(battery_edge, "UNMAP_DELAY_MS", 10)
    marked = []
    overlay = battery_edge.GameBatteryEdge(mark_overlay=lambda wid: marked.append(wid) or True)
    qtbot.addWidget(overlay)
    overlay.alert(5)
    assert overlay.isVisible() and marked == [int(overlay.winId())] and overlay.edge.text.text().startswith(
        "Battery at 5 %")
    overlay.alert(5)
    assert len(marked) == 1  # marked once
    qtbot.waitUntil(lambda: not overlay.isVisible(), timeout=2000)  # gone after the time (drawn empty first)


def test_the_app_shows_it(qtbot, monkeypatch):
    import copy

    from gamingcrypt.app import MainWindow
    from gamingcrypt.config import DEFAULTS
    from gamingcrypt.ui import battery_edge

    w = MainWindow(copy.deepcopy(DEFAULTS), lambda c: None)
    qtbot.addWidget(w)
    w.windowed = True
    w.show()
    w.battery_monitor.notice.emit(15)
    assert w.battery_edge.isVisible()  # desktop: over GamingCrypt
    shown = []
    monkeypatch.setenv("GAMINGCRYPT_SESSION", "1")
    monkeypatch.setattr(battery_edge.GameBatteryEdge, "alert", lambda self, p: shown.append(p))
    w.battery_monitor.critical.emit(5)
    assert shown == [5]  # gaming mode: gamescope draws it over everything, also a game


def test_warning_counts_down_to_sleep(qtbot, monkeypatch):
    from PySide6.QtWidgets import QWidget

    from gamingcrypt.ui import battery_warning

    monkeypatch.setattr(battery_warning, "COUNTDOWN_S", 2)
    host = QWidget()
    qtbot.addWidget(host)
    host.show()
    warning = BatteryWarning(host)
    slept = []
    warning.sleep_now.connect(lambda: slept.append(1))
    warning.open(10)
    assert "Going to sleep in 0:02" in warning.text.text() and host.focusWidget() is warning.keep_button
    qtbot.waitUntil(lambda: slept == [1], timeout=4000)
    assert not warning.isVisible()
    kept = []
    warning.dismissed.connect(lambda: kept.append(1))
    warning.open(9)
    assert warning.gamepad_back() and kept == [1] and not warning.timer.isActive()


class Download:
    def __init__(self, appid, name, is_update=False):
        self.appid, self.name, self.is_update = appid, name, is_update


def test_download_notices(qtbot):
    lists = [[Download(1, "Hades"), Download(2, "Celeste", True)],
             [Download(2, "Celeste", True), Download(3, "Portal 2", True), Download(4, "Doom", True)],
             []]
    installed = {1}
    notifier = DownloadNotifier(lambda: lists.pop(0), lambda appid: appid in installed, interval_ms=60_000)
    got = []
    notifier.message.connect(lambda icon, text: got.append(text))
    notifier.poll()
    qtbot.waitUntil(lambda: not notifier.busy)
    assert got == ["Update available for Celeste"]
    notifier.poll()
    qtbot.waitUntil(lambda: not notifier.busy)
    assert got[1:] == ["Download finished: Hades", "Updates available for 2 games"]
    notifier.poll()  # cancelled ones (not installed) aren't "finished"
    qtbot.waitUntil(lambda: not notifier.busy)
    assert len(got) == 3


@pytest.fixture
def window(qtbot, monkeypatch):
    from gamingcrypt.app import MainWindow
    from gamingcrypt.config import DEFAULTS
    from gamingcrypt.system import gamescope_ctl, sleep

    monkeypatch.setattr(gamescope_ctl, "set_focus_order", lambda order: True)
    monkeypatch.setattr(gamescope_ctl, "set_window_appid", lambda wid: True)
    w = MainWindow(copy.deepcopy(DEFAULTS), lambda c: None)
    qtbot.addWidget(w)
    w.windowed = True
    w._slept = []
    monkeypatch.setattr(sleep, "suspend", lambda: w._slept.append(1) or (True, ""))
    return w


def test_low_battery_comes_in_front_of_the_game(qtbot, window):
    asides = []
    window.step_aside = lambda front="steam": asides.append(front)
    window.game_watcher.appid, window.game_watcher.phase = 620, "playing"
    window.warn_battery(10)  # hidden: a game is in front
    assert window.isVisible() and window.battery_warning.isVisible()
    assert window.nav_root() is window.battery_warning
    window.battery_warning.keep_button.click()
    assert asides == ["game"]  # straight back into the game
    window.warn_battery(8)
    window.battery_warning.sleep_button.click()
    qtbot.waitUntil(lambda: window._slept == [1])
    window.game_watcher._stop()


def test_notices_show_in_the_window(qtbot, window):
    window.show()
    window.notify("Download finished: Hades", "⬇")
    assert window.toasts.isVisible() and window.toasts.shown == ["Download finished: Hades"]
