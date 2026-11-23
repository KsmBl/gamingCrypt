"""Button mapping and stick calibration, and the translation physical -> virtual pad.

Pure logic (no device access) so everything here is unit-testable.
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field

from gamingcrypt.input import evdev as e

# (id, label, output) - output is a key code, or a hat/trigger for D-pad and triggers
BUTTONS = [
    ("a", "A", e.BTN_SOUTH),
    ("b", "B", e.BTN_EAST),
    ("x", "X", e.BTN_NORTH),  # Xbox 360 / xpad layout: X = BTN_NORTH (0x133), Y = BTN_WEST
    ("y", "Y", e.BTN_WEST),
    ("lb", "LB (left bumper)", e.BTN_TL),
    ("rb", "RB (right bumper)", e.BTN_TR),
    ("lt", "LT (left trigger)", "lt"),
    ("rt", "RT (right trigger)", "rt"),
    ("back", "View / Select", e.BTN_SELECT),
    ("start", "Menu / Start", e.BTN_START),
    ("guide", "Guide / Home", e.BTN_MODE),
    ("l3", "Left stick click", e.BTN_THUMBL),
    ("r3", "Right stick click", e.BTN_THUMBR),
    ("dpad_up", "D-pad up", "hat"),
    ("dpad_down", "D-pad down", "hat"),
    ("dpad_left", "D-pad left", "hat"),
    ("dpad_right", "D-pad right", "hat"),
]
BUTTON_LABELS = {b[0]: b[1] for b in BUTTONS}
STICK_AXES = ["lx", "ly", "rx", "ry"]
TRIGGER_AXES = ["lt", "rt"]
OUTPUT_AXES = {"lx": e.ABS_X, "ly": e.ABS_Y, "rx": e.ABS_RX, "ry": e.ABS_RY, "lt": e.ABS_Z, "rt": e.ABS_RZ}
PRESS_THRESHOLD = 0.5

KEY_NAMES = {
    e.BTN_SOUTH: "South (A)", e.BTN_EAST: "East (B)", e.BTN_C: "C", e.BTN_NORTH: "North (X)",
    e.BTN_WEST: "West (Y)", e.BTN_TL: "TL", e.BTN_TR: "TR", e.BTN_TL2: "TL2", e.BTN_TR2: "TR2",
    e.BTN_SELECT: "Select", e.BTN_START: "Start", e.BTN_MODE: "Mode", e.BTN_THUMBL: "Thumb L",
    e.BTN_THUMBR: "Thumb R", e.BTN_DPAD_UP: "D-pad up", e.BTN_DPAD_DOWN: "D-pad down",
    e.BTN_DPAD_LEFT: "D-pad left", e.BTN_DPAD_RIGHT: "D-pad right",
}
AXIS_NAMES = {e.ABS_X: "X", e.ABS_Y: "Y", e.ABS_Z: "Z", e.ABS_RX: "RX", e.ABS_RY: "RY", e.ABS_RZ: "RZ",
              e.ABS_GAS: "Gas", e.ABS_BRAKE: "Brake", e.ABS_HAT0X: "Hat X", e.ABS_HAT0Y: "Hat Y"}


@dataclass(frozen=True)
class Source:
    """A physical input: a key, or an axis pushed in one direction."""

    kind: str  # "key" or "abs"
    code: int
    direction: int = 0  # for "abs": -1 or +1

    def to_dict(self) -> dict:
        data = {"type": self.kind, "code": self.code}
        if self.kind == "abs":
            data["dir"] = self.direction
        return data

    @classmethod
    def from_dict(cls, data: dict) -> "Source":
        return cls(data["type"], int(data["code"]), int(data.get("dir", 0)))

    def describe(self) -> str:
        if self.kind == "key":
            return KEY_NAMES.get(self.code, f"Button {self.code}")
        sign = "+" if self.direction > 0 else "-"
        return f"Axis {AXIS_NAMES.get(self.code, self.code)} {sign}"


@dataclass
class AxisCal:
    center: int
    minimum: int
    maximum: int

    def normalize(self, raw: int) -> float:
        """-1..1 around the center (0..1 for triggers whose center is their minimum)."""
        if raw >= self.center:
            span = self.maximum - self.center
            value = (raw - self.center) / span if span > 0 else 0.0
        else:
            span = self.center - self.minimum
            value = -(self.center - raw) / span if span > 0 else 0.0
        return max(-1.0, min(1.0, value))

    def to_dict(self) -> dict:
        return {"center": self.center, "min": self.minimum, "max": self.maximum}

    @classmethod
    def from_dict(cls, data: dict) -> "AxisCal":
        return cls(int(data["center"]), int(data["min"]), int(data["max"]))


CURVE_POINTS = 17  # a trigger curve: this many points, 0 .. 1 evenly over the trigger's raw range


def trigger_curve(start: float, full: float, shape: float) -> list[float]:
    """The output at CURVE_POINTS even steps of the raw trigger: nothing up to ``start``, all from
    ``full`` (0..1 of the raw range), in between ``t ** shape`` (1 linear, < 1 rises early - for
    triggers that do little at first, > 1 rises late)."""
    start, full = max(0.0, min(start, 0.9)), max(0.1, min(full, 1.0))
    full = max(full, start + 0.05)
    out = []
    for i in range(CURVE_POINTS):
        x = i / (CURVE_POINTS - 1)
        t = 0.0 if x <= start else 1.0 if x >= full else (x - start) / (full - start)
        out.append(round(t ** shape, 4))
    return out


def apply_curve(curve: list[float], x: float) -> float:
    """The curve between its points (straight lines), x and result 0..1."""
    x = max(0.0, min(1.0, x)) * (len(curve) - 1)
    i = min(int(x), len(curve) - 2)
    return max(0.0, min(1.0, curve[i] + (curve[i + 1] - curve[i]) * (x - i)))


def measured_curve(samples: list[tuple[float, float]]) -> list[float] | None:
    """One slow, even pull of a trigger (time, raw 0..1): the curve that makes the output follow
    how far the trigger is pressed instead of what its sensor says. None: not a usable pull (it
    has to go from released to fully pressed). Where the sensor reports nothing (a dead start, a
    stop before the end) no curve can help - those parts stay as they are."""
    moving = [(t, x) for t, x in samples if x > 0.01]
    if len(moving) < 5 or max(x for _t, x in moving) < 0.9:
        return None
    top = max(x for _t, x in moving)
    first = moving[0][0]
    end = next(t for t, x in moving if x >= top - 0.01)
    if end - first < 0.3:  # pulled in one go: nothing to learn from
        return None
    curve = []
    for i in range(CURVE_POINTS):
        level = i / (CURVE_POINTS - 1) * top
        reached = next((t for t, x in moving if x >= level), end) if i else first
        curve.append(round(min(1.0, (reached - first) / (end - first)), 4))
    curve[0] = 0.0
    for i in range(1, CURVE_POINTS):  # never back down
        curve[i] = max(curve[i], curve[i - 1])
    if top < 1.0:  # the sensor stops short of its range: full from there on
        cut = int(top * (CURVE_POINTS - 1))
        curve = [*curve[:cut + 1], *[1.0] * (CURVE_POINTS - cut - 1)]
    return curve


@dataclass
class Profile:
    buttons: dict[str, Source] = field(default_factory=dict)
    axes: dict[str, int | None] = field(default_factory=dict)  # lx/ly/rx/ry/lt/rt -> physical abs code
    calibration: dict[int, AxisCal] = field(default_factory=dict)
    deadzone: float = 0.08
    trigger_deadzone: float = 0.03
    # lt / rt -> their curve (trigger_curve, measured_curve); none: straight, with trigger_deadzone
    trigger_curves: dict[str, list[float]] = field(default_factory=dict)
    # lt / rt -> (start, full, shape) their curve was made from (the sliders); none: measured
    trigger_shapes: dict[str, tuple[float, float, float]] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "trigger_curves": {k: list(v) for k, v in self.trigger_curves.items()},
            "trigger_shapes": {k: list(v) for k, v in self.trigger_shapes.items()},
            "buttons": {k: v.to_dict() for k, v in self.buttons.items()},
            "axes": dict(self.axes),
            "calibration": {str(k): v.to_dict() for k, v in self.calibration.items()},
            "deadzone": self.deadzone,
            "trigger_deadzone": self.trigger_deadzone,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Profile":
        return cls(
            buttons={k: Source.from_dict(v) for k, v in data.get("buttons", {}).items()},
            axes={k: (int(v) if v is not None else None) for k, v in data.get("axes", {}).items()},
            calibration={int(k): AxisCal.from_dict(v) for k, v in data.get("calibration", {}).items()},
            deadzone=float(data.get("deadzone", 0.08)),
            trigger_deadzone=float(data.get("trigger_deadzone", 0.03)),
            trigger_curves={k: [float(x) for x in v] for k, v in data.get("trigger_curves", {}).items()
                            if k in TRIGGER_AXES and len(v) == CURVE_POINTS},
            trigger_shapes={k: tuple(float(x) for x in v) for k, v in data.get("trigger_shapes", {}).items()
                            if k in TRIGGER_AXES and len(v) == 3},
        )


# Drivers that follow the kernel's own layout (hid-playstation, hid-nintendo): the left face button
# (Square, Y) is BTN_WEST and the top one BTN_NORTH - xpad (Xbox pads, built-in pads of handhelds)
# has them the other way round, and that's the layout passed on (the virtual pad is an Xbox 360 one).
POSITIONAL_VENDORS = {"054c", "057e"}  # Sony, Nintendo


def default_profile(keys: set[int], axes: set[int], vendor: str = "") -> Profile:
    """A sensible starting point from what the controller reports."""
    buttons: dict[str, Source] = {}
    for name, _label, output in BUTTONS:
        if isinstance(output, int) and output in keys:
            buttons[name] = Source("key", output)
    if vendor.lower() in POSITIONAL_VENDORS and {e.BTN_NORTH, e.BTN_WEST} <= keys:
        # the left button is X (Square), the top one Y (Triangle) - as on an Xbox pad
        buttons.update(x=Source("key", e.BTN_WEST), y=Source("key", e.BTN_NORTH))
    if e.ABS_HAT0X in axes:
        buttons.update(dpad_left=Source("abs", e.ABS_HAT0X, -1), dpad_right=Source("abs", e.ABS_HAT0X, 1),
                       dpad_up=Source("abs", e.ABS_HAT0Y, -1), dpad_down=Source("abs", e.ABS_HAT0Y, 1))
    else:
        for name, code in (("dpad_up", e.BTN_DPAD_UP), ("dpad_down", e.BTN_DPAD_DOWN),
                           ("dpad_left", e.BTN_DPAD_LEFT), ("dpad_right", e.BTN_DPAD_RIGHT)):
            if code in keys:
                buttons[name] = Source("key", code)
    profile_axes: dict[str, int | None] = {
        "lx": e.ABS_X if e.ABS_X in axes else None,
        "ly": e.ABS_Y if e.ABS_Y in axes else None,
        "rx": e.ABS_RX if e.ABS_RX in axes else None,
        "ry": e.ABS_RY if e.ABS_RY in axes else None,
    }
    for name, analog, fallback_axis, digital in (("lt", e.ABS_Z, e.ABS_BRAKE, e.BTN_TL2),
                                                 ("rt", e.ABS_RZ, e.ABS_GAS, e.BTN_TR2)):
        code = analog if analog in axes else fallback_axis if fallback_axis in axes else None
        profile_axes[name] = code
        if code is not None:
            buttons[name] = Source("abs", code, 1)
        elif digital in keys:
            buttons[name] = Source("key", digital)
    return Profile(buttons=buttons, axes=profile_axes)


def default_calibration(name: str, info: e.AbsInfo) -> AxisCal:
    if name in TRIGGER_AXES:
        return AxisCal(info.minimum, info.minimum, info.maximum)
    center = 0 if info.minimum < 0 < info.maximum else (info.minimum + info.maximum) // 2
    return AxisCal(center, info.minimum, info.maximum)


def apply_deadzone(x: float, y: float, deadzone: float) -> tuple[float, float]:
    """Radial deadzone, rescaled so full deflection still reaches 1."""
    magnitude = math.hypot(x, y)
    if magnitude <= deadzone or magnitude == 0:
        return 0.0, 0.0
    scale = min(1.0, (magnitude - deadzone) / (1 - deadzone)) / magnitude
    return x * scale, y * scale


class Translator:
    """Feeds physical events, returns the virtual pad's events (on every SYN_REPORT)."""

    def __init__(self, profile: Profile, absinfo: dict[int, e.AbsInfo]):
        self.profile = profile
        self.keys: dict[int, int] = {}
        self.abs: dict[int, int] = {code: info.value for code, info in absinfo.items()}
        self.cal: dict[int, AxisCal] = {}
        names = {code: name for name, code in profile.axes.items() if code is not None}
        for code, info in absinfo.items():
            self.cal[code] = profile.calibration.get(code) or default_calibration(names.get(code, ""), info)
        self.last: dict[tuple[int, int], int] = {}

    def normalized(self, code: int) -> float:
        cal = self.cal.get(code)
        raw = self.abs.get(code, 0)
        return cal.normalize(raw) if cal else max(-1.0, min(1.0, float(raw)))

    def pressed(self, source: Source | None) -> bool:
        if source is None:
            return False
        if source.kind == "key":
            return self.keys.get(source.code, 0) != 0
        return self.normalized(source.code) * source.direction > PRESS_THRESHOLD

    def _trigger(self, name: str) -> int:
        source = self.profile.buttons.get(name)
        analog = self.profile.axes.get(name)
        if source is not None and source.kind == "abs" and source.code == analog and source.direction > 0:
            value = max(0.0, self.normalized(analog))
            curve = self.profile.trigger_curves.get(name)
            if curve:
                return round(apply_curve(curve, value) * 255)
            dz = self.profile.trigger_deadzone
            value = 0.0 if value <= dz else (value - dz) / (1 - dz)
            return round(value * 255)
        return 255 if self.pressed(source) else 0

    def outputs(self) -> dict[tuple[int, int], int]:
        out: dict[tuple[int, int], int] = {}
        b = self.profile.buttons
        for name, _label, output in BUTTONS:
            if isinstance(output, int):
                out[(e.EV_KEY, output)] = 1 if self.pressed(b.get(name)) else 0
        out[(e.EV_ABS, e.ABS_HAT0X)] = int(self.pressed(b.get("dpad_right"))) - int(self.pressed(b.get("dpad_left")))
        out[(e.EV_ABS, e.ABS_HAT0Y)] = int(self.pressed(b.get("dpad_down"))) - int(self.pressed(b.get("dpad_up")))
        for left, right in (("lx", "ly"), ("rx", "ry")):
            cx, cy = self.profile.axes.get(left), self.profile.axes.get(right)
            x = self.normalized(cx) if cx is not None else 0.0
            y = self.normalized(cy) if cy is not None else 0.0
            x, y = apply_deadzone(x, y, self.profile.deadzone)
            out[(e.EV_ABS, OUTPUT_AXES[left])] = round(x * 32767)
            out[(e.EV_ABS, OUTPUT_AXES[right])] = round(y * 32767)
        for name in TRIGGER_AXES:
            out[(e.EV_ABS, OUTPUT_AXES[name])] = self._trigger(name)
        return out

    def feed(self, ev_type: int, code: int, value: int) -> list[tuple[int, int, int]]:
        if ev_type == e.EV_KEY:
            self.keys[code] = value
        elif ev_type == e.EV_ABS:
            self.abs[code] = value
        elif ev_type == e.EV_SYN and code == e.SYN_REPORT:
            changed = [(t, c, v) for (t, c), v in self.outputs().items() if self.last.get((t, c)) != v]
            for t, c, v in changed:
                self.last[(t, c)] = v
            return changed + [(e.EV_SYN, e.SYN_REPORT, 0)] if changed else []
        return []


