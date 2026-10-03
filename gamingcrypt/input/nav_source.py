"""Controller input for navigating the GamingCrypt UI.

Delivers standard (Xbox layout) events from a background thread: from the
virtual controller when the user's mapping is active, otherwise from the
physical controller translated with the user's profile.
"""

from __future__ import annotations

import threading
import time
from typing import Callable

from gamingcrypt.input import evdev as e
from gamingcrypt.input.profile import Translator
from gamingcrypt.input.remapper import read_absinfo

Emit = Callable[[int, int, int], None]


class NavSource:
    RECHECK_S = 2.0

    def __init__(self, input_service, emit: Emit,
                 devices: Callable[[], list[e.DeviceInfo]] = e.list_devices,
                 open_device: Callable[[str], e.InputDevice] = e.InputDevice):
        self.input = input_service
        self.emit = emit
        self.devices = devices
        self.open_device = open_device
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def choose(self) -> tuple[e.DeviceInfo, bool] | None:
        """(device, is_virtual)."""
        if self.input.running:
            virtual = next((d for d in self.devices() if d.name == e.VIRTUAL_NAME), None)
            if virtual is not None:
                return virtual, True
        physical = self.input.device()
        return (physical, False) if physical is not None else None

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="gamingcrypt-nav", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(2)
        self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            choice = self.choose()
            if choice is None:
                self._stop.wait(self.RECHECK_S)
                continue
            info, virtual = choice
            try:
                device = self.open_device(info.path)
            except OSError:
                self._stop.wait(self.RECHECK_S)
                continue
            try:
                self._read(device, info, virtual)
            finally:
                device.close()

    def _read(self, device, info: e.DeviceInfo, virtual: bool) -> None:
        translator = None
        if not virtual:
            translator = Translator(self.input.profile(info), read_absinfo(device, info.axes))
        checked = time.monotonic()
        while not self._stop.is_set():
            try:
                events = device.read(0.1)
            except OSError:
                return  # unplugged -> choose again
            for event in events:
                if translator is None:
                    self.emit(*event)
                else:
                    for out in translator.feed(*event):
                        self.emit(*out)
            if time.monotonic() - checked > self.RECHECK_S:
                checked = time.monotonic()
                choice = self.choose()
                if choice is None or choice[0].path != info.path:
                    return  # mapping switched on/off or controller changed
