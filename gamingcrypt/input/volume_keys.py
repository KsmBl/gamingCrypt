"""Hardware volume buttons in gaming mode.

gamescope doesn't handle them (on a desktop the compositor does), so GamingCrypt
reads them straight from the input devices - not grabbed, so they also work while
a game has the focus. Only used inside the gaming session.
"""

from __future__ import annotations

import threading
from typing import Callable

from gamingcrypt.input import evdev as e

PRESS, REPEAT = 1, 2


class VolumeKeys:
    def __init__(self, on_key: Callable[[int], None],
                 finder: Callable[[], list[e.DeviceInfo]] = e.find_volume_key_devices,
                 open_device: Callable[[str], e.InputDevice] = e.InputDevice):
        self.on_key = on_key
        self.finder = finder
        self.open_device = open_device
        self.devices: list = []
        self.errors: list[str] = []
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
                    if ev_type == e.EV_KEY and code in e.VOLUME_KEYS and value in (PRESS, REPEAT):
                        if code == e.KEY_MUTE and value == REPEAT:
                            continue  # holding mute must not flicker
                        self.on_key(code)
            if not self.devices:
                return

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(1)
        for device in self.devices:
            device.close()
        self.devices = []
