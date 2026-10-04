"""Settings sections for the device itself: display, power and audio."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QLabel, QSlider, QVBoxLayout, QWidget

from gamingcrypt.system.controls import SystemControls
from gamingcrypt.ui.tasks import run_async
from gamingcrypt.ui.widgets import big_button, set_status

KEEP_SECONDS = 15


def _label(text: str = "", name: str = "detailMeta") -> QLabel:
    label = QLabel(text)
    label.setObjectName(name)
    label.setWordWrap(True)
    return label


def _slider(low: int, high: int, value: int) -> QSlider:
    slider = QSlider(Qt.Orientation.Horizontal)
    slider.setRange(low, high)
    slider.setValue(value)
    slider.setPageStep(max(1, (high - low) // 10))
    return slider


def _on_change(slider: QSlider, apply: Callable[[int], None], show: Callable[[int], None]) -> None:
    """Apply when the finger lifts (or on a tap on the groove), show the value while dragging."""
    slider.valueChanged.connect(show)
    slider.sliderReleased.connect(lambda: apply(slider.value()))
    slider.valueChanged.connect(lambda v: None if slider.isSliderDown() else apply(v))


class Section(QFrame):
    def __init__(self, title: str):
        super().__init__()
        self.setObjectName("card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(24, 18, 24, 18)
        heading = QLabel(title)
        heading.setObjectName("section")
        self.body.addWidget(heading)
        self.status = _label("", "status")

    def unavailable(self, text: str) -> None:
        self.body.addWidget(_label(text))

    def row(self, caption: str, widget: QWidget, value: QLabel | None = None) -> None:
        line = QHBoxLayout()
        cap = QLabel(caption)
        cap.setFixedWidth(220)
        line.addWidget(cap)
        line.addWidget(widget, 1)
        if value is not None:
            value.setFixedWidth(90)
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            line.addWidget(value)
        self.body.addLayout(line)


class DisplaySection(Section):
    def __init__(self, controls: SystemControls, config: dict, save: Callable[[dict], None]):
        super().__init__("Display")
        self.controls, self.config, self.save = controls, config, save
        self.backend = controls.display
        self.output = None
        self.previous = None
        self.remaining = 0
        self._countdown = QTimer(self)
        self._countdown.timeout.connect(self._tick)

        outputs = self.backend.outputs() if self.backend else []
        if not outputs:
            from gamingcrypt.session.mode import in_gaming_session

            if in_gaming_session():
                self.unavailable("Resolution and refresh rate: managed by gamescope in gaming mode. "
                                 "Own options (e.g. \"-f -W 1280 -H 800 -r 60\") go into "
                                 "~/.config/gamingcrypt/gamescope-args.")
            else:
                self.unavailable("Resolution and refresh rate: not supported on this desktop "
                                 "(needs KDE, a wlroots compositor or X11).")
        else:
            self.output = outputs[0]
            self.resolution = QComboBox()
            self.refresh = QComboBox()
            for w, h in self.output.resolutions():
                # Plain string as item data: PySide would turn a tuple into a list.
                self.resolution.addItem(f"{w}×{h}", f"{w}x{h}")
            self.resolution.currentIndexChanged.connect(self._fill_rates)
            self.row("Resolution", self.resolution)
            self.row("Refresh rate", self.refresh)
            self.apply_button = big_button("Apply", "primary")
            self.apply_button.clicked.connect(self.apply_mode)
            self.body.addWidget(self.apply_button, alignment=Qt.AlignmentFlag.AlignLeft)
            self.confirm = QFrame()
            confirm = QHBoxLayout(self.confirm)
            confirm.setContentsMargins(0, 0, 0, 0)
            self.confirm_label = _label()
            confirm.addWidget(self.confirm_label, 1)
            self.keep_button = big_button("Keep", "primary")
            self.keep_button.clicked.connect(self.keep)
            confirm.addWidget(self.keep_button)
            self.revert_button = big_button("Revert")
            self.revert_button.clicked.connect(self.revert)
            confirm.addWidget(self.revert_button)
            self.confirm.hide()
            self.body.addWidget(self.confirm)
            self._select_current()

        self.brightness = controls.brightness
        level = self.brightness.get() if self.brightness else None
        if level is None:
            self.unavailable("Brightness: not available (install brightnessctl).")
        else:
            self.brightness_value = QLabel(f"{level}%")
            self.brightness_slider = _slider(5, 100, level)
            _on_change(self.brightness_slider, self.set_brightness,
                       lambda v: self.brightness_value.setText(f"{v}%"))
            self.row("Brightness", self.brightness_slider, self.brightness_value)
        self.body.addWidget(self.status)

    def _select_current(self) -> None:
        cur = self.output.current
        if cur is not None:
            index = self.resolution.findData(f"{cur.width}x{cur.height}")
            self.resolution.setCurrentIndex(max(index, 0))
        self._fill_rates()

    def _fill_rates(self) -> None:
        data = self.resolution.currentData()
        if not data:
            return
        size = tuple(int(v) for v in data.split("x"))
        self.refresh.clear()
        for mode in self.output.refresh_rates(*size):
            self.refresh.addItem(mode.refresh_label, mode)
        cur = self.output.current
        if cur is not None and (cur.width, cur.height) == tuple(size):
            for i in range(self.refresh.count()):
                if round(self.refresh.itemData(i).refresh) == round(cur.refresh):
                    self.refresh.setCurrentIndex(i)

    def selected_mode(self):
        return self.refresh.currentData()

    def apply_mode(self, mode=None) -> None:
        mode = mode or self.selected_mode()
        if mode is None or mode == self.output.current:
            return
        self.previous = self.output.current
        set_status(self.status, "Changing display mode…")
        run_async(lambda: self.backend.set_mode(self.output, mode), lambda r: self._applied(mode, r), owner=self)

    def _applied(self, mode, result) -> None:
        ok, message = result
        if not ok:
            set_status(self.status, message, error=True)
            return
        self.output.current = mode
        set_status(self.status, "")
        # Like a desktop: if the screen went black nobody can press "Keep" -> revert by itself.
        self.remaining = KEEP_SECONDS
        self.confirm.show()
        self._tick(start=True)

    def _tick(self, start: bool = False) -> None:
        if not start:
            self.remaining -= 1
        if self.remaining <= 0:
            self.revert()
            return
        self.confirm_label.setText(f"Keep this display mode? Reverting in {self.remaining} s")
        if start:
            self._countdown.start(1000)

    def keep(self) -> None:
        self._countdown.stop()
        self.confirm.hide()
        mode = self.output.current
        self.config["system"]["display"] = {"output": self.output.name, "width": mode.width, "height": mode.height,
                                            "refresh": mode.refresh}
        self.save(self.config)
        set_status(self.status, f"Display set to {mode.resolution} @ {mode.refresh_label}")

    def revert(self) -> None:
        self._countdown.stop()
        self.confirm.hide()
        previous, self.previous = self.previous, None
        if previous is None:
            return
        set_status(self.status, "Reverting…")
        run_async(lambda: self.backend.set_mode(self.output, previous),
                  lambda r: self._reverted(previous, r), owner=self)

    def _reverted(self, mode, result) -> None:
        ok, message = result
        if ok:
            self.output.current = mode
            self._select_current()
            set_status(self.status, f"Back to {mode.resolution} @ {mode.refresh_label}")
        else:
            set_status(self.status, message, error=True)

    def set_brightness(self, percent: int) -> None:
        if not self.brightness.set(percent):
            set_status(self.status, "Could not change the brightness", error=True)


class PowerSection(Section):
    def __init__(self, controls: SystemControls, config: dict, save: Callable[[dict], None]):
        super().__init__("Power")
        self.config, self.save = config, save
        self.power = controls.power
        limit = self.power.read() if self.power else None
        if limit is None:
            self.unavailable("Max power consumption: no adjustable power limit found on this device.")
        else:
            self.value = QLabel(f"{limit.current_w} W")
            self.slider = _slider(limit.min_w, limit.max_w, limit.current_w)
            _on_change(self.slider, self.set_limit, lambda v: self.value.setText(f"{v} W"))
            self.row("Max power", self.slider, self.value)
            hint = f"{limit.min_w}-{limit.max_w} W ({limit.source}). Lower = longer battery, higher = more FPS."
            if not self.power.can_set:
                hint += " Run install.sh to allow changing it."
                self.slider.setEnabled(False)
            self.body.addWidget(_label(hint))
        self.body.addWidget(self.status)

    def set_limit(self, watts: int) -> None:
        set_status(self.status, f"Setting {watts} W…")
        run_async(lambda: self.power.set(watts), lambda r: self._done(watts, r), owner=self)

    def _done(self, watts: int, result) -> None:
        ok, message = result
        set_status(self.status, message, error=not ok)
        if ok:
            self.config["system"]["power_limit_w"] = watts
            self.save(self.config)


class AudioSection(Section):
    def __init__(self, controls: SystemControls):
        super().__init__("Audio")
        self.audio = controls.audio
        self.combos: dict[str, QComboBox] = {}
        self.sliders: dict[str, QSlider] = {}
        if self.audio is None:
            self.unavailable("Audio: pactl not found (PipeWire or PulseAudio needed).")
        else:
            for kind, caption in (("output", "Output"), ("input", "Input")):
                self._build(kind, caption)
        self.body.addWidget(self.status)

    def _build(self, kind: str, caption: str) -> None:
        devices = self.audio.devices(kind)
        if not devices:
            self.unavailable(f"No audio {kind} device found.")
            return
        combo = QComboBox()
        for d in devices:
            combo.addItem(d.description, d.name)
        default = next((d for d in devices if d.is_default), devices[0])
        combo.setCurrentIndex(combo.findData(default.name))  # before connecting: no switch on open
        combo.currentIndexChanged.connect(lambda _i, k=kind: self.set_device(k))
        self.combos[kind] = combo
        self.row(f"{caption} device", combo)
        value = QLabel(f"{default.volume}%")
        slider = _slider(0, 100, min(default.volume, 100))
        _on_change(slider, lambda v, k=kind: self.set_volume(k, v), lambda v, lbl=value: lbl.setText(f"{v}%"))
        self.sliders[kind] = slider
        self.row(f"{caption} volume", slider, value)

    def set_device(self, kind: str) -> None:
        name = self.combos[kind].currentData()
        if not self.audio.set_default(kind, name):
            set_status(self.status, f"Could not switch the {kind} device", error=True)
            return
        set_status(self.status, f"{kind.capitalize()}: {self.combos[kind].currentText()}")
        device = next((d for d in self.audio.devices(kind) if d.name == name), None)
        if device is not None:
            self.sliders[kind].blockSignals(True)
            self.sliders[kind].setValue(min(device.volume, 100))
            self.sliders[kind].blockSignals(False)

    def set_volume(self, kind: str, percent: int) -> None:
        name = self.combos[kind].currentData()
        if not self.audio.set_volume(kind, name, percent):
            set_status(self.status, "Could not change the volume", error=True)
