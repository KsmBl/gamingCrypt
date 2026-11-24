"""Adaptive triggers of a PS5 controller (DualSense, DualSense Edge), through its hidraw device -
e.g. a stop halfway down the aim trigger. (The same as the PS5 Shock Configurator's.)

It's sent when the controller is found, when it's changed, and when a game starts (a game that
talks to the controller itself may have changed it).

Linux's driver (hid-playstation) has no interface for the adaptive triggers, so the effect goes
straight to the controller in an output report that only says "the triggers' effects": the
lights and rumble stay with the driver. The controller keeps an effect until it's told another
one or switched off.

The effects are the controller's own (the ones PS5 games use). A trigger's travel is 10 zones.
The motor can only push a trigger outward: an effect is felt pulling in - "Bump" (and "Rising")
are also felt letting go (the motor nudges the trigger out over those zones).
"""

from __future__ import annotations

import binascii
import os
from dataclasses import dataclass
from pathlib import Path

SONY = 0x054C
PRODUCTS = {0x0CE6: "DualSense", 0x0DF2: "DualSense Edge"}
BUS_USB, BUS_BLUETOOTH = 0x03, 0x05

OFF, STOP, BUMP, RESISTANCE = "off", "stop", "bump", "resistance"
RISING, BOW, BUZZ, RISING_BUZZ = "rising", "bow", "buzz", "rising_buzz"
EFFECTS = (  # (id, label, what it does)
    (OFF, "Off", "The trigger moves freely."),
    (STOP, "Stop", "A stop that gives way when pulled harder - like a gun's trigger. Felt pulling in only; "
                   "wider is a longer, softer stop."),
    (BUMP, "Bump (both ways)", "A band of resistance: pushed through pulling in, and letting go the trigger "
                               "nudges your finger there. Narrow is a sharp point, wide a soft hill."),
    (RESISTANCE, "Resistance", "The same resistance from that point to the end."),
    (RISING, "Rising resistance", "Gets harder the further you pull - like a real spring or brake pedal."),
    (BOW, "Tension and snap", "Tightens over a range, then gives way with a snap - like a bowstring."),
    (BUZZ, "Buzz", "The trigger vibrates once pulled past that point - a machine gun, an engine."),
    (RISING_BUZZ, "Rising buzz", "Vibrates harder the further you pull - an engine revving up, a drill biting in."),
)
KINDS = tuple(kind for kind, _label, _text in EFFECTS)
MODE_OFF, MODE_FEEDBACK, MODE_BOW, MODE_WEAPON, MODE_VIBRATION = 0x05, 0x21, 0x22, 0x25, 0x26
TRIGGER_FLAGS = 0x04 | 0x08  # valid_flag0: right / left trigger effect

# each effect's settings: (field, caption, lowest, highest, step, unit) - the window shows these
PCT, LEVEL, HZ = "%", "/ 8", "Hz"
PARAMS = {
    OFF: (),
    STOP: (("position", "Where", 20, 70, 10, PCT), ("width", "Width", 10, 30, 10, PCT),
           ("strength", "Strength", 1, 8, 1, LEVEL)),
    BUMP: (("position", "Where", 0, 90, 10, PCT), ("width", "Width", 10, 30, 10, PCT),
           ("strength", "Strength", 1, 8, 1, LEVEL)),
    RESISTANCE: (("position", "From", 0, 90, 10, PCT), ("strength", "Strength", 1, 8, 1, LEVEL)),
    RISING: (("position", "From", 0, 80, 10, PCT), ("strength", "Strength at first", 1, 8, 1, LEVEL),
             ("strength_end", "Strength at the end", 1, 8, 1, LEVEL)),
    BOW: (("position", "From", 0, 70, 10, PCT), ("end", "Snaps at", 10, 80, 10, PCT),
          ("strength", "Tension", 1, 8, 1, LEVEL), ("snap", "Snap", 1, 8, 1, LEVEL)),
    BUZZ: (("position", "From", 0, 90, 10, PCT), ("strength", "Strength", 1, 8, 1, LEVEL),
           ("speed", "Speed", 5, 100, 5, HZ)),
    RISING_BUZZ: (("position", "From", 0, 80, 10, PCT), ("strength", "Strength at first", 1, 8, 1, LEVEL),
                  ("strength_end", "Strength at the end", 1, 8, 1, LEVEL), ("speed", "Speed", 5, 100, 5, HZ)),
}
LIMITS = {"position": (0, 100), "strength": (1, 8), "width": (10, 30), "strength_end": (1, 8),
          "end": (10, 90), "snap": (1, 8), "speed": (1, 255)}


