"""Settings sections for the device itself: display, power and audio."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt, QTimer, Signal
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


class AppearanceSection(Section):
    """Dark or light - switched at once, everywhere."""

    changed = Signal(str)

    def __init__(self, config: dict, save: Callable[[dict], None]):
        super().__init__("Appearance")
        from gamingcrypt.ui import theme

        self.config, self.save = config, save
        row = QHBoxLayout()
        row.setSpacing(12)
        self.buttons = {}
        for name, label in (("dark", "🌙  Dark"), ("light", "☀  Light")):
            button = big_button(label, checkable=True)
            button.setMinimumWidth(180)
            button.clicked.connect(lambda _=False, n=name: self.choose(n))
            row.addWidget(button)
            self.buttons[name] = button
        row.addStretch()
        caption = QLabel("Theme")
        caption.setFixedWidth(220)
        line = QHBoxLayout()
        line.addWidget(caption)
        line.addLayout(row, 1)
        self.body.addLayout(line)
        self._show(theme.current)

    def _show(self, name: str) -> None:
        for key, button in self.buttons.items():
            button.setChecked(key == name)

    def choose(self, name: str) -> None:
        from PySide6.QtWidgets import QApplication

        from gamingcrypt.ui import theme

        self.config.setdefault("appearance", {})["theme"] = name
        self.save(self.config)
        theme.apply(name, QApplication.instance())
        self._show(name)
        self.changed.emit(name)


class DisplaySection(Section):
    def __init__(self, controls: SystemControls, config: dict, save: Callable[[dict], None],
                 restart_gaming: Callable[[], None] | None = None):
        super().__init__("Display")
        self.controls, self.config, self.save = controls, config, save
        self.restart_gaming = restart_gaming
        self.backend = controls.display
        self.output = None
        self.previous = None
        self.remaining = 0
        self._countdown = QTimer(self)
        self._countdown.timeout.connect(self._tick)

        from gamingcrypt.session.mode import in_gaming_session

        outputs = self.backend.outputs() if self.backend else []
        if in_gaming_session():
            self._build_gamescope()
        elif not outputs:
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

    # gaming mode: gamescope options, applied by restarting gaming mode -------------
    def _build_gamescope(self) -> None:
        from gamingcrypt.session import mode

        self.gamescope = True
        native = mode.panel_size() or (1280, 800)
        current = mode.parse_display(mode.read_args())
        self.gs_resolution = QComboBox()
        for w, h in mode.render_sizes(native):
            label = f"{w}×{h}" + (" (native)" if (w, h) == native else "")
            self.gs_resolution.addItem(label, f"{w}x{h}")
        wanted = f"{current.get('width', native[0])}x{current.get('height', native[1])}"
        self.gs_resolution.setCurrentIndex(max(0, self.gs_resolution.findData(wanted)))
        self.gs_refresh = QComboBox()
        self.gs_refresh.addItem("Default (screen)", 0)
        for hz in mode.REFRESH_RATES:
            self.gs_refresh.addItem(f"{hz} Hz", hz)
        self.gs_refresh.setCurrentIndex(max(0, self.gs_refresh.findData(current.get("refresh", 0))))
        self.row("Resolution", self.gs_resolution)
        self.row("Refresh rate", self.gs_refresh)
        actual = mode.actual_mode()
        self.body.addWidget(_label("Lower resolutions are upscaled to the screen: more FPS, less power."
                                   + (f" Screen right now: {actual}." if actual else "")))
        self.gs_apply = big_button("Apply - restarts gaming mode", "primary")
        self.gs_apply.clicked.connect(self.apply_gamescope)
        self.body.addWidget(self.gs_apply, alignment=Qt.AlignmentFlag.AlignLeft)

    def apply_gamescope(self) -> None:
        from gamingcrypt.session import mode

        w, h = (int(v) for v in self.gs_resolution.currentData().split("x"))
        native = mode.panel_size() or (1280, 800)
        refresh = self.gs_refresh.currentData() or None
        size = (None, None) if (w, h) == native else (w, h)
        mode.apply_display(size[0], size[1], refresh)
        set_status(self.status, "Closing Steam and restarting gaming mode - you'll be asked to keep the "
                                "new mode (it reverts after 15 s)")
        self.gs_apply.setEnabled(False)
        if self.restart_gaming is not None:
            self.restart_gaming()

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
        # power button (gaming mode)
        system = self.config.setdefault("system", {})
        self.power_button = QComboBox()
        self.power_button.addItem("Open the power menu", "menu")
        self.power_button.addItem("Sleep", "sleep")
        choice = "menu" if system.get("sleep_broken") else system.get("power_button", "menu")
        self.power_button.setCurrentIndex(max(0, self.power_button.findData(choice)))
        self.power_button.currentIndexChanged.connect(self._power_button_chosen)
        self.row("Power button", self.power_button)
        self.sleep_hint = _label("")
        self.body.addWidget(self.sleep_hint)
        self._update_sleep_hint()
        self.body.addWidget(self.status)

    def _update_sleep_hint(self) -> None:
        if self.config["system"].get("sleep_broken"):
            text = ("This device didn't wake up from sleep last time, so sleep is off. Choose Sleep to try "
                    "again - if it hangs, hold the power button for 10 seconds.")
        else:
            text = ("Sleep doesn't wake up again on every device. If it hangs, hold the power button for "
                    "10 seconds - GamingCrypt notices and switches sleep off.")
        self.sleep_hint.setText(text)

    def _power_button_chosen(self, _index: int) -> None:
        system = self.config["system"]
        system["power_button"] = self.power_button.currentData()
        if system["power_button"] == "sleep":
            system["sleep_broken"] = False  # the user wants to try again
        self.save(self.config)
        self._update_sleep_hint()

    def set_limit(self, watts: int) -> None:
        set_status(self.status, f"Setting {watts} W…")
        run_async(lambda: self.power.set(watts), lambda r: self._done(watts, r), owner=self)

    def _done(self, watts: int, result) -> None:
        ok, message = result
        set_status(self.status, message, error=not ok)
        if ok:
            self.config["system"]["power_limit_w"] = watts
            self.save(self.config)


def step_text(step: int) -> str:
    if step == 0:
        return "Off"
    return f"{step:+d}%" + (" (swapped)" if step < 0 else "")


class AudioSection(Section):
    def __init__(self, controls: SystemControls, config: dict | None = None,
                 save: Callable[[dict], None] = lambda c: None):
        super().__init__("Audio")
        self.config, self.save = config if config is not None else {"system": {}}, save
        self.audio = controls.audio
        self.combos: dict[str, QComboBox] = {}
        self.sliders: dict[str, QSlider] = {}
        if self.audio is None:
            self.unavailable("Audio: pactl not found (PipeWire or PulseAudio needed).")
        else:
            for kind, caption in (("output", "Output"), ("input", "Input")):
                self._build(kind, caption)
            self._build_step()
        self.body.addWidget(self.status)

    def _build_step(self) -> None:
        from gamingcrypt.ui.volume_osd import MAX_STEP, clamp_step

        step = clamp_step(self.config.setdefault("system", {}).get("volume_step", 5))
        self.step_value = QLabel(step_text(step))
        self.step_slider = _slider(-MAX_STEP, MAX_STEP, step)
        self.step_slider.setPageStep(1)
        _on_change(self.step_slider, self.set_step, lambda v: self.step_value.setText(step_text(v)))
        self.row("Volume buttons", self.step_slider, self.step_value)
        self.step_value.setFixedWidth(150)
        self.body.addWidget(_label("How much one press of + / - changes the volume in gaming mode. "
                                   "Below 0 the buttons are swapped, 0 turns them off."))

    def set_step(self, step: int) -> None:
        if self.config["system"].get("volume_step") == step:
            return
        self.config["system"]["volume_step"] = step
        self.save(self.config)

    def _build(self, kind: str, caption: str) -> None:
        devices = self.audio.devices(kind)
        if not devices:
            self.unavailable(f"No audio {kind} device found.")
            return
        combo = QComboBox()
        # long device names get elided instead of widening the page
        combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(8)
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
