"""Minimal pure-Python access to Linux input devices (evdev) and uinput.

No compiled dependency on purpose: handheld distros are often read-only and
have no compiler for python-evdev.
"""

from __future__ import annotations

import fcntl
import os
import select
import struct
from dataclasses import dataclass, field
from pathlib import Path

EV_SYN, EV_KEY, EV_ABS = 0x00, 0x01, 0x03
SYN_REPORT = 0

ABS_X, ABS_Y, ABS_Z, ABS_RX, ABS_RY, ABS_RZ = 0x00, 0x01, 0x02, 0x03, 0x04, 0x05
ABS_GAS, ABS_BRAKE = 0x09, 0x0A
ABS_HAT0X, ABS_HAT0Y = 0x10, 0x11

BTN_SOUTH, BTN_EAST, BTN_C, BTN_NORTH, BTN_WEST = 0x130, 0x131, 0x132, 0x133, 0x134
BTN_TL, BTN_TR, BTN_TL2, BTN_TR2 = 0x136, 0x137, 0x138, 0x139
BTN_SELECT, BTN_START, BTN_MODE, BTN_THUMBL, BTN_THUMBR = 0x13A, 0x13B, 0x13C, 0x13D, 0x13E
BTN_DPAD_UP, BTN_DPAD_DOWN, BTN_DPAD_LEFT, BTN_DPAD_RIGHT = 0x220, 0x221, 0x222, 0x223
BTN_GAMEPAD = BTN_SOUTH
KEY_MUTE, KEY_VOLUMEDOWN, KEY_VOLUMEUP = 113, 114, 115
KEY_LEFTMETA, KEY_RIGHTMETA = 125, 126  # the "Windows" button
KEY_POWER = 116
PANIC_COMBO = -1  # reported by VolumeKeys: Volume Down while the Windows button is held
VOLUME_KEYS = {KEY_MUTE, KEY_VOLUMEDOWN, KEY_VOLUMEUP}
MENU_KEYS = {KEY_LEFTMETA, KEY_RIGHTMETA}
BUS_BLUETOOTH = 0x05

EVENT_FORMAT = "llHHi"  # struct input_event (timeval, type, code, value)
EVENT_SIZE = struct.calcsize(EVENT_FORMAT)
ABSINFO_FORMAT = "6i"  # value, minimum, maximum, fuzz, flat, resolution

VIRTUAL_NAME = "GamingCrypt Virtual Controller"
# An Xbox 360 pad for everyone (SDL, Steam, Wine) - but not the id of the built-in pads (0x028E,
# wired): Wine games are told to skip the grabbed real one by its id, see InputService.game_env.
VIRTUAL_VENDOR, VIRTUAL_PRODUCT = 0x045E, 0x028F  # the 360 wireless pad on its charging cable
BUS_USB = 0x03


def _ioc(direction: int, kind: str, nr: int, size: int) -> int:
    return (direction << 30) | (size << 16) | (ord(kind) << 8) | nr


def _io(kind: str, nr: int) -> int:
    return _ioc(0, kind, nr, 0)


def _iow(kind: str, nr: int, size: int) -> int:
    return _ioc(1, kind, nr, size)


def _ior(kind: str, nr: int, size: int) -> int:
    return _ioc(2, kind, nr, size)


def EVIOCGABS(axis: int) -> int:  # noqa: N802 (kernel name)
    return _ior("E", 0x40 + axis, struct.calcsize(ABSINFO_FORMAT))


EVIOCGRAB = _iow("E", 0x90, 4)
UI_DEV_CREATE = _io("U", 1)
UI_DEV_DESTROY = _io("U", 2)
UI_DEV_SETUP = _iow("U", 3, struct.calcsize("HHHH80sI"))
UI_ABS_SETUP = _iow("U", 4, struct.calcsize("H2x6i"))
UI_SET_EVBIT = _iow("U", 100, 4)
UI_SET_KEYBIT = _iow("U", 101, 4)
UI_SET_ABSBIT = _iow("U", 103, 4)


@dataclass
class AbsInfo:
    value: int
    minimum: int
    maximum: int
    fuzz: int = 0
    flat: int = 0
    resolution: int = 0


def parse_bitmap(text: str) -> set[int]:
    """sysfs capability bitmap: hex words (unsigned long), most significant first."""
    bits: set[int] = set()
    words = text.split()
    width = struct.calcsize("l") * 8  # words are the kernel's unsigned long, printed without padding
    for index, word in enumerate(reversed(words)):
        value = int(word, 16)
        bit = 0
        while value:
            if value & 1:
                bits.add(index * width + bit)
            value >>= 1
            bit += 1
    return bits


@dataclass
class DeviceInfo:
    path: str
    name: str
    vendor: str = "0000"
    product: str = "0000"
    keys: set[int] = field(default_factory=set)
    axes: set[int] = field(default_factory=set)
    bus: int = 0

    @property
    def key(self) -> str:
        """Stable id for storing a profile per controller model."""
        return f"{self.vendor}:{self.product}:{self.name}"

    @property
    def is_gamepad(self) -> bool:
        return BTN_GAMEPAD in self.keys and self.name != VIRTUAL_NAME


def _read(path: Path) -> str:
    try:
        return path.read_text().strip()
    except OSError:
        return ""


