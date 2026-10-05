"""Hardware volume buttons, the Windows button (quick menu) and the power button
(sleep) in gaming mode.

gamescope doesn't handle them (on a desktop the compositor does), so GamingCrypt
reads them straight from the input devices - not grabbed, so they also work while
a game has the focus. Only used inside the gaming session.
"""

from __future__ import annotations

import threading
from typing import Callable

from gamingcrypt.input import evdev as e
from gamingcrypt.input import hotkeys

RELEASE, PRESS, REPEAT = 0, 1, 2


class VolumeKeys:
    def __init__(self, on_key: Callable[[int], None],
                 finder: Callable[[], list[e.DeviceInfo]] = e.find_volume_key_devices,
                 open_device: Callable[[str], e.InputDevice] = e.InputDevice,
                 bindings: dict | None = None):
        self.on_key = on_key
        self.finder = finder
        self.open_device = open_device
        self.devices: list = []
        self.errors: list[str] = []
        # device buttons (quick menu, lock now) on keyboard-like devices - see input/hotkeys
        self.tracker = hotkeys.Tracker(bindings if bindings is not None else dict(hotkeys.WINDOWS), hotkeys.KEY)
        self.consumed: set[int] = set()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> bool:
        """False if no volume buttons could be opened (e.g. no permission - see install.sh)."""
        for info in self.finder():
            try:
                self.devices.append(self.open_device(info.path))
            except OSError as exc:
                self.errors.append(f"{info.name}: {exc.strerror or exc}")
        if not self.devices:
            return False
        self._thread = threading.Thread(target=self._run, name="gamingcrypt-volume", daemon=True)
        self._thread.start()
        return True

    def _run(self) -> None:
        while not self._stop.is_set():
            for device in list(self.devices):
                try:
                    events = device.read(0.05)
                except OSError:
                    self.devices.remove(device)  # unplugged
                    continue
                for ev_type, code, value in events:
                    if ev_type == e.EV_KEY:
                        self._key(code, value)
            if not self.devices:
                return

    def _key(self, code: int, value: int) -> None:
        if value == RELEASE:
            self.tracker.feed(code, False)
            self.consumed.discard(code)
            return
        if value == PRESS:
            actions, consumed = self.tracker.feed(code, True)
            for action in actions:
                self.on_key(hotkeys.ACTION_CODES[action])  # quick menu / lock now
            if consumed:
                self.consumed.add(code)  # e.g. Volume Down of "Windows + Volume Down"
                return
        if code in self.consumed:
            return  # its key repeats belong to the combination too
        if code in e.VOLUME_KEYS:
            if code == e.KEY_MUTE and value == REPEAT:
                return  # holding mute must not flicker
            self.on_key(code)
        elif code == e.KEY_POWER and value == PRESS:
            self.on_key(code)  # once per press

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(1)
        for device in self.devices:
            device.close()
        self.devices = []