class CalibrationSession:
    """Step 1: sticks centred (noise -> deadzone). Step 2: full circles + triggers (range)."""

    def __init__(self, profile: Profile, absinfo: dict[int, e.AbsInfo]):
        self.profile = profile
        self.absinfo = absinfo
        self.codes = {name: code for name, code in profile.axes.items() if code is not None and code in absinfo}
        self.step = "center"
        self.center_samples: dict[int, list[int]] = {c: [absinfo[c].value] for c in self.codes.values()}
        self.low: dict[int, int] = {}
        self.high: dict[int, int] = {}

    def feed(self, ev_type: int, code: int, value: int) -> None:
        if ev_type != e.EV_ABS or code not in self.center_samples:
            return
        if self.step == "center":
            self.center_samples[code].append(value)
        elif self.step == "range":
            self.low[code] = min(self.low.get(code, value), value)
            self.high[code] = max(self.high.get(code, value), value)

    def next_step(self) -> None:
        self.step = "range"

    def coverage(self) -> dict[str, float]:
        """How much of each axis' hardware range was reached (0..1)."""
        result = {}
        for name, code in self.codes.items():
            info = self.absinfo[code]
            span = info.maximum - info.minimum
            seen = self.high.get(code, 0) - self.low.get(code, 0) if code in self.high else 0
            result[name] = seen / span if span else 0.0
        return result

    def finish(self) -> tuple[Profile | None, str]:
        coverage = self.coverage()
        too_small = [n for n, c in coverage.items() if c < (0.4 if n in TRIGGER_AXES else 0.5)]
        if too_small:
            return None, "Move further: " + ", ".join(n.upper() for n in too_small)
        calibration = dict(self.profile.calibration)
        noise = 0.0
        for name, code in self.codes.items():
            samples = self.center_samples[code]
            low, high = self.low[code], self.high[code]
            if name in TRIGGER_AXES:
                calibration[code] = AxisCal(low, low, high)
                continue
            center = int(statistics.median(samples))
            center = min(max(center, low + 1), high - 1)
            calibration[code] = AxisCal(center, low, high)
            half = max(high - center, center - low, 1)
            noise = max(noise, (max(samples) - min(samples)) / 2 / half)
        profile = Profile(dict(self.profile.buttons), dict(self.profile.axes), calibration,
                          deadzone=round(min(0.3, max(0.03, noise * 1.5 + 0.02)), 3),
                          trigger_deadzone=self.profile.trigger_deadzone,
                          trigger_curves=dict(self.profile.trigger_curves),
                          trigger_shapes=dict(self.profile.trigger_shapes))
        return profile, "Calibration done"


class Capture:
    """Waits for the next deliberate press: a button, or an axis pushed past 60 %."""

    def __init__(self, absinfo: dict[int, e.AbsInfo], current: dict[int, int] | None = None):
        self.absinfo = absinfo
        self.rest = dict(current or {code: info.value for code, info in absinfo.items()})

    def feed(self, ev_type: int, code: int, value: int) -> Source | None:
        if ev_type == e.EV_KEY and value == 1:
            return Source("key", code)
        if ev_type == e.EV_ABS and code in self.absinfo:
            info = self.absinfo[code]
            half = (info.maximum - info.minimum) / 2 or 1
            delta = value - self.rest.get(code, info.value)
            if abs(delta) / half > 0.6 or (info.maximum - info.minimum <= 2 and value != 0):
                return Source("abs", code, 1 if delta > 0 else -1)
        return None
