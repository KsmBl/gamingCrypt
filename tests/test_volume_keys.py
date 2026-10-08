import os
import subprocess
import time

import pytest

from gamingcrypt.input import evdev as e
from gamingcrypt.input.volume_keys import VolumeKeys
from gamingcrypt.system.audio import PulseAudio


def test_find_volume_key_devices(tmp_path):
    def device(n, name, keys, bus="0011"):
        d = tmp_path / f"sys/class/input/event{n}/device"
        (d / "capabilities").mkdir(parents=True)
        (d / "id").mkdir()
        (d / "name").write_text(name)
        bits = sum(1 << k for k in keys)
        (d / "capabilities/key").write_text(f"{bits:x}")
        (d / "capabilities/abs").write_text("0")
        (d / "id/bustype").write_text(bus)

    device(1, "AT Translated Set 2 keyboard", [e.KEY_VOLUMEUP, e.KEY_VOLUMEDOWN, 30])
    device(2, "Power Button", [116])
    device(3, "BT Keyboard", [e.KEY_VOLUMEUP], bus="0005")
    device(4, e.VIRTUAL_NAME, [e.KEY_VOLUMEUP])
    found = e.find_volume_key_devices(tmp_path / "sys", tmp_path / "dev")
    assert [d.name for d in found] == ["AT Translated Set 2 keyboard", "Power Button"]  # power: sleep


class FakeDevice:
    def __init__(self, batches):
        self.batches = list(batches)
        self.closed = False

    def read(self, timeout):
        if self.batches:
            return self.batches.pop(0)
        time.sleep(0.01)
        return []

    def close(self):
        self.closed = True


def test_reader_reports_presses_and_repeats():
    batches = [[(e.EV_KEY, e.KEY_VOLUMEUP, 1), (e.EV_SYN, 0, 0)],
               [(e.EV_KEY, e.KEY_VOLUMEUP, 2)],              # held -> repeat
               [(e.EV_KEY, e.KEY_VOLUMEUP, 0)],              # release: nothing
               [(e.EV_KEY, e.KEY_MUTE, 1), (e.EV_KEY, e.KEY_MUTE, 2)],  # held mute: once
               [(e.EV_KEY, 30, 1)],                          # other keys: ignored
               [(e.EV_KEY, e.KEY_VOLUMEDOWN, 1)]]
    device = FakeDevice(batches)
    got = []
    keys = VolumeKeys(got.append, finder=lambda: [e.DeviceInfo("/dev/input/event9", "Buttons")],
                      open_device=lambda path: device)
    assert keys.start()
    deadline = time.time() + 2
    while time.time() < deadline and len(got) < 4:
        time.sleep(0.01)
    keys.stop()
    assert got == [e.KEY_VOLUMEUP, e.KEY_VOLUMEUP, e.KEY_MUTE, e.KEY_VOLUMEDOWN]
    assert device.closed


def test_reader_without_permission():
    def denied(path):
        raise PermissionError(13, "Permission denied")

    keys = VolumeKeys(lambda c: None, finder=lambda: [e.DeviceInfo("/dev/input/event3", "AT kbd")],
                      open_device=denied)
    assert not keys.start() and "Permission denied" in keys.errors[0]
    assert not VolumeKeys(lambda c: None, finder=list).start()


class Pactl:
    def __init__(self, volume=60, muted=False):
        self.volume, self.muted, self.calls = volume, muted, []

    def __call__(self, cmd, **kw):
        self.calls.append(cmd[1:])
        args = cmd[1:]
        out = ""
        if args[0] == "get-sink-volume":
            out = f"Volume: front-left: 1 / {self.volume}% / -1 dB,   front-right: 1 / {self.volume}% / -1 dB\n"
        elif args[0] == "set-sink-volume":
            self.volume = int(args[2].rstrip("%"))
        elif args[0] == "set-sink-mute":
            self.muted = (not self.muted) if args[2] == "toggle" else args[2] == "1"
        elif args[0] == "get-sink-mute":
            out = f"Mute: {'yes' if self.muted else 'no'}\n"
        return subprocess.CompletedProcess(cmd, 0, out, "")


def test_volume_steps_stay_within_0_and_100_and_unmute():
    pactl = Pactl(volume=97, muted=True)
    audio = PulseAudio(pactl)
    assert audio.step_volume(5) == 100 and not pactl.muted  # louder unmutes
    assert audio.step_volume(5) == 100
    pactl.volume = 3
    assert audio.step_volume(-5) == 0
    assert ["set-sink-volume", "@DEFAULT_SINK@", "0%"] in pactl.calls
    assert audio.toggle_mute() is True and audio.toggle_mute() is False