@dataclass(frozen=True)
class Effect:
    kind: str = OFF
    position: int = 50  # where it starts: % of the trigger's travel
    strength: int = 5  # 1 .. 8
    width: int = 10  # stop, bump: how long, % of the travel
    strength_end: int = 8  # rising, rising buzz: at the end of the travel
    end: int = 80  # bow: where it snaps
    snap: int = 5  # bow: how hard it snaps
    speed: int = 30  # buzz, rising buzz: vibrations a second

    def to_dict(self) -> dict:
        return {"effect": self.kind, "position": self.position, "strength": self.strength, "width": self.width,
                "strength_end": self.strength_end, "end": self.end, "snap": self.snap, "speed": self.speed}

    @classmethod
    def from_dict(cls, data: dict | None) -> "Effect":
        data = data or {}
        kind = data.get("effect", OFF)
        values = {}
        for name, (low, high) in LIMITS.items():
            try:
                values[name] = max(low, min(high, int(data.get(name, getattr(cls, name)))))
            except (TypeError, ValueError):
                values[name] = getattr(cls, name)
        return cls(kind if kind in KINDS else OFF, **values)


def _zone(percent: int, low: int = 0, high: int = 9) -> int:
    return max(low, min(high, round(percent / 10)))


def rising(start: int, first: int, last: int) -> dict[int, int]:
    """Zone -> strength from ``start`` to the end, ``first`` there, growing evenly to ``last``."""
    span = max(1, 9 - start)
    return {z: round(first + (last - first) * (z - start) / span) for z in range(start, 10)}


def _by_zone(out: bytearray, strengths: dict[int, int], mode: int = MODE_FEEDBACK) -> None:
    """Feedback / vibration by position: each zone its own strength (1..8)."""
    active = forces = 0
    for zone, strength in strengths.items():
        active |= 1 << zone
        forces |= (max(1, min(8, strength)) - 1) << (3 * zone)
    out[0] = mode
    out[1:3] = active.to_bytes(2, "little")
    out[3:7] = forces.to_bytes(4, "little")


def effect_bytes(effect: Effect) -> bytes:
    """The 11 bytes of one trigger's effect in the output report."""
    out = bytearray(11)
    kind = effect.kind
    if kind == STOP:
        start = _zone(effect.position, 2, 7)  # the controller's limits for this one
        end = min(8, start + max(1, _zone(effect.width, 1, 3)))
        out[0] = MODE_WEAPON
        out[1:3] = ((1 << start) | (1 << end)).to_bytes(2, "little")
        out[3] = effect.strength - 1
    elif kind == BUMP:
        start = _zone(effect.position)
        _by_zone(out, {z: effect.strength for z in range(start, min(10, start + _zone(effect.width, 1, 3)))})
    elif kind == RESISTANCE:
        _by_zone(out, {z: effect.strength for z in range(_zone(effect.position), 10)})
    elif kind == RISING:
        _by_zone(out, rising(_zone(effect.position, 0, 8), effect.strength, effect.strength_end))
    elif kind == BOW:
        start = _zone(effect.position, 0, 7)
        end = max(start + 1, _zone(effect.end, 1, 8))
        out[0] = MODE_BOW
        out[1:3] = ((1 << start) | (1 << end)).to_bytes(2, "little")
        pair = ((effect.strength - 1) & 7) | (((effect.snap - 1) & 7) << 3)
        out[3:5] = pair.to_bytes(2, "little")
    elif kind == BUZZ:
        _by_zone(out, {z: effect.strength for z in range(_zone(effect.position), 10)}, MODE_VIBRATION)
        out[9] = max(1, min(255, effect.speed))
    elif kind == RISING_BUZZ:  # the vibration's strength set zone by zone, as the resistance's is for Rising
        _by_zone(out, rising(_zone(effect.position, 0, 8), effect.strength, effect.strength_end), MODE_VIBRATION)
        out[9] = max(1, min(255, effect.speed))
    else:
        out[0] = MODE_OFF
    return bytes(out)


