import json
import subprocess
from pathlib import Path

import pytest

from gamingcrypt.helper import veracrypt_helper
from gamingcrypt.system import audio, brightness, display, power
from gamingcrypt.system.controls import SystemControls


class Runner:
    """Maps the command (joined) to (rc, stdout); records every call."""

    def __init__(self, routes=None, default=(0, "")):
        self.routes = routes or {}
        self.default = default
        self.calls = []

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        joined = " ".join(cmd)
        for prefix, (rc, out) in self.routes.items():
            if joined.startswith(prefix):
                return subprocess.CompletedProcess(cmd, rc, out, "boom" if rc else "")
        rc, out = self.default
        return subprocess.CompletedProcess(cmd, rc, out, "")


# --- display -------------------------------------------------------------------

WLR = json.dumps([{"name": "eDP-1", "description": "Panel", "enabled": True, "modes": [
    {"width": 1920, "height": 1080, "refresh": 60.008, "preferred": True, "current": True},
    {"width": 1920, "height": 1080, "refresh": 48.006, "preferred": False, "current": False},
    {"width": 1280, "height": 800, "refresh": 90.0, "preferred": False, "current": False},
    {"width": 1280, "height": 800, "refresh": 59.95, "preferred": False, "current": False},
]}, {"name": "HDMI-A-1", "enabled": False, "modes": []}])

XRANDR = """Screen 0: minimum 320 x 200, current 1280 x 800, maximum 16384 x 16384
eDP connected primary 1280x800+0+0 (normal left inverted right x axis y axis) 0mm x 0mm
   1280x800      90.00 +  60.00*
   800x600       60.32
HDMI-A-0 disconnected (normal left inverted right x axis y axis)
   1024x768      60.00
"""

KSCREEN = json.dumps({"outputs": [{"name": "eDP-1", "connected": True, "enabled": True, "currentModeId": "2",
                                   "modes": [{"id": "1", "size": {"width": 1280, "height": 800}, "refreshRate": 90.0},
                                             {"id": "2", "size": {"width": 1280, "height": 800}, "refreshRate": 60.0}]},
                                  {"name": "DP-1", "connected": False, "enabled": False, "modes": []}]})


def test_wlr_randr_outputs_and_set():
    runner = Runner({"wlr-randr --json": (0, WLR)})
    backend = display.WlrRandr(runner)
    [out] = backend.outputs()
    assert out.name == "eDP-1" and out.current == display.Mode(1920, 1080, 60.008)
    assert out.resolutions() == [(1920, 1080), (1280, 800)]
    assert [m.refresh_label for m in out.refresh_rates(1280, 800)] == ["90 Hz", "60 Hz"]
    ok, msg = backend.set_mode(out, out.refresh_rates(1280, 800)[0])
    assert ok and msg == "1280×800 @ 90 Hz"
    assert runner.calls[-1] == ["wlr-randr", "--output", "eDP-1", "--mode", "1280x800@90.000000Hz"]


def test_xrandr_parse_and_set():
    runner = Runner({"xrandr --query": (0, XRANDR)})
    [out] = display.Xrandr(runner).outputs()
    assert out.name == "eDP" and out.current == display.Mode(1280, 800, 60.0)
    assert len(out.modes) == 3
    display.Xrandr(runner).set_mode(out, display.Mode(1280, 800, 90.0))
    assert runner.calls[-1] == ["xrandr", "--output", "eDP", "--mode", "1280x800", "--rate", "90.00"]


def test_kscreen_parse_and_set():
    runner = Runner({"kscreen-doctor -j": (0, KSCREEN)})
    backend = display.KScreen(runner)
    [out] = backend.outputs()
    assert out.current.refresh == 60.0
    backend.set_mode(out, out.refresh_rates(1280, 800)[0])
    assert runner.calls[-1] == ["kscreen-doctor", "output.eDP-1.mode.1"]


def test_display_errors():
    assert display.WlrRandr(Runner(default=(1, ""))).outputs() == []
    assert display.WlrRandr(Runner(default=(0, "not json"))).outputs() == []
    ok, msg = display.WlrRandr(Runner(default=(1, ""))).set_mode(
        display.Output("x", "x", [], None), display.Mode(1, 1, 60))
    assert not ok and msg == "wlr-randr failed"