def test_controller_shows_indicator(qtbot):
    from PySide6.QtWidgets import QWidget

    from gamingcrypt.ui.volume_osd import VolumeController, VolumeOsd

    host = QWidget()
    qtbot.addWidget(host)
    host.resize(1280, 800)
    host.show()
    pactl = Pactl(volume=60)
    osd = VolumeOsd(host)
    controller = VolumeController(PulseAudio(pactl), osd)
    controller.bridge.key.emit(e.KEY_VOLUMEUP)
    qtbot.waitUntil(lambda: osd.isVisible())
    assert osd.value.text() == "65%" and osd.bar.value() == 65 and pactl.volume == 65
    assert osd.x() == (1280 - osd.width()) // 2  # centred at the top
    controller.bridge.key.emit(e.KEY_MUTE)
    qtbot.waitUntil(lambda: osd.value.text() == "Muted")
    assert osd.icon.text() == "🔇"
    controller.bridge.key.emit(e.KEY_VOLUMEDOWN)
    qtbot.waitUntil(lambda: osd.value.text() == "60%")


def test_hidden_launcher_still_changes_volume(qtbot):
    from PySide6.QtWidgets import QWidget

    from gamingcrypt.ui.volume_osd import VolumeController, VolumeOsd

    host = QWidget()  # hidden: a game is in front
    qtbot.addWidget(host)
    pactl = Pactl(volume=50)
    controller = VolumeController(PulseAudio(pactl), VolumeOsd(host))
    controller.bridge.key.emit(e.KEY_VOLUMEDOWN)
    qtbot.waitUntil(lambda: pactl.volume == 45)
    assert not controller.osd.isVisible()


def test_only_active_in_gaming_mode(qtbot, monkeypatch):
    import copy

    from gamingcrypt.app import MainWindow
    from gamingcrypt.config import DEFAULTS
    from gamingcrypt.input import volume_keys
    from gamingcrypt.system.controls import SystemControls

    started = []

    class Keys:
        def __init__(self, on_key, finder=None, bindings=None):
            self.devices = ["dev"]
            self.errors = []

        def start(self):
            started.append(1)
            return True

    monkeypatch.setattr(volume_keys, "VolumeKeys", Keys)
    window = MainWindow(copy.deepcopy(DEFAULTS), lambda c: None, system=SystemControls(audio=PulseAudio(Pactl())))
    qtbot.addWidget(window)
    assert window.start_volume_keys() is None and started == []  # desktop: the compositor does it
    monkeypatch.setenv("GAMINGCRYPT_SESSION", "1")
    assert window.start_volume_keys() is not None and started == [1]


def test_cli_lists_volume_key_devices(capsys, monkeypatch, tmp_path):
    from gamingcrypt import app

    monkeypatch.setattr(e, "find_volume_key_devices", lambda: [e.DeviceInfo("/dev/x", "Handheld Buttons")])
    assert app.main(["--config", str(tmp_path / "c.json"), "--volume-key-devices"]) == 0
    assert capsys.readouterr().out == "Handheld Buttons\n"


@pytest.mark.skipif(not os.access("/dev/uinput", os.W_OK), reason="/dev/uinput not writable")
def test_real_volume_buttons():
    from tests.test_input import wait_for_device

    name = f"GC Volume Buttons {os.getpid()}"
    buttons = e.UInput(name=name, keys=[e.KEY_VOLUMEUP, e.KEY_VOLUMEDOWN, e.KEY_MUTE], axes=[])
    got = []
    keys = None
    try:
        info = wait_for_device(name)
        assert any(d.name == name for d in e.find_volume_key_devices())  # recognised as volume buttons
        keys = VolumeKeys(got.append, finder=lambda: [info])
        assert keys.start()
        buttons.emit([(e.EV_KEY, e.KEY_VOLUMEUP, 1), (e.EV_SYN, 0, 0), (e.EV_KEY, e.KEY_VOLUMEUP, 0),
                      (e.EV_SYN, 0, 0)])
        deadline = time.time() + 2
        while time.time() < deadline and not got:
            time.sleep(0.02)
        assert got == [e.KEY_VOLUMEUP]
    finally:
        if keys is not None:
            keys.stop()
        buttons.close()


def test_configurable_step_swapped_and_off(qtbot):
    from PySide6.QtWidgets import QWidget

    from gamingcrypt.ui.volume_osd import VolumeController, VolumeOsd, clamp_step

    host = QWidget()
    qtbot.addWidget(host)
    pactl = Pactl(volume=50)
    step = {"value": 10}
    controller = VolumeController(PulseAudio(pactl), VolumeOsd(host), step=lambda: step["value"])
    controller.bridge.key.emit(e.KEY_VOLUMEUP)
    qtbot.waitUntil(lambda: pactl.volume == 60)
    step["value"] = -2  # negative: + turns it down
    controller.bridge.key.emit(e.KEY_VOLUMEUP)
    qtbot.waitUntil(lambda: pactl.volume == 58)
    controller.bridge.key.emit(e.KEY_VOLUMEDOWN)
    qtbot.waitUntil(lambda: pactl.volume == 60)
    step["value"] = 0  # off
    controller.handle(e.KEY_VOLUMEUP)
    qtbot.wait(50)
    assert pactl.volume == 60
    assert clamp_step(99) == 10 and clamp_step(-99) == -10 and clamp_step("x") == 5


