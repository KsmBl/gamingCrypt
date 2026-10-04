"""Screen resolution and refresh rate through the compositor's own tool.

Supported: kscreen-doctor (KDE Plasma), wlr-randr (Sway, Hyprland, other
wlroots compositors) and xrandr (X11).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Callable

Runner = Callable[..., subprocess.CompletedProcess]


@dataclass(frozen=True)
class Mode:
    width: int
    height: int
    refresh: float
    mode_id: str = field(default="", compare=False)

    @property
    def resolution(self) -> str:
        return f"{self.width}×{self.height}"

    @property
    def refresh_label(self) -> str:
        return f"{round(self.refresh)} Hz"


@dataclass
class Output:
    name: str
    description: str
    modes: list[Mode]
    current: Mode | None

    def resolutions(self) -> list[tuple[int, int]]:
        sizes = sorted({(m.width, m.height) for m in self.modes}, key=lambda s: (s[0] * s[1], s[0]), reverse=True)
        return sizes

    def refresh_rates(self, width: int, height: int) -> list[Mode]:
        modes = [m for m in self.modes if (m.width, m.height) == (width, height)]
        unique: dict[int, Mode] = {}
        for m in sorted(modes, key=lambda m: m.refresh, reverse=True):
            unique.setdefault(round(m.refresh), m)
        return list(unique.values())


def _run(runner: Runner, cmd: list[str]) -> subprocess.CompletedProcess | None:
    try:
        return runner(cmd, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None


class DisplayBackend:
    name = ""

    def __init__(self, runner: Runner = subprocess.run):
        self.runner = runner

    def outputs(self) -> list[Output]:
        raise NotImplementedError

    def mode_command(self, output: Output, mode: Mode) -> list[str]:
        raise NotImplementedError

    def set_mode(self, output: Output, mode: Mode) -> tuple[bool, str]:
        result = _run(self.runner, self.mode_command(output, mode))
        if result is None:
            return False, f"{self.name} could not be run"
        if result.returncode != 0:
            return False, (result.stderr or result.stdout or "").strip() or f"{self.name} failed"
        return True, f"{mode.resolution} @ {mode.refresh_label}"


class WlrRandr(DisplayBackend):
    name = "wlr-randr"

    def outputs(self) -> list[Output]:
        result = _run(self.runner, ["wlr-randr", "--json"])
        if result is None or result.returncode != 0:
            return []
        try:
            data = json.loads(result.stdout)
        except ValueError:
            return []
        outputs = []
        for o in data:
            if not o.get("enabled", True):
                continue
            modes = [Mode(int(m["width"]), int(m["height"]), float(m["refresh"])) for m in o.get("modes", [])]
            current = next((Mode(int(m["width"]), int(m["height"]), float(m["refresh"]))
                            for m in o.get("modes", []) if m.get("current")), None)
            outputs.append(Output(o["name"], o.get("description") or o["name"], modes, current))
        return outputs

    def mode_command(self, output: Output, mode: Mode) -> list[str]:
        return ["wlr-randr", "--output", output.name, "--mode", f"{mode.width}x{mode.height}@{mode.refresh:.6f}Hz"]


XRANDR_OUTPUT = re.compile(r"^(\S+) connected")
XRANDR_MODE = re.compile(r"^\s+(\d+)x(\d+)\S*\s+(.*)$")
XRANDR_RATE = re.compile(r"(\d+(?:\.\d+)?)([ *+]*)")


class Xrandr(DisplayBackend):
    name = "xrandr"

    def outputs(self) -> list[Output]:
        result = _run(self.runner, ["xrandr", "--query"])
        if result is None or result.returncode != 0:
            return []
        outputs: list[Output] = []
        current: Output | None = None
        for line in result.stdout.splitlines():
            head = XRANDR_OUTPUT.match(line)
            if head:
                current = Output(head.group(1), head.group(1), [], None)
                outputs.append(current)
                continue
            if line and not line[0].isspace():
                current = None  # disconnected output
                continue
            mode_line = XRANDR_MODE.match(line)
            if current is None or not mode_line:
                continue
            w, h = int(mode_line.group(1)), int(mode_line.group(2))
            for rate, flags in XRANDR_RATE.findall(mode_line.group(3)):
                mode = Mode(w, h, float(rate))
                current.modes.append(mode)
                if "*" in flags:
                    current.current = mode
        return [o for o in outputs if o.modes]

    def mode_command(self, output: Output, mode: Mode) -> list[str]:
        return ["xrandr", "--output", output.name, "--mode", f"{mode.width}x{mode.height}",
                "--rate", f"{mode.refresh:.2f}"]


class KScreen(DisplayBackend):
    name = "kscreen-doctor"

    def outputs(self) -> list[Output]:
        result = _run(self.runner, ["kscreen-doctor", "-j"])
        if result is None or result.returncode != 0:
            return []
        try:
            data = json.loads(result.stdout)
        except ValueError:
            return []
        outputs = []
        for o in data.get("outputs", []):
            if not o.get("connected", True) or not o.get("enabled", True):
                continue
            modes, current = [], None
            for m in o.get("modes", []):
                size = m.get("size", {})
                mode = Mode(int(size.get("width", 0)), int(size.get("height", 0)), float(m.get("refreshRate", 0)),
                            str(m.get("id", "")))
                modes.append(mode)
                if str(m.get("id")) == str(o.get("currentModeId")):
                    current = mode
            outputs.append(Output(o["name"], o.get("name"), modes, current))
        return outputs

    def mode_command(self, output: Output, mode: Mode) -> list[str]:
        return ["kscreen-doctor", f"output.{output.name}.mode.{mode.mode_id}"]


def detect(env: dict | None = None, which: Callable[[str], str | None] = shutil.which,
           runner: Runner = subprocess.run) -> DisplayBackend | None:
    env = os.environ if env is None else env
    desktop = env.get("XDG_CURRENT_DESKTOP", "").upper()
    if "GAMESCOPE" in desktop or env.get("GAMESCOPE_WAYLAND_DISPLAY"):
        return None  # gamescope decides the output mode itself
    if "KDE" in desktop and which("kscreen-doctor"):
        return KScreen(runner)
    if env.get("WAYLAND_DISPLAY") and which("wlr-randr"):
        return WlrRandr(runner)
    if env.get("DISPLAY") and not env.get("WAYLAND_DISPLAY") and which("xrandr"):
        return Xrandr(runner)
    return None
