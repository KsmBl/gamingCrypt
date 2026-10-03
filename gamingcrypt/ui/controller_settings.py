"""Settings → Controller: live stick view, calibration and button mapping."""

from __future__ import annotations

import threading
from typing import Callable

from PySide6.QtCore import QObject, QPointF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from gamingcrypt.input import evdev as e
from gamingcrypt.input.profile import BUTTONS, TRIGGER_AXES, CalibrationSession, Capture, Profile, Translator
from gamingcrypt.input.remapper import read_absinfo
from gamingcrypt.ui import navigator, theme
from gamingcrypt.ui.system_settings import Section, _label, _on_change, _slider
from gamingcrypt.ui.widgets import big_button, set_status


class LiveReader:
    """Reads the raw controller (not grabbed) in a thread while the page is open."""

    def __init__(self, info: e.DeviceInfo, on_event: Callable[[int, int, int], None]):
        self.info = info
        self.on_event = on_event
        self.device = e.InputDevice(info.path)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def absinfo(self) -> dict[int, e.AbsInfo]:
        return read_absinfo(self.device, self.info.axes)

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                events = self.device.read(0.1)
            except OSError:
                return
            for event in events:
                self.on_event(*event)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(1)
        self.device.close()


class _Bridge(QObject):
    event = Signal(int, int, int)


class StickView(QWidget):
    """Circle with the raw stick position (grey) and what games will get (blue)."""

    def __init__(self, title: str):
        super().__init__()
        self.title = title
        self.setFixedSize(170, 190)
        self.raw = (0.0, 0.0)
        self.out = (0.0, 0.0)
        self.deadzone = 0.0

    def set_values(self, raw, out, deadzone: float) -> None:
        self.raw, self.out, self.deadzone = raw, out, deadzone
        self.update()

    def paintEvent(self, _event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = 70
        c = QPointF(85, 85)
        p.setPen(QPen(QColor(theme.SURFACE_HI), 3))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(c, r, r)
        p.setPen(QPen(QColor(theme.TEXT_DIM), 1, Qt.PenStyle.DashLine))
        p.drawEllipse(c, r * self.deadzone, r * self.deadzone)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.TEXT_DIM))
        p.drawEllipse(QPointF(c.x() + self.raw[0] * r, c.y() + self.raw[1] * r), 6, 6)
        p.setBrush(QColor(theme.ACCENT))
        p.drawEllipse(QPointF(c.x() + self.out[0] * r, c.y() + self.out[1] * r), 9, 9)
        p.setPen(QColor(theme.TEXT_DIM))
        p.drawText(0, 172, 170, 18, Qt.AlignmentFlag.AlignCenter, self.title)


