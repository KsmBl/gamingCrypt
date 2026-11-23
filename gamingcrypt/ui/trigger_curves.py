"""Settings → Controller → Triggers: a curve per trigger, for triggers that aren't linear (a dead
start, a sudden rise, full long before the end). The sliders shape it; Measure makes it from one
slow pull. Games get the corrected value through the virtual controller (input/profile)."""

from __future__ import annotations

import math
import time
from typing import Callable

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

from gamingcrypt.input.profile import TRIGGER_AXES, apply_curve, measured_curve, trigger_curve
from gamingcrypt.ui import navigator, theme
from gamingcrypt.ui.system_settings import Section, _label, _on_change, _slider
from gamingcrypt.ui.widgets import big_button, set_status

NAMES = {"lt": "LT (left trigger)", "rt": "RT (right trigger)"}
SHORT = {"lt": "LT", "rt": "RT"}
MEASURE_S = 15  # how long a pull is waited for


def shape_of(slider: int) -> float:
    """Curve slider -100..100 -> exponent: + rises early (4 ** -1 = 0.25), - rises late (4)."""
    return round(4 ** (-slider / 100), 4)


def slider_of(shape: float) -> int:
    return round(-math.log(shape, 4) * 100) if shape > 0 else 0


class TriggerView(QWidget):
    """The curve (raw trigger → what games get) and where the trigger is now."""

    def __init__(self, title: str):
        super().__init__()
        self.title = title
        self.setFixedSize(170, 190)
        self.curve: list[float] | None = None
        self.raw = 0.0
        self.out = 0.0
        self.selected = False

    def set_curve(self, curve: list[float] | None) -> None:
        self.curve = curve
        self.update()

    def set_values(self, raw: float, out: float) -> None:
        self.raw, self.out = raw, out
        self.update()

    def paintEvent(self, _event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        box = QRectF(15, 15, 140, 140)
        p.setPen(QPen(QColor(theme.ACCENT if self.selected else theme.SURFACE_HI), 3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(box, 6, 6)
        p.setPen(QPen(QColor(theme.TEXT_DIM), 1, Qt.PenStyle.DashLine))
        p.drawLine(box.bottomLeft(), box.topRight())  # straight, for comparison

        def at(x: float, y: float) -> QPointF:
            return QPointF(box.left() + x * box.width(), box.bottom() - y * box.height())

        path = QPainterPath(at(0, 0))
        steps = 64
        for i in range(steps + 1):
            x = i / steps
            path.lineTo(at(x, apply_curve(self.curve, x) if self.curve else x))
        p.setPen(QPen(QColor(theme.ACCENT), 3))
        p.drawPath(path)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.TEXT))
        p.drawEllipse(at(self.raw, self.out), 7, 7)
        p.setPen(QColor(theme.TEXT_DIM))
        p.drawText(0, 172, 170, 18, Qt.AlignmentFlag.AlignCenter, f"{self.title}  {round(self.out * 100)}%")


class TriggerSection(Section):
    """``profile()``: the controller's profile now (None: none); ``save()``: after a change."""

    def __init__(self, profile: Callable[[], object], save: Callable[[], None]):
        super().__init__("Triggers")
        self.profile = profile
        self.save = save
        self.editing = "rt"
        self.measuring: str | None = None
        self.samples: list[tuple[float, float]] = []
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(lambda: self.stop_measuring("No full pull noticed - tap Measure to try again"))

        self.body.addWidget(_label("Fix triggers that do nothing at first, then jump, or are at 100% long before "
                                   "the end. The line shows what games get for each position (dashed: straight). "
                                   "Measure: pull the trigger slowly and evenly all the way, and its curve is "
                                   "made from that."))
        views = QHBoxLayout()
        self.views = {name: TriggerView(SHORT[name]) for name in TRIGGER_AXES}
        for view in self.views.values():
            views.addWidget(view)
        views.addStretch()
        self.body.addLayout(views)

        pick = QHBoxLayout()
        self.pick_buttons = {}
        for name in TRIGGER_AXES:
            button = big_button(f"Edit {SHORT[name]}", choice=True)
            button.clicked.connect(lambda _=False, n=name: self.select(n))
            pick.addWidget(button)
            self.pick_buttons[name] = button
        pick.addStretch()
        self.body.addLayout(pick)

        self.start_value, self.full_value, self.shape_value = QLabel(), QLabel(), QLabel()
        self.start_slider = _slider(0, 50, 0)
        self.full_slider = _slider(50, 100, 100)
        self.shape_slider = _slider(-100, 100, 0)
        for slider, value, text in ((self.start_slider, self.start_value, lambda v: f"{v}%"),
                                    (self.full_slider, self.full_value, lambda v: f"{v}%"),
                                    (self.shape_slider, self.shape_value, self.shape_text)):
            _on_change(slider, lambda _v: self.shape_changed(), lambda v, value=value, text=text: value.setText(text(v)))
        self.row("Starts at", self.start_slider, self.start_value)
        self.row("100% at", self.full_slider, self.full_value)
        self.row("Curve", self.shape_slider, self.shape_value)

        actions = QHBoxLayout()
        self.measure_button = big_button("Measure", "primary")
        self.measure_button.clicked.connect(self.start_measuring)
        actions.addWidget(self.measure_button)
        self.straight_button = big_button("Straight")
        self.straight_button.clicked.connect(self.straight)
        actions.addWidget(self.straight_button)
        actions.addStretch()
        self.body.addLayout(actions)
        self.body.addWidget(self.status)
        self.select(self.editing)

    @staticmethod
    def shape_text(value: int) -> str:
        return "straight" if value == 0 else f"earlier {value}" if value > 0 else f"later {-value}"

    # which trigger, and its sliders -----------------------------------------------------------
    def select(self, name: str) -> None:
        self.editing = name
        for other, button in self.pick_buttons.items():
            button.setChecked(other == name)
            self.views[other].selected = other == name
            self.views[other].update()
        self.refresh()

    def refresh(self) -> None:
        """Curves and sliders from the profile (another controller, a reset …)."""
        profile = self.profile()
        for name, view in self.views.items():
            view.set_curve(profile.trigger_curves.get(name) if profile else None)
        shape = profile.trigger_shapes.get(self.editing) if profile else None
        start, full, exponent = shape or (0.0, 1.0, 1.0)
        for slider, value in ((self.start_slider, round(start * 100)), (self.full_slider, round(full * 100)),
                              (self.shape_slider, slider_of(exponent))):
            slider.blockSignals(True)
            slider.setValue(value)
            slider.blockSignals(False)
        self.start_value.setText(f"{self.start_slider.value()}%")
        self.full_value.setText(f"{self.full_slider.value()}%")
        self.shape_value.setText(self.shape_text(self.shape_slider.value()))
        measured = profile is not None and self.editing in profile.trigger_curves and shape is None
        if measured:
            set_status(self.status, f"{SHORT[self.editing]}: measured curve - the sliders start a new one")

    def shape_changed(self) -> None:
        profile = self.profile()
        if profile is None:
            return
        start, full = self.start_slider.value() / 100, self.full_slider.value() / 100
        exponent = shape_of(self.shape_slider.value())
        name = self.editing
        if start == 0 and full == 1 and exponent == 1:
            profile.trigger_curves.pop(name, None)
            profile.trigger_shapes.pop(name, None)
        else:
            profile.trigger_shapes[name] = (start, full, exponent)
            profile.trigger_curves[name] = trigger_curve(start, full, exponent)
        self.save()
        self.views[name].set_curve(profile.trigger_curves.get(name))
        set_status(self.status, "")

    def straight(self) -> None:
        profile = self.profile()
        if profile is None:
            return
        self.stop_measuring()
        profile.trigger_curves.pop(self.editing, None)
        profile.trigger_shapes.pop(self.editing, None)
        self.save()
        self.refresh()
        set_status(self.status, f"{SHORT[self.editing]} straight again")

    # Measure: one slow pull -----------------------------------------------------------------
    def start_measuring(self) -> None:
        if self.profile() is None:
            return
        if self.measuring is not None:
            self.stop_measuring("Measuring cancelled")
            return
        self.measuring = self.editing
        self.samples = []
        navigator.set_paused(True)  # the trigger must not move the UI meanwhile
        self.measure_button.setText("Cancel")
        self.timer.start(MEASURE_S * 1000)
        set_status(self.status, f"Pull {SHORT[self.editing]} slowly and evenly all the way down (about 3 seconds), "
                                f"then let go")

    def stop_measuring(self, message: str = "", error: bool = True) -> None:
        if self.measuring is None:
            return
        self.measuring = None
        self.timer.stop()
        navigator.set_paused(False)
        self.measure_button.setText("Measure")
        if message:
            set_status(self.status, message, error=error)

    def feed(self, name: str, raw: float, out: float) -> None:
        """The trigger's position now (raw 0..1, what games get 0..1)."""
        self.views[name].set_values(raw, out)
        if self.measuring != name:
            return
        self.samples.append((time.monotonic(), raw))
        if raw < 0.05 and any(x >= 0.9 for _t, x in self.samples):  # pulled all the way and let go
            self.finish_measuring()

    def finish_measuring(self) -> None:
        name = self.measuring
        curve = measured_curve(self.samples)
        if curve is None:
            self.stop_measuring("Too fast or not all the way - pull slowly and evenly, over about 3 seconds")
            return
        profile = self.profile()
        profile.trigger_curves[name] = curve
        profile.trigger_shapes.pop(name, None)
        self.save()
        self.stop_measuring()
        self.refresh()
        set_status(self.status, f"{SHORT[name]} measured - try it: the dot should now follow your finger evenly",
                   error=False)
