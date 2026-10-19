"""Background thread: physical controllers (grabbed) -> Translator -> one virtual pad.

Every connected controller feeds the same virtual pad, each translated with its own profile: a
controller connected over Bluetooth is found (looked for every few seconds) and works like the
built-in one - in the UI and as player 1 in games; one that goes away is let go, and the virtual
pad stays (player 1 keeps its place until it's back).
"""

from __future__ import annotations

import select
import threading
import time
from typing import Callable

from gamingcrypt.input import evdev as e
from gamingcrypt.input.profile import Profile, Translator

ABS_CODES = [e.ABS_X, e.ABS_Y, e.ABS_Z, e.ABS_RX, e.ABS_RY, e.ABS_RZ, e.ABS_GAS, e.ABS_BRAKE,
             e.ABS_HAT0X, e.ABS_HAT0Y]
RESCAN_S = 2.0  # how often new controllers are looked for


def read_absinfo(device: e.InputDevice, codes: set[int]) -> dict[int, e.AbsInfo]:
    result = {}
    for code in ABS_CODES:
        if code in codes:
            info = device.absinfo(code)
            if info is not None:
                result[code] = info
    return result


def neutral() -> list[tuple[int, int, int]]:
    """The virtual controller's state with nothing pressed or pushed."""
    events = [(e.EV_KEY, key, 0) for key in e.XBOX_KEYS]
    events += [(e.EV_ABS, axis.code, 0) for axis in e.XBOX_AXES]
    return events + [(e.EV_SYN, e.SYN_REPORT, 0)]


class Remapper:
    def __init__(self, info: e.DeviceInfo, profile: Profile,
                 open_device: Callable[[str], e.InputDevice] = e.InputDevice,
                 make_uinput: Callable[[], e.UInput] = e.UInput,
                 find: Callable[[], list[e.DeviceInfo]] | None = None,
                 profile_for: Callable[[e.DeviceInfo], Profile] | None = None):
        """info / profile: the controller it starts with; find: all controllers now (None: that
        one only), profile_for: each one's profile."""
        self.info = info
        self.profile = profile
        self.open_device = open_device
        self.make_uinput = make_uinput
        self.find = find
        self.profile_for = profile_for or (lambda _info: profile)
        self.error = ""
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._pads: dict[str, tuple[e.DeviceInfo, e.InputDevice, Translator]] = {}
        # set: the controller goes there instead of to the game (the on-screen keyboard over it)
        self.divert: Callable[[list[tuple[int, int, int]]], None] | None = None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def infos(self) -> list[e.DeviceInfo]:
        """The controllers read (and grabbed) right now."""
        return [info for info, _device, _translator in list(self._pads.values())]

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

    def _add(self, info: e.DeviceInfo, profile: Profile) -> None:
        """Opened, grabbed (games must only see the remapped controller) - OSError: not."""
        device = self.open_device(info.path)
        try:
            translator = Translator(profile, read_absinfo(device, info.axes))
            device.grab()
        except OSError:
            device.close()
            raise
        self._pads[info.path] = (info, device, translator)

    def _drop(self, path: str) -> None:
        _info, device, _translator = self._pads.pop(path)
        device.close()

    def _rescan(self) -> None:
        """Controllers connected meanwhile (Bluetooth): read too."""
        try:
            found = self.find() if self.find is not None else []
        except OSError:
            return
        for info in found:
            if info.path in self._pads or info.name == e.VIRTUAL_NAME:
                continue
            try:
                self._add(info, self.profile_for(info))
            except OSError:
                pass  # (not readable yet - next time)

    def _run(self) -> None:
        virtual = None
        try:
            self._add(self.info, self.profile)
            virtual = self.make_uinput()
            first = self._pads[self.info.path][2]
            virtual.emit(first.feed(e.EV_SYN, e.SYN_REPORT, 0))  # initial neutral state
        except OSError as exc:
            self.error = f"{exc.strerror or exc} ({getattr(exc, 'filename', '') or self.info.path})"
            self._ready.set()
            for path in list(self._pads):
                self._drop(path)
            if virtual is not None:
                virtual.close()
            return
        self._ready.set()
        rescan_at = time.monotonic() + RESCAN_S
        diverted = False
        try:
            while not self._stop.is_set():
                if self.find is not None and time.monotonic() >= rescan_at:
                    self._rescan()
                    rescan_at = time.monotonic() + RESCAN_S
                if not self._pads:
                    if self.find is None:
                        break  # (the one controller is gone)
                    self._stop.wait(0.1)
                    continue
                by_fd = {device.fd: path for path, (_info, device, _t) in self._pads.items()}
                try:
                    ready, _, _ = select.select(list(by_fd), [], [], 0.1)
                except (OSError, ValueError):
                    ready = list(by_fd)  # (one of them went away: read each, drop that one)
                out = []
                for fd in ready:
                    path = by_fd[fd]
                    _info, device, translator = self._pads[path]
                    try:
                        events = device.read(0)
                    except OSError as exc:  # unplugged / switched off
                        self.error = str(exc) if self.find is None else ""
                        self._drop(path)
                        continue
                    for event in events:
                        out.extend(translator.feed(*event))
                divert = self.divert
                if divert is not None and not diverted:
                    virtual.emit(neutral())  # the game sees everything let go meanwhile
                diverted = divert is not None
                if out and divert is not None:
                    divert(out)
                elif out:
                    virtual.emit(out)
        finally:
            for path in list(self._pads):
                self._drop(path)
            virtual.close()
