"""Background thread: physical controller (grabbed) -> Translator -> virtual pad."""

from __future__ import annotations

import threading
from typing import Callable

from gamingcrypt.input import evdev as e
from gamingcrypt.input.profile import Profile, Translator

ABS_CODES = [e.ABS_X, e.ABS_Y, e.ABS_Z, e.ABS_RX, e.ABS_RY, e.ABS_RZ, e.ABS_GAS, e.ABS_BRAKE,
             e.ABS_HAT0X, e.ABS_HAT0Y]


def read_absinfo(device: e.InputDevice, codes: set[int]) -> dict[int, e.AbsInfo]:
    result = {}
    for code in ABS_CODES:
        if code in codes:
            info = device.absinfo(code)
            if info is not None:
                result[code] = info
    return result


class Remapper:
    def __init__(self, info: e.DeviceInfo, profile: Profile,
                 open_device: Callable[[str], e.InputDevice] = e.InputDevice,
                 make_uinput: Callable[[], e.UInput] = e.UInput):
        self.info = info
        self.profile = profile
        self.open_device = open_device
        self.make_uinput = make_uinput
        self.error = ""
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, timeout: float = 2.0) -> bool:
        """Start; returns False (with ``error`` set) if the device or uinput can't be opened."""
        self._stop.clear()
        self._ready.clear()
        self._thread = threading.Thread(target=self._run, name="gamingcrypt-remapper", daemon=True)
        self._thread.start()
        self._ready.wait(timeout)
        return self.running and not self.error

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(2)
        self._thread = None

    def _run(self) -> None:
        device = virtual = None
        try:
            device = self.open_device(self.info.path)
            translator = Translator(self.profile, read_absinfo(device, self.info.axes))
            virtual = self.make_uinput()
            device.grab()  # games must only see the remapped controller
            virtual.emit(translator.feed(e.EV_SYN, e.SYN_REPORT, 0))  # initial neutral state
        except OSError as exc:
            self.error = f"{exc.strerror or exc} ({getattr(exc, 'filename', '') or self.info.path})"
            self._ready.set()
            for res in (virtual, device):
                if res is not None:
                    res.close()
            return
        self._ready.set()
        try:
            while not self._stop.is_set():
                try:
                    events = device.read(0.1)
                except OSError as exc:  # controller unplugged
                    self.error = str(exc)
                    break
                out = []
                for event in events:
                    out.extend(translator.feed(*event))
                virtual.emit(out)
        finally:
            device.close()
            virtual.close()
