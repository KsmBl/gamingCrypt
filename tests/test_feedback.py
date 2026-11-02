"""Sounds and rumble: what plays when, that both can be off, and how a controller is made to rumble."""

import struct
import wave
from types import SimpleNamespace

import pytest

from gamingcrypt.input import evdev as e
from gamingcrypt.ui import feedback


class Process:
    def __init__(self):
        self.done = False

    def poll(self):
        return 0 if self.done else None


@pytest.fixture
def setup(tmp_path):
    played, shaken, clock = [], [], [0.0]
    processes = []

    def popen(args, **_kw):
        played.append(args)
        processes.append(Process())
        return processes[-1]

    config = {"appearance": {}}
    made = feedback.Feedback(config, tmp_path / "sounds", rumble=lambda *a: shaken.append(a),
                             which=lambda name: f"/usr/bin/{name}" if name == "paplay" else None,
                             popen=popen, clock=lambda: clock[0])
    return SimpleNamespace(made=made, config=config, played=played, shaken=shaken, clock=clock, processes=processes)


@pytest.mark.parametrize("name", sorted(feedback.SOUNDS))
def test_every_sound_is_a_short_quiet_wav(tmp_path, name):
    path = feedback.sound_file(tmp_path, name)
    with wave.open(str(path)) as sound:
        assert sound.getframerate() == feedback.RATE and sound.getnchannels() == 1
        assert sound.getnframes() / feedback.RATE < 0.45
        values = struct.unpack(f"<{sound.getnframes()}h", sound.readframes(sound.getnframes()))
    assert 0.03 * 32767 < max(map(abs, values)) < 0.25 * 32767


def test_plays_with_what_there_is_and_keeps_no_finished_process(setup):
    setup.made.play("select")
    assert setup.played[0][0] == "/usr/bin/paplay" and setup.played[0][1].endswith("select-1.wav")
    setup.processes[0].done = True
    setup.made.play("back")
    assert len(setup.made.running) == 1


def test_only_a_game_start_and_errors_rumble(setup):
    setup.made.play("select")
    setup.made.play("move")
    assert setup.shaken == []
    setup.made.play("launch")
    setup.made.play("error")
    assert setup.shaken == [feedback.RUMBLES["launch"], feedback.RUMBLES["error"]]


def test_both_can_be_switched_off_each_on_its_own(setup):
    setup.config["appearance"]["sounds"] = False
    setup.made.play("launch")
    assert setup.played == [] and len(setup.shaken) == 1
    setup.config["appearance"].update(sounds=True, rumble=False)
    setup.made.play("launch")
    assert len(setup.played) == 1 and len(setup.shaken) == 1


def test_silent_while_a_game_is_in_front(setup):
    setup.made.visible = lambda: False
    setup.made.play("error")
    assert setup.played == [] and setup.shaken == []


def test_holding_the_dpad_doesnt_pile_up(setup):
    setup.made.play("move")
    setup.clock[0] += 0.03
    setup.made.play("move")
    setup.clock[0] += 0.05
    setup.made.play("move")
    assert len(setup.played) == 2


def test_nothing_to_play_with_is_no_problem(tmp_path):
    made = feedback.Feedback({}, tmp_path, which=lambda _n: None)
    made.play("select")
    assert not tmp_path.joinpath("select-1.wav").exists()


def test_without_configure_nothing_happens():
    feedback.configure(None)
    feedback.play("launch")


# --- the navigator ---------------------------------------------------------------------------
@pytest.fixture
def heard(monkeypatch):
    names = []
    monkeypatch.setattr(feedback, "play", names.append)
    return names


def test_navigator_ticks_only_when_the_highlight_moved(qtbot, heard):
    from PySide6.QtWidgets import QPushButton, QVBoxLayout, QWidget

    from gamingcrypt.ui.navigator import GamepadNavigator

    window = QWidget()
    qtbot.addWidget(window)
    layout = QVBoxLayout(window)
    first, second = QPushButton("1"), QPushButton("2")
    layout.addWidget(first)
    layout.addWidget(second)
    window.show()
    qtbot.waitExposed(window)
    first.setFocus()
    nav = GamepadNavigator(window)
    nav._step(0, 1)
    assert window.focusWidget() is second and heard == ["move"]
    nav._step(0, 1)  # the end of the list
    assert heard == ["move"]
    nav.activate()
    assert heard == ["move", "select"]
    nav.back()  # nothing to go back from
    assert heard == ["move", "select"]
    window.gamepad_back = lambda: True
    nav.back()
    assert heard == ["move", "select", "back"]