class ControllerPage(QWidget):
    def __init__(self, service, reader_factory=LiveReader):
        super().__init__()
        self.service = service
        self.reader_factory = reader_factory
        self.reader = None
        self.info: e.DeviceInfo | None = None
        self.profile: Profile | None = None
        self.absinfo: dict[int, e.AbsInfo] = {}
        self.translator: Translator | None = None
        self.session: CalibrationSession | None = None
        self.capture: tuple[str, Capture] | None = None
        self._was_running = False
        self._bridge = _Bridge(self)
        self._bridge.event.connect(self.on_event)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        top = Section("Controller")
        self.device_label = _label()
        top.body.addWidget(self.device_label)
        row = QHBoxLayout()
        self.enable_button = big_button("Use my calibration and mapping", checkable=True)
        self.enable_button.setChecked(service.enabled)
        self.enable_button.toggled.connect(self.set_enabled)
        row.addWidget(self.enable_button)
        rescan = big_button("Rescan")
        rescan.clicked.connect(self.rescan)
        row.addWidget(rescan)
        row.addStretch()
        top.body.addLayout(row)
        top.body.addWidget(_label("Games then see a virtual Xbox controller with your mapping and calibration. "
                                  "Turn off Steam Input for the built-in controller if inputs arrive twice."))
        top.body.addWidget(top.status)
        self.top = top
        layout.addWidget(top)

        sticks = Section("Sticks")
        views = QHBoxLayout()
        self.left_view = StickView("Left stick")
        self.right_view = StickView("Right stick")
        views.addWidget(self.left_view)
        views.addWidget(self.right_view)
        views.addStretch()
        sticks.body.addLayout(views)
        self.deadzone_value = QLabel()
        self.deadzone_slider = _slider(0, 30, 8)
        _on_change(self.deadzone_slider, self.set_deadzone, lambda v: self.deadzone_value.setText(f"{v}%"))
        sticks.row("Deadzone", self.deadzone_slider, self.deadzone_value)
        self.calibration_text = _label()
        sticks.body.addWidget(self.calibration_text)
        cal_row = QHBoxLayout()
        self.calibrate_button = big_button("Calibrate sticks and triggers", "primary")
        self.calibrate_button.clicked.connect(self.start_calibration)
        cal_row.addWidget(self.calibrate_button)
        self.next_button = big_button("Next")
        self.next_button.clicked.connect(self.calibration_next)
        cal_row.addWidget(self.next_button)
        self.cancel_cal_button = big_button("Cancel")
        self.cancel_cal_button.clicked.connect(self.cancel_calibration)
        cal_row.addWidget(self.cancel_cal_button)
        cal_row.addStretch()
        sticks.body.addLayout(cal_row)
        sticks.body.addWidget(sticks.status)
        self.sticks = sticks
        layout.addWidget(sticks)

        buttons = Section("Buttons")
        buttons.body.addWidget(_label("Tap Remap, then press the button (or push the stick/trigger) "
                                      "that should act as it."))
        self.rows: dict[str, tuple[QLabel, object]] = {}
        for name, label, _out in BUTTONS:
            line = QHBoxLayout()
            caption = QLabel(label)
            caption.setFixedWidth(260)
            line.addWidget(caption)
            current = QLabel()
            current.setObjectName("detailMeta")
            line.addWidget(current, 1)
            button = big_button("Remap")
            button.clicked.connect(lambda _=False, n=name: self.start_capture(n))
            line.addWidget(button)
            buttons.body.addLayout(line)
            self.rows[name] = (current, button)
        reset = big_button("Reset to defaults")
        reset.clicked.connect(self.reset)
        buttons.body.addWidget(reset, alignment=Qt.AlignmentFlag.AlignLeft)
        buttons.body.addWidget(buttons.status)
        self.buttons = buttons
        layout.addWidget(buttons)
        self._set_calibration_ui(False)
        self.load_device()

    # device -----------------------------------------------------------------
    def load_device(self) -> None:
        self.info = self.service.device()
        has = self.info is not None
        for section in (self.sticks, self.buttons):
            section.setVisible(has)
        if not has:
            self.device_label.setText("No controller found. Connect one and tap Rescan.")
            self.profile = None
            return
        self.device_label.setText(f"Controller: {self.info.name}")
        self.profile = self.service.profile(self.info)
        self.refresh_rows()

    def rescan(self) -> None:
        self.stop_reader()
        self.load_device()
        if self.isVisible():
            self.start_reader()

    def set_enabled(self, enabled: bool) -> None:
        ok = self.service.set_enabled(enabled)
        if enabled and self.isVisible():
            # Page is open and reads the raw controller - start it when leaving the page.
            self.service.stop()
            self._was_running = True
            ok = True
        message = "Virtual controller on" if enabled else "Virtual controller off"
        set_status(self.top.status, message if ok else f"Could not start: {self.service.error}", error=not ok)

    # live input ----------------------------------------------------------------
    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        self._was_running = self.service.pause()
        self.start_reader()

    def hideEvent(self, event):  # noqa: N802
        super().hideEvent(event)
        self.stop_reader()
        self.cancel_calibration()
        self.capture = None
        navigator.set_paused(False)
        self.service.resume(self._was_running or self.service.enabled)

    def start_reader(self) -> None:
        if self.info is None or self.reader is not None:
            return
        try:
            self.reader = self.reader_factory(self.info, self._bridge.event.emit)
            self.absinfo = self.reader.absinfo()
            self.reader.start()
        except OSError as exc:
            self.reader = None
            set_status(self.top.status, f"Can't read the controller: {exc.strerror or exc}", error=True)
            return
        self.translator = Translator(self.profile, self.absinfo)
        self.translator.feed(e.EV_SYN, e.SYN_REPORT, 0)

    def stop_reader(self) -> None:
        if self.reader is not None:
            self.reader.stop()
            self.reader = None

    def on_event(self, ev_type: int, code: int, value: int) -> None:
        if self.session is not None:
            self.session.feed(ev_type, code, value)
            if self.session.step == "range":
                cov = self.session.coverage()
                if cov:
                    worst = min(cov.values())
                    self.calibration_text.setText(f"Step 2/2: rotate both sticks in full circles and press both "
                                                  f"triggers fully, then tap Done. Least covered: {worst:.0%}")
        if self.capture is not None:
            name, capture = self.capture
            source = capture.feed(ev_type, code, value)
            if source is not None:
                self.assign(name, source)
        if self.translator is not None:
            self.translator.feed(ev_type, code, value)
            if ev_type == e.EV_SYN:
                self.update_views()

    def update_views(self) -> None:
        t = self.translator
        axes = self.profile.axes
        out = t.last
        for view, (x, y), (ox, oy) in (
            (self.left_view, ("lx", "ly"), (e.ABS_X, e.ABS_Y)),
            (self.right_view, ("rx", "ry"), (e.ABS_RX, e.ABS_RY)),
        ):
            raw = (t.normalized(axes[x]) if axes.get(x) is not None else 0.0,
                   t.normalized(axes[y]) if axes.get(y) is not None else 0.0)
            done = (out.get((e.EV_ABS, ox), 0) / 32767, out.get((e.EV_ABS, oy), 0) / 32767)
            view.set_values(raw, done, self.profile.deadzone)

    # profile ----------------------------------------------------------------------
    def refresh_rows(self) -> None:
        for name, (current, button) in self.rows.items():
            source = self.profile.buttons.get(name)
            current.setText(source.describe() if source else "not mapped")
            button.setText("Remap")
        dz = round(self.profile.deadzone * 100)
        self.deadzone_slider.blockSignals(True)
        self.deadzone_slider.setValue(dz)
        self.deadzone_slider.blockSignals(False)
        self.deadzone_value.setText(f"{dz}%")
        calibrated = bool(self.profile.calibration)
        self.calibration_text.setText("Calibrated" if calibrated else "Not calibrated yet (factory ranges are used)")

    def save(self) -> None:
        self.service.save_profile(self.info, self.profile)
        if self.translator is not None:
            self.translator = Translator(self.profile, self.absinfo)
            self.translator.feed(e.EV_SYN, e.SYN_REPORT, 0)

    def set_deadzone(self, percent: int) -> None:
        if self.profile is None:
            return
        self.profile.deadzone = percent / 100
        self.save()
        if self.translator is not None:
            self.update_views()

    def start_capture(self, name: str) -> None:
        if self.capture is not None and self.capture[0] == name:
            self.capture = None  # tapping again cancels
            navigator.set_paused(False)
            self.refresh_rows()
            return
        self.refresh_rows()
        current = dict(self.translator.abs) if self.translator else None
        self.capture = (name, Capture(self.absinfo, current))
        navigator.set_paused(True)  # the next press is the new binding, not a UI action
        label, button = self.rows[name]
        label.setText("Press the button now…")
        button.setText("Cancel")
        set_status(self.buttons.status, f"Waiting for {dict((b[0], b[1]) for b in BUTTONS)[name]}…")

    def assign(self, name: str, source) -> None:
        self.capture = None
        navigator.set_paused(False)
        self.profile.buttons[name] = source
        if name in TRIGGER_AXES:
            info = self.absinfo.get(source.code) if source.kind == "abs" else None
            analog = info is not None and info.maximum - info.minimum > 2 and source.direction > 0
            self.profile.axes[name] = source.code if analog else None
        self.save()
        self.refresh_rows()
        set_status(self.buttons.status, f"{dict((b[0], b[1]) for b in BUTTONS)[name]} → {source.describe()}")

    def reset(self) -> None:
        self.profile = self.service.reset_profile(self.info)
        self.translator = Translator(self.profile, self.absinfo) if self.absinfo else None
        self.refresh_rows()
        set_status(self.buttons.status, "Mapping and calibration reset")

    # calibration ---------------------------------------------------------------------
    def _set_calibration_ui(self, active: bool) -> None:
        self.calibrate_button.setVisible(not active)
        self.next_button.setVisible(active)
        self.cancel_cal_button.setVisible(active)

    def start_calibration(self) -> None:
        if self.profile is None:
            return
        self.session = CalibrationSession(self.profile, self.absinfo)
        navigator.set_paused(True)  # moving sticks / triggers must not move the UI focus
        self._set_calibration_ui(True)
        self.next_button.setText("Next")
        self.calibration_text.setText("Step 1/2: don't touch the sticks and triggers, then tap Next.")
        set_status(self.sticks.status, "")

    def calibration_next(self) -> None:
        if self.session is None:
            return
        if self.session.step == "center":
            self.session.next_step()
            self.next_button.setText("Done")
            self.calibration_text.setText("Step 2/2: rotate both sticks in full circles and press both triggers "
                                          "fully, then tap Done.")
            return
        profile, message = self.session.finish()
        if profile is None:
            set_status(self.sticks.status, message, error=True)
            return
        self.profile = profile
        self.session = None
        navigator.set_paused(False)
        self._set_calibration_ui(False)
        self.save()
        self.refresh_rows()
        set_status(self.sticks.status, f"{message} - deadzone {profile.deadzone:.0%}")

    def cancel_calibration(self) -> None:
        navigator.set_paused(False)
        if self.session is not None:
            self.session = None
            self._set_calibration_ui(False)
            if self.profile is not None:
                self.refresh_rows()
