"""Device buttons: which button opens the quick menu and which locks right away.

Not every handheld has a Windows key for the quick menu, so the buttons are set in
Settings -> Controller -> Device buttons (pressed once to record them). A binding is
one button or a combination (hold the first, press the second), either on a
keyboard-like device (Windows key, volume buttons ...) or on the controller (Guide,
Select ...). Defaults depend on the handheld model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from gamingcrypt.input import evdev as e

ACTIONS = {"quick_menu": "Quick menu", "lock": "Lock now"}
# reported by the key reader instead of the key code when a binding fired
ACTION_CODES = {"lock": e.PANIC_COMBO, "quick_menu": -2}
KEY = "key"  # keyboard-like device (read by the volume key reader)
PAD = "pad"  # the controller (through the UI's controller input)

KEY_NAMES = {e.KEY_LEFTMETA: "Windows", e.KEY_RIGHTMETA: "Windows", e.KEY_VOLUMEDOWN: "Volume Down",
             e.KEY_VOLUMEUP: "Volume Up", e.KEY_MUTE: "Mute", e.KEY_POWER: "Power", 1: "Esc", 28: "Enter",
             148: "Prog1", 149: "Prog2", 202: "Prog3", 203: "Prog4", 185: "F15", 186: "F16", 187: "F17",
             188: "F18", 189: "F19", 190: "F20", 191: "F21", 192: "F22", 193: "F23", 194: "F24"}
PAD_NAMES = {e.BTN_SOUTH: "A", e.BTN_EAST: "B", e.BTN_NORTH: "X", e.BTN_WEST: "Y", e.BTN_TL: "LB",
             e.BTN_TR: "RB", e.BTN_SELECT: "View", e.BTN_START: "Menu", e.BTN_MODE: "Guide",
             e.BTN_THUMBL: "L3", e.BTN_THUMBR: "R3"}
ALIASES = {e.KEY_RIGHTMETA: e.KEY_LEFTMETA}  # either Windows key counts


@dataclass(frozen=True)
class Binding:
    source: str
    codes: tuple[int, ...]
    device: str = ""  # keyboard-like device it came from (for install.sh's access rule)

    def describe(self) -> str:
        names = PAD_NAMES if self.source == PAD else KEY_NAMES
        parts = [names.get(c, f"{'Button' if self.source == PAD else 'Key'} {c}") for c in self.codes]
        text = " + ".join(parts)
        return f"{text} (controller)" if self.source == PAD else text

    def to_dict(self) -> dict:
        return {"source": self.source, "codes": list(self.codes), "device": self.device}

    @classmethod
    def from_dict(cls, data: dict) -> "Binding | None":
        try:
            codes = tuple(int(c) for c in data["codes"])
            source = data["source"]
        except (KeyError, TypeError, ValueError):
            return None
        if source not in (KEY, PAD) or not 1 <= len(codes) <= 2:
            return None
        return cls(source, codes, str(data.get("device", "")))


WINDOWS = {"quick_menu": Binding(KEY, (e.KEY_LEFTMETA,)),
           "lock": Binding(KEY, (e.KEY_LEFTMETA, e.KEY_VOLUMEDOWN))}
CONTROLLER = {"quick_menu": Binding(PAD, (e.BTN_MODE,)),
              "lock": Binding(PAD, (e.BTN_MODE, e.BTN_SELECT))}
# vendor (DMI sys_vendor) -> defaults: handhelds with a Windows key use it for the menu
KNOWN = {"AYANEO": WINDOWS, "AYADEVICE": WINDOWS, "GPD": WINDOWS, "ONE-NETBOOK": WINDOWS,
         "Valve": CONTROLLER}


def dmi(sys_root: Path = Path("/sys")) -> tuple[str, str]:
    def read(name: str) -> str:
        try:
            return (sys_root / "class/dmi/id" / name).read_text().strip()
        except OSError:
            return ""
    return read("sys_vendor"), read("product_name")


def defaults(vendor: str = "", product: str = "") -> dict[str, Binding]:
    for known, bindings in KNOWN.items():
        if vendor.upper().startswith(known.upper()):
            return dict(bindings)
    return dict(WINDOWS)  # most PC handhelds have one; the controller's Guide when not


def load(config: dict, vendor_product: tuple[str, str] | None = None) -> dict[str, Binding]:
    bindings = defaults(*(vendor_product if vendor_product is not None else dmi()))
    for action, data in (config.get("input", {}).get("hotkeys") or {}).items():
        binding = Binding.from_dict(data) if isinstance(data, dict) else None
        if action in ACTIONS and binding is not None:
            bindings[action] = binding
    return bindings


def save(config: dict, action: str, binding: Binding | None) -> None:
    hotkeys = config.setdefault("input", {}).setdefault("hotkeys", {})
    if binding is None:
        hotkeys.pop(action, None)  # back to the default for this device
    else:
        hotkeys[action] = binding.to_dict()


@dataclass
class Tracker:
    """Feed button presses / releases of one source; get the actions that fired.

    A combination fires when its second button is pressed while the first is held;
    the second button is then "used up" (e.g. Volume Down doesn't change the volume).
    """

    bindings: dict[str, Binding]
    source: str
    held: set[int] = field(default_factory=set)

    def feed(self, code: int, pressed: bool) -> tuple[list[str], bool]:
        """-> (actions, consumed)."""
        code = ALIASES.get(code, code)
        if not pressed:
            self.held.discard(code)
            return [], False
        self.held.add(code)
        actions, consumed = [], False
        for action, binding in self.bindings.items():
            if binding.source != self.source:
                continue
            if len(binding.codes) == 2 and code == binding.codes[1] and binding.codes[0] in self.held:
                actions.append(action)
                consumed = True
        if not actions:
            for action, binding in self.bindings.items():
                if binding.source == self.source and binding.codes == (code,):
                    actions.append(action)
                    consumed = True
        return actions, consumed

    def watched(self) -> set[int]:
        return {c for b in self.bindings.values() if b.source == self.source for c in b.codes}