def test_a_red_status_sounds(qtbot, heard):
    from PySide6.QtWidgets import QLabel

    from gamingcrypt.ui.widgets import set_status

    label = QLabel()
    qtbot.addWidget(label)
    set_status(label, "Fine")
    set_status(label, "", error=True)
    assert heard == []
    set_status(label, "Broken", error=True)
    assert heard == ["error"]


# --- the controller --------------------------------------------------------------------------
def test_effect_has_the_kernels_size():
    assert struct.calcsize(e.FF_EFFECT_FORMAT) == (48 if struct.calcsize("P") == 8 else 44)


def test_rumble_uploads_plays_and_removes(monkeypatch):
    calls = []

    def ioctl(_fd, request, arg):
        calls.append((request, bytes(arg) if isinstance(arg, bytearray) else arg))
        if isinstance(arg, bytearray):
            struct.pack_into("h", arg, 2, 7)  # the kernel's id for it
        return 0

    monkeypatch.setattr(e.fcntl, "ioctl", ioctl)
    written = []
    monkeypatch.setattr(e.os, "write", lambda _fd, data: written.append(data))
    device = e.InputDevice.__new__(e.InputDevice)
    device.fd = 5
    slept = []
    device.rumble(0x6000, 0x3000, 180, sleep=slept.append)
    fields = struct.unpack(e.FF_EFFECT_FORMAT, calls[0][1])
    assert calls[0][0] == e.EVIOCSFF and fields[0] == e.FF_RUMBLE and fields[1] == -1
    assert fields[5] == 180 and fields[-2:] == (0x6000, 0x3000)  # replay.length; strong, weak
    assert written == [e.pack_event(e.EV_FF, 7, 1)] and slept == [0.18]
    assert calls[1] == (e.EVIOCRMFF, 7)


def test_rumble_is_removed_even_when_playing_fails(monkeypatch):
    calls = []

    def ioctl(_fd, request, arg):
        calls.append(request)
        if isinstance(arg, bytearray):
            struct.pack_into("h", arg, 2, 3)
        return 0

    monkeypatch.setattr(e.fcntl, "ioctl", ioctl)

    def fail(_fd, _data):
        raise OSError("gone")

    monkeypatch.setattr(e.os, "write", fail)
    device = e.InputDevice.__new__(e.InputDevice)
    device.fd = 5
    with pytest.raises(OSError):
        device.rumble(1, 1, 10, sleep=lambda _s: None)
    assert calls == [e.EVIOCSFF, e.EVIOCRMFF]


def test_a_device_that_can_rumble_is_recognised(tmp_path):
    sys_root, dev_root = tmp_path / "sys", tmp_path / "dev"
    for number, ev in ((0, "20000b"), (1, "b")):  # 0x20_0000 is EV_FF's bit
        device = sys_root / "class/input" / f"event{number}" / "device"
        (device / "capabilities").mkdir(parents=True)
        (device / "name").write_text("Pad")
        (device / "capabilities/ev").write_text(ev)
    found = e.list_devices(sys_root, dev_root)
    assert [d.rumbles for d in found] == [True, False]


def test_a_mapped_controller_rumbles_through_the_remappers_handle(monkeypatch):
    """Its handle grabbed the controller: the kernel ignores what any other handle writes."""
    import threading

    from gamingcrypt.input.remapper import Remapper
    from gamingcrypt.input.service import InputService

    done = threading.Event()

    class Device:
        calls = []

        def rumble(self, *args):
            self.calls.append(args)
            done.set()

    service = InputService({"input": {"enabled": True, "profiles": {}}}, lambda c: None, finder=lambda: [])
    mapper = Remapper.__new__(Remapper)
    pad, silent = e.DeviceInfo("/p", "Pad", rumbles=True), e.DeviceInfo("/q", "Old pad")
    mapper._pads = {"/p": (pad, Device(), None), "/q": (silent, object(), None)}
    service.remapper = mapper
    monkeypatch.setattr(InputService, "running", property(lambda self: True))
    opened = []
    monkeypatch.setattr(e, "InputDevice", lambda path: opened.append(path))
    service.rumble(1, 2, 3)
    assert done.wait(2) and Device.calls == [(1, 2, 3)] and opened == []


def test_settings_switch_sounds_and_rumble(qtbot, heard):
    from gamingcrypt.ui.system_settings import AppearanceSection

    config, saved = {"appearance": {}}, []
    section = AppearanceSection(config, saved.append)
    qtbot.addWidget(section)
    assert section.switches["sounds"][True].isChecked() and section.switches["rumble"][True].isChecked()
    section.switches["sounds"][False].click()
    assert config["appearance"]["sounds"] is False and saved and section.switches["sounds"][False].isChecked()
    assert heard == []
    section.switches["sounds"][True].click()
    assert config["appearance"]["sounds"] is True and heard == ["launch"]  # what it's like
