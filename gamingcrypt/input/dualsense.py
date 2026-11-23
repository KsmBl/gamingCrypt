"""Adaptive triggers of a PS5 controller (DualSense, DualSense Edge): resistance the triggers
push back with - e.g. a stop halfway down the aim trigger, like a gun's.

Linux has no interface for it: the effect is sent straight to the controller (its hidraw
device, an output report that only says "the triggers' effects" - lights and rumble stay with
the kernel's driver). The controller keeps an effect until it's told another or switched off,
so it's sent when the controller is found, when it's changed, and when a game starts (a game
that talks to the controller itself may have changed it).

The effects are the controller's own (as PS5 games use them); the trigger's travel is 10 zones.
"""

from __future__ import annotations

import binascii
from dataclasses import dataclass
from pathlib import Path

SONY = 0x054C
PRODUCTS = {0x0CE6: "DualSense", 0x0DF2: "DualSense Edge"}
BUS_USB, BUS_BLUETOOTH = 0x03, 0x05

OFF, STOP, RESISTANCE = "off", "stop", "resistance"
EFFECTS = (  # (id, label, what it does)
    (OFF, "Off", "The trigger moves freely"),
    (STOP, "Stop", "A stop at that point that gives way when pulled harder - like a gun's trigger"),
    (RESISTANCE, "Resistance", "Pushes back from that point to the end"),
)
MODE_OFF, MODE_FEEDBACK, MODE_WEAPON = 0x05, 0x21, 0x25
TRIGGERS = ("lt", "rt")


@dataclass(frozen=True)
class Effect:
    kind: str = OFF
    position: int = 50  # where it starts: % of the trigger's travel
    strength: int = 5  # 1 .. 8

    def to_dict(self) -> dict:
        return {"effect": self.kind, "position": self.position, "strength": self.strength}

    @classmethod
    def from_dict(cls, data: dict | None) -> "Effect":
        data = data or {}
        kind = data.get("effect", OFF)
        return cls(kind if kind in (OFF, STOP, RESISTANCE) else OFF,
                   max(0, min(100, int(data.get("position", 50)))), max(1, min(8, int(data.get("strength", 5)))))


def effect_bytes(effect: Effect) -> bytes:
    """The 11 bytes of one trigger's effect in the output report."""
    out = bytearray(11)
    zone = round(effect.position / 10)  # 0 .. 10
    force = effect.strength - 1  # 0 .. 7
    if effect.kind == STOP:
        start = max(2, min(7, zone))  # the controller's limits for this one
        end = min(8, start + 1)
        zones = (1 << start) | (1 << end)
        out[0] = MODE_WEAPON
        out[1:3] = zones.to_bytes(2, "little")
        out[3] = force
    elif effect.kind == RESISTANCE:
        start = max(0, min(9, zone))
        active = forces = 0
        for i in range(start, 10):
            active |= 1 << i
            forces |= force << (3 * i)
        out[0] = MODE_FEEDBACK
        out[1:3] = active.to_bytes(2, "little")
        out[3:7] = forces.to_bytes(4, "little")
    else:
        out[0] = MODE_OFF
    return bytes(out)


TRIGGER_FLAGS = 0x04 | 0x08  # valid_flag0: right / left trigger effect


def report(lt: Effect, rt: Effect, bus: int, seq: int = 0) -> bytes:
    """The output report that sets both triggers - nothing else (USB: 0x02; Bluetooth: 0x31, with
    the controller's checksum)."""
    common = bytearray(47)  # the part USB and Bluetooth share
    common[0] = TRIGGER_FLAGS
    common[10:21] = effect_bytes(rt)
    common[21:32] = effect_bytes(lt)
    if bus == BUS_BLUETOOTH:
        data = bytearray(78)
        data[0] = 0x31
        data[1] = (seq & 0x0F) << 4
        data[2] = 0x10  # (DS_OUTPUT_TAG)
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


def find(sys_root: Path = Path("/sys"), dev: Path = Path("/dev")) -> list[Controller]:
    """The connected PS5 controllers (their hidraw devices)."""
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
            error = "Not allowed to reach the PS5 controller yet - finish the update in Settings → System"
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