def test_indicator_over_an_emulated_game(qtbot, monkeypatch):
    """No Steam over emulators to show the volume: GamingCrypt's own overlay window (gamescope draws it on top)."""
    from PySide6.QtWidgets import QWidget

    from gamingcrypt.ui import volume_osd
    from gamingcrypt.ui.volume_osd import GameOverlay, VolumeController, VolumeOsd

    monkeypatch.setattr(volume_osd, "SHOW_MS", 200)
    host = QWidget()  # hidden: the game is in front
    qtbot.addWidget(host)
    marked = []
    overlay = GameOverlay(mark_overlay=lambda window: marked.append(window) or True)
    qtbot.addWidget(overlay)
    emulated = {"on": True}
    pactl = Pactl(volume=50)
    controller = VolumeController(PulseAudio(pactl), VolumeOsd(host), game_osd=overlay,
                                  use_game_osd=lambda: emulated["on"])
    controller.bridge.key.emit(e.KEY_VOLUMEUP)
    qtbot.waitUntil(lambda: overlay.isVisible())
    assert overlay.osd.value.text() == "55%" and marked == [int(overlay.winId())]
    qtbot.waitUntil(lambda: not overlay.isVisible(), timeout=3000)  # gone again
    controller.bridge.key.emit(e.KEY_VOLUMEUP)
    qtbot.waitUntil(lambda: overlay.isVisible())
    assert len(marked) == 1  # marked once
    overlay.hide()
    emulated["on"] = False  # a Steam game: Steam shows its own
    controller.bridge.key.emit(e.KEY_VOLUMEDOWN)
    qtbot.waitUntil(lambda: pactl.volume == 55)
    qtbot.wait(100)
    assert not overlay.isVisible()


def test_app_knows_when_an_emulated_game_is_in_front(qtbot, monkeypatch, tmp_path):
    import copy

    from gamingcrypt.app import MainWindow
    from gamingcrypt.config import DEFAULTS

    window = MainWindow(copy.deepcopy(DEFAULTS), lambda c: None, page_factory=lambda c: {})
    qtbot.addWidget(window)
    monkeypatch.setattr(window, "running_rom", lambda: object())
    window.hide()
    assert window.emulated_game_in_front()
    window.show()
    assert not window.emulated_game_in_front()  # GamingCrypt shows its own indicator
    window.hide()
    monkeypatch.setattr(window, "running_rom", lambda: None)
    assert not window.emulated_game_in_front()


def test_shown_as_a_notification_not_as_the_external_overlay():
    """gamescope draws one external overlay - the performance overlay (mangoapp): the volume
    over a game took its place, and it was gone. A notification (STEAM_OVERLAY, narrower than
    the screen) is drawn on a plane of its own."""
    import subprocess

    from PySide6.QtCore import QRect

    from gamingcrypt.system import gamescope_ctl

    calls = []
    run = lambda cmd, **kw: calls.append(cmd) or subprocess.CompletedProcess(cmd, 0, "", "")  # noqa: E731
    assert gamescope_ctl.set_notification_overlay(42, runner=run)
    assert calls[0] == ["xprop", "-id", "42", "-f", "STEAM_OVERLAY", "32c", "-set", "STEAM_OVERLAY", "1"]
    assert gamescope_ctl.notification_geometry(QRect(0, 0, 1280, 800)) == (0, 0, 1279, 800)


def test_game_overlays_use_the_notification_plane(qtbot):
    from gamingcrypt.system import gamescope_ctl
    from gamingcrypt.ui.battery_edge import GameBatteryEdge
    from gamingcrypt.ui.volume_osd import GameOverlay

    for overlay in (GameOverlay(), GameBatteryEdge()):
        qtbot.addWidget(overlay)
        assert overlay.mark_overlay is gamescope_ctl.set_notification_overlay


def test_game_overlay_is_drawn_empty_before_it_is_hidden(qtbot, monkeypatch):
    """gamescope keeps showing an overlay's last picture after it's hidden (seen on the handheld:
    the volume popup stayed over GamingCrypt after a movie)."""
    from PySide6.QtWidgets import QWidget

    from gamingcrypt.ui import volume_osd
    from gamingcrypt.ui.volume_osd import GameOverlay

    monkeypatch.setattr(volume_osd, "UNMAP_DELAY_MS", 150)
    overlay = GameOverlay(mark_overlay=lambda window: True)
    qtbot.addWidget(overlay)
    events = []
    original_hide = QWidget.hide
    monkeypatch.setattr(GameOverlay, "hide", lambda self: (events.append(("hide", self.osd.isVisible())),
                                                           original_hide(self))[1])
    overlay.show_level(40)
    overlay.dismiss()
    assert not overlay.osd.isVisible() and overlay.isVisible()  # empty, still mapped
    qtbot.waitUntil(lambda: not overlay.isVisible(), timeout=2000)
    assert events == [("hide", False)]
    overlay.show_level(40)
    overlay.dismiss()
    overlay.show_level(50)  # shown again before it was hidden: stays
    qtbot.wait(300)
    assert overlay.isVisible() and overlay.osd.isVisible()
    overlay.dismiss()
    overlay.dismiss()  # twice is fine
    qtbot.waitUntil(lambda: not overlay.isVisible(), timeout=2000)