def list_devices(sys_root: Path = Path("/sys"), dev_root: Path = Path("/dev/input")) -> list[DeviceInfo]:
    devices = []
    for node in sorted((sys_root / "class/input").glob("event*"), key=lambda p: int(p.name[5:] or 0)):
        dev = node / "device"
        devices.append(DeviceInfo(
            path=str(dev_root / node.name),
            name=_read(dev / "name"),
            vendor=_read(dev / "id/vendor") or "0000",
            product=_read(dev / "id/product") or "0000",
            keys=parse_bitmap(_read(dev / "capabilities/key") or "0"),
            axes=parse_bitmap(_read(dev / "capabilities/abs") or "0"),
            bus=int(_read(dev / "id/bustype") or "0", 16),
        ))
    return devices


def find_gamepads(sys_root: Path = Path("/sys"), dev_root: Path = Path("/dev/input")) -> list[DeviceInfo]:
    return [d for d in list_devices(sys_root, dev_root) if d.is_gamepad]


def find_volume_key_devices(sys_root: Path = Path("/sys"), dev_root: Path = Path("/dev/input")) -> list[DeviceInfo]:
    """Built-in devices with volume or power buttons (not Bluetooth keyboards, not our virtual pad)."""
    return [d for d in list_devices(sys_root, dev_root)
            if d.keys & {KEY_VOLUMEUP, KEY_VOLUMEDOWN, KEY_POWER} and d.bus != BUS_BLUETOOTH
            and d.name != VIRTUAL_NAME]


def pack_event(ev_type: int, code: int, value: int) -> bytes:
    return struct.pack(EVENT_FORMAT, 0, 0, ev_type, code, value)


def unpack_events(data: bytes) -> list[tuple[int, int, int]]:
    events = []
    for offset in range(0, len(data) - EVENT_SIZE + 1, EVENT_SIZE):
        _s, _us, ev_type, code, value = struct.unpack_from(EVENT_FORMAT, data, offset)
        events.append((ev_type, code, value))
    return events


class InputDevice:
    """A physical input device opened for reading (optionally grabbed exclusively)."""

    def __init__(self, path: str):
        self.path = path
        self.fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
        self.grabbed = False

    def absinfo(self, axis: int) -> AbsInfo | None:
        buf = bytearray(struct.calcsize(ABSINFO_FORMAT))
        try:
            fcntl.ioctl(self.fd, EVIOCGABS(axis), buf)
        except OSError:
            return None
        return AbsInfo(*struct.unpack(ABSINFO_FORMAT, buf))

    def grab(self) -> None:
        fcntl.ioctl(self.fd, EVIOCGRAB, 1)
        self.grabbed = True

    def ungrab(self) -> None:
        if self.grabbed:
            try:
                fcntl.ioctl(self.fd, EVIOCGRAB, 0)
            except OSError:
                pass
            self.grabbed = False

    def read(self, timeout: float = 0.1) -> list[tuple[int, int, int]]:
        ready, _, _ = select.select([self.fd], [], [], timeout)
        if not ready:
            return []
        try:
            data = os.read(self.fd, EVENT_SIZE * 64)
        except BlockingIOError:
            return []
        return unpack_events(data)

    def close(self) -> None:
        self.ungrab()
        try:
            os.close(self.fd)
        except OSError:
            pass


@dataclass
class AxisSpec:
    code: int
    minimum: int
    maximum: int
    flat: int = 0


XBOX_KEYS = [BTN_SOUTH, BTN_EAST, BTN_NORTH, BTN_WEST, BTN_TL, BTN_TR, BTN_SELECT, BTN_START, BTN_MODE,
             BTN_THUMBL, BTN_THUMBR]
XBOX_AXES = [AxisSpec(ABS_X, -32768, 32767), AxisSpec(ABS_Y, -32768, 32767),
             AxisSpec(ABS_RX, -32768, 32767), AxisSpec(ABS_RY, -32768, 32767),
             AxisSpec(ABS_Z, 0, 255), AxisSpec(ABS_RZ, 0, 255),
             AxisSpec(ABS_HAT0X, -1, 1), AxisSpec(ABS_HAT0Y, -1, 1)]


class UInput:
    """A virtual controller (Xbox 360 layout so Steam/SDL know it everywhere)."""

    def __init__(self, name: str = VIRTUAL_NAME, path: str = "/dev/uinput",
                 keys: list[int] | None = None, axes: list[AxisSpec] | None = None):
        self.fd = os.open(path, os.O_WRONLY | os.O_NONBLOCK)
        try:
            fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_KEY)
            if axes is None or axes:
                fcntl.ioctl(self.fd, UI_SET_EVBIT, EV_ABS)
            for key in XBOX_KEYS if keys is None else keys:
                fcntl.ioctl(self.fd, UI_SET_KEYBIT, key)
            for axis in XBOX_AXES if axes is None else axes:
                fcntl.ioctl(self.fd, UI_SET_ABSBIT, axis.code)
                fcntl.ioctl(self.fd, UI_ABS_SETUP, struct.pack("H2x6i", axis.code, 0, axis.minimum, axis.maximum,
                                                               0, axis.flat, 0))
            fcntl.ioctl(self.fd, UI_DEV_SETUP, struct.pack("HHHH80sI", BUS_USB, VIRTUAL_VENDOR, VIRTUAL_PRODUCT,
                                                           0x0110, name.encode()[:79], 0))
            fcntl.ioctl(self.fd, UI_DEV_CREATE)
        except OSError:
            os.close(self.fd)
            raise

    def emit(self, events: list[tuple[int, int, int]]) -> None:
        if events:
            os.write(self.fd, b"".join(pack_event(*e) for e in events))

    def close(self) -> None:
        try:
            fcntl.ioctl(self.fd, UI_DEV_DESTROY)
        except OSError:
            pass
        try:
            os.close(self.fd)
        except OSError:
            pass