@pytest.mark.parametrize("env,tools,expected", [
    ({"XDG_CURRENT_DESKTOP": "KDE", "WAYLAND_DISPLAY": "w"}, {"kscreen-doctor", "wlr-randr"}, "kscreen-doctor"),
    ({"WAYLAND_DISPLAY": "w"}, {"wlr-randr", "xrandr"}, "wlr-randr"),
    ({"DISPLAY": ":0"}, {"xrandr"}, "xrandr"),
    ({"WAYLAND_DISPLAY": "w", "DISPLAY": ":0"}, {"xrandr"}, None),  # xrandr can't change Wayland outputs
    ({}, set(), None),
])
def test_display_detect(env, tools, expected):
    backend = display.detect(env, lambda t: f"/usr/bin/{t}" if t in tools else None)
    assert (backend.name if backend else None) == expected


# --- audio ---------------------------------------------------------------------

SINKS = json.dumps([
    {"index": 1, "name": "speakers", "description": "Speakers", "mute": False,
     "volume": {"front-left": {"value_percent": "60%"}, "front-right": {"value_percent": "40%"}}},
    {"index": 2, "name": "headset", "description": "USB Headset", "mute": True,
     "volume": {"mono": {"value_percent": "80%"}}},
])
SOURCES = json.dumps([
    {"name": "speakers.monitor", "description": "Monitor of Speakers", "monitor_of_sink": "speakers", "volume": {}},
    {"name": "mic", "description": "Internal Mic", "monitor_of_sink": "n/a",
     "volume": {"mono": {"value_percent": "100%"}}},
])


def pactl_runner():
    return Runner({
        "pactl -f json list sinks": (0, SINKS),
        "pactl -f json list sources": (0, SOURCES),
        "pactl get-default-sink": (0, "speakers\n"),
        "pactl get-default-source": (0, "mic\n"),
        "pactl -f json list sink-inputs": (0, json.dumps([{"index": 7}, {"index": 9}])),
        "pactl -f json list source-outputs": (0, "[]"),
    })


def test_audio_devices():
    a = audio.PulseAudio(pactl_runner())
    outs = a.devices("output")
    assert [(d.name, d.volume, d.is_default, d.muted) for d in outs] == [
        ("speakers", 50, True, False), ("headset", 80, False, True)]
    assert [d.name for d in a.devices("input")] == ["mic"]  # monitors filtered


def test_audio_switch_moves_running_streams():
    runner = pactl_runner()
    assert audio.PulseAudio(runner).set_default("output", "headset")
    assert ["pactl", "set-default-sink", "headset"] in runner.calls
    assert ["pactl", "move-sink-input", "7", "headset"] in runner.calls
    assert ["pactl", "move-sink-input", "9", "headset"] in runner.calls


def test_audio_volume_and_errors():
    runner = pactl_runner()
    assert audio.PulseAudio(runner).set_volume("input", "mic", 250)
    assert runner.calls[-1] == ["pactl", "set-source-volume", "mic", "150%"]
    assert not audio.PulseAudio(Runner(default=(1, ""))).set_default("output", "x")
    assert audio.PulseAudio(Runner(default=(1, ""))).devices("output") == []
    assert audio.detect(lambda t: None) is None


# --- brightness ----------------------------------------------------------------

def test_brightness():
    runner = Runner({"brightnessctl -m": (0, "amdgpu_bl0,backlight,120,47%,255\n")})
    b = brightness.Brightness(runner)
    assert b.get() == 47
    assert b.set(1)
    assert runner.calls[-1] == ["brightnessctl", "-q", "--class=backlight", "set", "5%"]  # never black
    assert brightness.Brightness(Runner(default=(1, ""))).get() is None
    assert brightness.Brightness(Runner(default=(0, "garbage"))).get() is None


# --- power -----------------------------------------------------------------------

def amd_sys(tmp_path, current=15, low=4, high=30):
    hw = tmp_path / "sys/class/drm/card1/device/hwmon/hwmon3"
    hw.mkdir(parents=True)
    (hw / "power1_cap").write_text(f"{current * 10**6}\n")
    (hw / "power1_cap_min").write_text(f"{low * 10**6}\n")
    (hw / "power1_cap_max").write_text(f"{high * 10**6}\n")
    return tmp_path / "sys", hw / "power1_cap"


def intel_sys(tmp_path, current=22, rated=15):
    rapl = tmp_path / "sys/class/powercap/intel-rapl:0"
    rapl.mkdir(parents=True)
    (rapl / "constraint_0_power_limit_uw").write_text(f"{current * 10**6}\n")
    (rapl / "constraint_0_max_power_uw").write_text(f"{rated * 10**6}\n")
    return tmp_path / "sys", rapl / "constraint_0_power_limit_uw"