def report(left: Effect, right: Effect, bus: int, seq: int = 0) -> bytes:
    """The output report that sets both triggers and nothing else (USB: 0x02; Bluetooth: 0x31,
    with the controller's checksum)."""
    common = bytearray(47)  # the part USB and Bluetooth share
    common[0] = TRIGGER_FLAGS
    common[10:21] = effect_bytes(right)
    common[21:32] = effect_bytes(left)
    if bus == BUS_BLUETOOTH:
        data = bytearray(78)
        data[0] = 0x31
        data[1] = (seq & 0x0F) << 4
        data[2] = 0x10
        data[3:3 + len(common)] = common
        crc = binascii.crc32(bytes([0xA2]) + bytes(data[:74])) & 0xFFFFFFFF
        data[74:78] = crc.to_bytes(4, "little")
        return bytes(data)
    return bytes([0x02]) + bytes(common)


@dataclass(frozen=True)
class Controller:
    path: str  # /dev/hidrawN
    bus: int
    name: str

    @property
    def connection(self) -> str:
        return "Bluetooth" if self.bus == BUS_BLUETOOTH else "USB"


def find(sys_root: Path = Path("/sys"), dev: Path = Path("/dev")) -> list[Controller]:
    """The connected PS5 controllers."""
    found = []
    for node in sorted((sys_root / "class/hidraw").glob("hidraw*")):
        try:
            uevent = (node / "device/uevent").read_text()
        except OSError:
            continue
        fields = dict(line.split("=", 1) for line in uevent.splitlines() if "=" in line)
        try:
            bus, vendor, product = (int(x, 16) for x in fields.get("HID_ID", "").split(":"))
        except ValueError:
            continue
        if vendor == SONY and product in PRODUCTS:
            found.append(Controller(str(dev / node.name), bus, PRODUCTS[product]))
    return found


_seq = 0
NO_ACCESS = "Not allowed to reach the PS5 controller yet - finish the update in Settings → System"


def send(lt: Effect, rt: Effect, controllers: list[Controller] | None = None, opener=open) -> tuple[int, str]:
    """To every PS5 controller: (how many took it, what went wrong - "" when nothing did)."""
    global _seq
    done, error = 0, ""
    for controller in find() if controllers is None else controllers:
        _seq = (_seq + 1) & 0x0F
        try:
            with opener(controller.path, "wb", buffering=0) as handle:
                handle.write(report(lt, rt, controller.bus, _seq))
            done += 1
        except PermissionError:
            error = NO_ACCESS
        except OSError as exc:
            error = f"The PS5 controller didn't take it: {exc.strerror or exc}"
    return done, error


def from_config(config: dict) -> tuple[Effect, Effect]:
    saved = config.get("input", {}).get("adaptive_triggers", {})
    return Effect.from_dict(saved.get("lt")), Effect.from_dict(saved.get("rt"))


def apply(config: dict, controllers: list[Controller] | None = None, opener=open) -> tuple[int, str]:
    """What's set in Settings, to the connected PS5 controllers."""
    lt, rt = from_config(config)
    return send(lt, rt, controllers, opener)


def triggers(data: bytes) -> tuple[int, int] | None:
    """(L2, R2) 0..255 from an input report - None for other reports.
    USB 0x01: L2, R2 at 5, 6; Bluetooth 0x31 (the full report): at 6, 7."""
    if len(data) >= 10 and data[0] == 0x01:
        return data[5], data[6]
    if len(data) >= 10 and data[0] == 0x31:
        return data[6], data[7]
    return None


class TriggerReader:
    """Reads where the triggers are (a copy of the input - the driver still gets it). ``poll()``
    returns the newest (L2, R2), or None when nothing new came."""

    def __init__(self, controller: Controller, opener=os.open):
        self.fd = opener(controller.path, os.O_RDONLY | os.O_NONBLOCK)

    def poll(self) -> tuple[int, int] | None:
        newest = None
        for _ in range(64):  # what came since last time - only the last one counts
            try:
                data = os.read(self.fd, 128)
            except BlockingIOError:
                break
            if not data:
                break
            newest = triggers(data) or newest
        return newest

    def close(self) -> None:
        try:
            os.close(self.fd)
        except OSError:
            pass
