"""Audio devices and volume through ``pactl`` (PipeWire or PulseAudio)."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable

Runner = Callable[..., subprocess.CompletedProcess]
KINDS = {"output": ("sink", "sinks", "sink-inputs", "move-sink-input"),
         "input": ("source", "sources", "source-outputs", "move-source-output")}


@dataclass
class Device:
    name: str
    description: str
    volume: int
    muted: bool
    is_default: bool


class PulseAudio:
    def __init__(self, runner: Runner = subprocess.run):
        self.runner = runner

    def _run(self, *args: str) -> subprocess.CompletedProcess | None:
        try:
            return self.runner(["pactl", *args], capture_output=True, text=True, timeout=10)
        except (OSError, subprocess.SubprocessError):
            return None

    def _json(self, *args: str):
        result = self._run("-f", "json", *args)
        if result is None or result.returncode != 0:
            return []
        try:
            return json.loads(result.stdout)
        except ValueError:
            return []

    def default(self, kind: str) -> str:
        result = self._run(f"get-default-{KINDS[kind][0]}")
        return result.stdout.strip() if result is not None and result.returncode == 0 else ""

    def devices(self, kind: str) -> list[Device]:
        single, plural, _, _ = KINDS[kind]
        default = self.default(kind)
        devices = []
        for d in self._json("list", plural):
            name = d.get("name", "")
            if kind == "input" and (name.endswith(".monitor") or d.get("monitor_of_sink") not in (None, "n/a")):
                continue  # "Monitor of …" sources aren't microphones
            percents = []
            for channel in (d.get("volume") or {}).values():
                try:
                    percents.append(int(str(channel.get("value_percent", "0")).rstrip("%")))
                except (ValueError, AttributeError):
                    pass
            volume = round(sum(percents) / len(percents)) if percents else 0
            devices.append(Device(name, d.get("description") or name, volume, bool(d.get("mute")), name == default))
        return devices

    def set_default(self, kind: str, name: str) -> bool:
        single, _, streams, move = KINDS[kind]
        result = self._run(f"set-default-{single}", name)
        if result is None or result.returncode != 0:
            return False
        # Move what's already playing / recording, not only new streams.
        for stream in self._json("list", streams):
            if "index" in stream:
                self._run(move, str(stream["index"]), name)
        return True

    # volume buttons (always the current default output) -------------------------
    def default_volume(self) -> int | None:
        result = self._run("get-sink-volume", "@DEFAULT_SINK@")
        if result is None or result.returncode != 0:
            return None
        values = [int(v) for v in re.findall(r"(\d+)%", result.stdout)]
        return round(sum(values) / len(values)) if values else None

    def step_volume(self, delta: int) -> int | None:
        """Default output +/- ``delta`` percent, kept within 0-100. Returns the new level."""
        current = self.default_volume()
        if current is None:
            return None
        new = max(0, min(100, current + delta))
        result = self._run("set-sink-volume", "@DEFAULT_SINK@", f"{new}%")
        if result is None or result.returncode != 0:
            return None
        if delta > 0:
            self._run("set-sink-mute", "@DEFAULT_SINK@", "0")  # louder always unmutes
        return new

    def toggle_mute(self) -> bool | None:
        """Returns the new mute state."""
        result = self._run("set-sink-mute", "@DEFAULT_SINK@", "toggle")
        if result is None or result.returncode != 0:
            return None
        state = self._run("get-sink-mute", "@DEFAULT_SINK@")
        return state is not None and "yes" in (state.stdout or "").lower()

    def set_volume(self, kind: str, name: str, percent: int) -> bool:
        percent = max(0, min(150, int(percent)))
        result = self._run(f"set-{KINDS[kind][0]}-volume", name, f"{percent}%")
        return result is not None and result.returncode == 0


def detect(which: Callable[[str], str | None] = shutil.which, runner: Runner = subprocess.run) -> PulseAudio | None:
    return PulseAudio(runner) if which("pactl") else None