def test_read_amd_and_intel(tmp_path):
    root, _ = amd_sys(tmp_path / "a")
    assert power.read_limit(root) == power.PowerLimit(15, 4, 30, "amdgpu")
    root, _ = intel_sys(tmp_path / "i")
    assert power.read_limit(root) == power.PowerLimit(22, 3, 22, "intel-rapl")  # rated 15 < current 22
    assert power.read_limit(tmp_path / "none") is None


def test_power_set_through_helper(tmp_path):
    helper = tmp_path / "helper"
    runner = Runner()
    control = power.PowerControl(helper=str(helper), runner=runner)
    ok, msg = control.set(12)
    assert not ok and "install.sh" in msg
    helper.write_text("")
    assert control.set(12) == (True, "Power limit set to 12 W")
    assert runner.calls[-1] == ["sudo", "-n", str(helper), "power-limit", "12"]
    failing = power.PowerControl(helper=str(helper), runner=Runner(default=(2, "")))
    assert failing.set(12)[0] is False


def test_helper_power_limit_writes_within_bounds(tmp_path):
    root, cap = amd_sys(tmp_path)
    calls = []
    rc = veracrypt_helper.set_power_limit(["20"], sys_root=str(root), run=lambda cmd, **kw: calls.append(cmd),
                                          ryzenadj=str(tmp_path / "missing"))
    assert rc == 0 and cap.read_text() == str(20 * 10**6) and calls == []


def test_helper_power_limit_uses_ryzenadj_if_present(tmp_path):
    root, cap = amd_sys(tmp_path)
    ryzenadj = tmp_path / "ryzenadj"
    ryzenadj.write_text("")
    calls = []
    veracrypt_helper.set_power_limit(["8"], sys_root=str(root), run=lambda cmd, **kw: calls.append(cmd),
                                     ryzenadj=str(ryzenadj))
    assert calls == [[str(ryzenadj), "--stapm-limit=8000", "--fast-limit=8000", "--slow-limit=8000"]]


@pytest.mark.parametrize("args", [["31"], ["2"], ["abc"], ["-5"], [], ["10", "20"]])
def test_helper_power_limit_rejects(tmp_path, args):
    root, cap = amd_sys(tmp_path)
    assert veracrypt_helper.set_power_limit(args, sys_root=str(root), ryzenadj="") == 2
    assert cap.read_text().strip() == str(15 * 10**6)  # untouched


def test_helper_power_limit_intel_and_none(tmp_path):
    root, path = intel_sys(tmp_path / "i")
    assert veracrypt_helper.set_power_limit(["10"], sys_root=str(root), ryzenadj="") == 0
    assert path.read_text() == str(10 * 10**6)
    assert veracrypt_helper.set_power_limit(["10"], sys_root=str(tmp_path / "none"), ryzenadj="") == 2


def test_helper_main_dispatches_power_limit(monkeypatch):
    seen = []
    monkeypatch.setattr(veracrypt_helper, "set_power_limit", lambda args: seen.append(args) or 0)
    assert veracrypt_helper.main(["power-limit", "12"]) == 0 and seen == [["12"]]


# --- saved settings ----------------------------------------------------------------

class FakePower:
    def __init__(self, current=15):
        self.current = current
        self.sets = []

    def read(self):
        return power.PowerLimit(self.current, 3, 30, "amdgpu")

    def set(self, watts):
        self.sets.append(watts)
        return True, "ok"


def test_apply_saved():
    runner = Runner({"wlr-randr --json": (0, WLR)})
    p = FakePower()
    controls = SystemControls(display=display.WlrRandr(runner), power=p)
    problems = controls.apply_saved({"display": {"output": "eDP-1", "width": 1280, "height": 800, "refresh": 90.0},
                                     "power_limit_w": 10})
    assert problems == []
    assert runner.calls[-1][-1] == "1280x800@90.000000Hz" and p.sets == [10]


def test_apply_saved_skips_what_is_already_set_and_reports_missing():
    runner = Runner({"wlr-randr --json": (0, WLR)})
    p = FakePower(current=10)
    controls = SystemControls(display=display.WlrRandr(runner), power=p)
    assert controls.apply_saved({"display": {"output": "eDP-1", "width": 1920, "height": 1080, "refresh": 60},
                                 "power_limit_w": 10}) == []
    assert len(runner.calls) == 1 and p.sets == []
    problems = controls.apply_saved({"display": {"output": "DP-9", "width": 1, "height": 1, "refresh": 1}})
    assert problems == ["saved display mode is not available"]
    assert SystemControls().apply_saved({"display": None, "power_limit_w": None}) == []
