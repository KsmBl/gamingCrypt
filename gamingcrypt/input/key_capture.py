"""Reads every keyboard-like device for a moment - to record a device button."""

from __future__ import annotations

import os
import threading
from typing import Callable

from gamingcrypt.input import evdev as e


def capture_devices(devices: Callable[[], list[e.DeviceInfo]] = e.list_devices) -> list[e.DeviceInfo]:
    """Devices with keys that aren't controllers (those come through the UI's controller input)."""
    return [d for d in devices() if d.keys and not d.is_gamepad and d.name != e.VIRTUAL_NAME
            and os.access(d.path, os.R_OK)]


class KeyCapture:
    def __init__(self, on_event: Callable[[str, int, int], None],
                 devices: Callable[[], list[e.DeviceInfo]] = capture_devices,
                 open_device: Callable[[str], e.InputDevice] = e.InputDevice):
        self.on_event = on_event  # (device name, code, value) - from a thread
        self.devices = devices
        self.open_device = open_device
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.opened: list[tuple[str, object]] = []

    def start(self) -> int:
        for info in self.devices():
            try:
                self.opened.append((info.name, self.open_device(info.path)))
            except OSError:
                continue
        if self.opened:
            self._thread = threading.Thread(target=self._run, name="gamingcrypt-capture", daemon=True)
            self._thread.start()
        return len(self.opened)

    def _run(self) -> None:
        while not self._stop.is_set() and self.opened:
            for name, device in list(self.opened):
                try:
                    events = device.read(0.05)
                except OSError:
                    self.opened.remove((name, device))
                    continue
                for ev_type, code, value in events:
                    if ev_type == e.EV_KEY and value in (0, 1):
                        self.on_event(name, code, value)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(1)
        for _name, device in self.opened:
            device.close()
        self.opened = []
