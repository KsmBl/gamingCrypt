"""Settings → Controller → Adaptive triggers: what a PS5 controller's triggers push back with
(input/dualsense - the same effects as the PS5 Shock Configurator). Each effect has its own
settings; a change goes to the controller at once, and a bar shows where the trigger is and where
its effect sits - pull it to feel it."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QGridLayout, QLabel, QWidget

from gamingcrypt.input import dualsense
from gamingcrypt.input.dualsense import BOW, BUMP, BUZZ, OFF, RESISTANCE, RISING, RISING_BUZZ, STOP, Effect
from gamingcrypt.ui import theme
from gamingcrypt.ui.combo import ComboBox
from gamingcrypt.ui.system_settings import Section, _label, _on_change, _slider
from gamingcrypt.ui.widgets import big_button, set_status

NAMES = {"lt": "LT / L2 (aim in most games)", "rt": "RT / R2 (shoot, gas)"}
FIELDS = ("position", "width", "strength", "strength_end", "end", "snap", "speed")
PRESETS = (  # (name, LT, RT - None: left as it is)
    ("Aim stop on LT", Effect(STOP, 50, 6), None),
    ("Aim bump on LT", Effect(BUMP, 50, 7), None),
    ("Shooter", Effect(STOP, 50, 6), Effect(STOP, 40, 7)),
    ("Machine gun", Effect(BUMP, 40, 6), Effect(BUZZ, 20, 6, speed=25)),
    ("Racing", Effect(RISING, 10, 3, strength_end=8), Effect(RESISTANCE, 20, 3)),
    ("Bow", Effect(STOP, 30, 4), Effect(BOW, 10, 6, end=70, snap=8)),
    ("Engine", Effect(RISING, 10, 2, strength_end=6), Effect(RISING_BUZZ, 10, 1, strength_end=8, speed=40)),
    ("Both off", Effect(OFF), Effect(OFF)),
)


class TriggerMeter(QWidget):
    """Where the trigger is (the bar over it) and where its effect is (marked)."""

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(34)
        self.value = 0.0
        self.effect = Effect()

    def set_value(self, value: float) -> None:
        self.value = value
        self.update()

    def set_effect(self, effect: Effect) -> None:
        self.effect = effect
        self.update()

    def paintEvent(self, _event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        box = QRectF(1, 6, self.width() - 2, self.height() - 12)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(theme.SURFACE_HI))
        p.drawRoundedRect(box, 8, 8)
        e = self.effect
        mark = QColor("#e5a33b")

        def band(a: float, b: float, alpha: int) -> None:
            color = QColor(mark)
            color.setAlpha(alpha)
            p.setBrush(color)
            p.drawRect(QRectF(box.left() + box.width() * a, box.top(), box.width() * max(0.0, b - a), box.height()))

        def line(x: float) -> None:
            p.setBrush(mark)
            p.drawRect(QRectF(box.left() + box.width() * x - 2, box.top() - 4, 5, box.height() + 8))

        x = round(e.position / 10) / 10
        if e.kind == STOP:
            start = max(0.2, min(0.7, x))
            band(start, min(0.8, start + max(0.1, round(e.width / 10) / 10)), 90)
            line(start)
        elif e.kind == BUMP:
            band(x, min(1.0, x + max(0.1, round(e.width / 10) / 10)), 170)
        elif e.kind == RESISTANCE:
            band(x, 1.0, 110)
        elif e.kind == RISING:  # more and more
            steps = max(1, round((1 - x) * 10))
            for i in range(steps):
                level = e.strength + (e.strength_end - e.strength) * i / max(1, steps - 1)
                band(x + i / 10, x + (i + 1) / 10, int(40 + level * 22))
        elif e.kind == BOW:
            end = max(x + 0.1, min(0.8, round(e.end / 10) / 10))
            band(x, end, 120)
            line(end)
        elif e.kind in (BUZZ, RISING_BUZZ):  # stripes - rising: stronger and taller toward the end
            left = box.left() + box.width() * x
            pos = left
            while pos < box.right():
                if e.kind == RISING_BUZZ:
                    share = (pos - left) / max(1.0, box.right() - left)
                    level = e.strength + (e.strength_end - e.strength) * share
                    alpha, height = int(50 + level * 15), box.height() * (0.35 + 0.65 * level / 8)
                else:
                    alpha, height = 170, box.height()
                color = QColor(mark)
                color.setAlpha(alpha)
                p.setBrush(color)
                p.drawRect(QRectF(pos, box.center().y() - height / 2, min(3.0, box.right() - pos), height))
                pos += 6.0
        accent = QColor(theme.ACCENT)  # where the trigger is: over the effect, which stays visible
        accent.setAlpha(200)
        p.setBrush(accent)
        p.drawRoundedRect(QRectF(box.left(), box.top() + box.height() * 0.25, box.width() * self.value,
                                 box.height() * 0.5), 4, 4)


class TriggerEffectBox(Section):
    """One trigger: its effect, and that effect's own settings (dualsense.PARAMS)."""

    def __init__(self, name: str, effect: Effect, changed: Callable[[], None]):
        super().__init__(NAMES[name])
        self.name = name
        self.changed = changed
        self.values = effect  # every setting - also those the effect shown doesn't use
        self.meter = TriggerMeter()
        self.body.addWidget(self.meter)
        grid = QGridLayout()
        grid.setColumnStretch(1, 1)
        grid.setHorizontalSpacing(16)
        self.kind = ComboBox()
        for kind, label, _text in dualsense.EFFECTS:
            self.kind.addItem(label, kind)
        caption = QLabel("Effect")
        caption.setFixedWidth(200)
        grid.addWidget(caption, 0, 0)
        grid.addWidget(self.kind, 0, 1, 1, 2)
        self.rows: dict[str, tuple[QLabel, object, QLabel]] = {}
        for line, field in enumerate(FIELDS, start=1):
            caption, slider, value = QLabel(), _slider(0, 1, 0), QLabel()
            value.setFixedWidth(80)
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            _on_change(slider, lambda _v: self._changed(), lambda _v: self._shown())
            grid.addWidget(caption, line, 0)
            grid.addWidget(slider, line, 1)
            grid.addWidget(value, line, 2)
            self.rows[field] = (caption, slider, value)
        self.body.addLayout(grid)
        self.about = _label("")
        self.body.addWidget(self.about)
        self.kind.currentIndexChanged.connect(lambda _i: self._kind_chosen())
        self.set_effect(effect)

    def params(self) -> tuple:
        return dualsense.PARAMS[self.kind.currentData()]

    def effect(self) -> Effect:
        values = self.values.to_dict()
        values["effect"] = self.kind.currentData()
        for field, _caption, _low, _high, step, _unit in self.params():
            values[field] = self.rows[field][1].value() * step
        return Effect.from_dict(values)

    def set_effect(self, effect: Effect) -> None:
        self.values = effect
        self.kind.blockSignals(True)
        self.kind.setCurrentIndex(max(0, self.kind.findData(effect.kind)))
        self.kind.blockSignals(False)
        self._layout_rows()

    def _layout_rows(self) -> None:
        """The current effect's settings shown (at the values kept), the others hidden."""
        params = {p[0]: p for p in self.params()}
        for field, (caption, slider, value) in self.rows.items():
            shown = field in params
            for widget in (caption, slider, value):
                widget.setVisible(shown)
            if shown:
                _field, text, low, high, step, _unit = params[field]
                slider.blockSignals(True)
                slider.setRange(low // step, high // step)  # whole steps: the controller's zones
                slider.setPageStep(1)
                slider.setValue(round(getattr(self.values, field) / step))
                slider.blockSignals(False)
                caption.setText(text)
        self._shown()

    def _shown(self) -> None:
        effect = self.effect()
        for field, _caption, _low, _high, _step, unit in self.params():
            number = getattr(effect, field)
            self.rows[field][2].setText(f"{number}{unit}" if unit == "%" else f"{number} {unit}")
        self.about.setText(next(text for k, _l, text in dualsense.EFFECTS if k == effect.kind))
        self.meter.set_effect(effect)

    def _kind_chosen(self) -> None:
        self._layout_rows()
        self._changed()

    def _changed(self) -> None:
        self.values = self.effect()
        self._shown()
        self.changed()


class AdaptiveTriggersSection(Section):
    """Both triggers, kept in config["input"]["adaptive_triggers"]; sent with ``send``.
    ``refresh`` when its page is shown, ``stop`` when it's left (the live bars)."""

    def __init__(self, config: dict, save: Callable[[dict], None], send=dualsense.apply, find=dualsense.find,
                 reader_factory=dualsense.TriggerReader, set_charge=dualsense.set_charge_only):
        super().__init__("PS5 controller")
        self.config, self.save_config, self.send, self.find = config, save, send, find
        self.set_charge = set_charge
        self.reader_factory = reader_factory
        self.reader = None
        self.body.addWidget(_label("A PS5 controller's triggers can push back - a stop on the aim trigger, a brake "
                                   "that gets harder, a bowstring that snaps, a machine gun's buzz. Changes are felt "
                                   "right away; the bars show where each trigger is. Works in every game, also over "
                                   "Bluetooth."))
        self.connected = _label("")
        self.body.addWidget(self.connected)
        self.charge_only = big_button("", checkable=True)
        self.charge_only.setChecked(dualsense.charge_only(config))
        self._label_charge_only()
        self.charge_only.toggled.connect(self.set_charge_only)
        self.body.addWidget(self.charge_only, alignment=Qt.AlignmentFlag.AlignLeft)
        self.body.addWidget(_label("On a USB cable the controller switches to USB, where its triggers are much weaker. "
                                   "With this on, it stays on Bluetooth and the cable only charges it. Only while "
                                   "Bluetooth is on and the controller is paired - otherwise it works over the cable "
                                   "as usual."))
        lt, rt = dualsense.from_config(config)
        self.boxes = {"lt": TriggerEffectBox("lt", lt, self.changed), "rt": TriggerEffectBox("rt", rt, self.changed)}
        presets = QGridLayout()  # rows of four
        presets.setHorizontalSpacing(10)
        presets.setVerticalSpacing(10)
        self.preset_buttons = {}
        for index, (name, lt_effect, rt_effect) in enumerate(PRESETS):
            button = big_button(name)
            button.clicked.connect(lambda _=False, l=lt_effect, r=rt_effect: self.preset(l, r))
            presets.addWidget(button, index // 4, index % 4)
            self.preset_buttons[name] = button
        self.body.addWidget(_label("Presets"))
        self.body.addLayout(presets)
        self.body.addWidget(self.status)
        for box in self.boxes.values():
            self.body.addWidget(box)
        self.read_timer = QTimer(self)
        self.read_timer.timeout.connect(self.read)
        self.refresh(live=False)  # (the bars only while its page is open - not in the background)

    # the controller ---------------------------------------------------------------------------
    def refresh(self, live: bool = True) -> None:
        """Which PS5 controller is connected - send it what's set, and (live) show its triggers."""
        found = self.find()
        self.connected.setText(", ".join(c.name + (" (Bluetooth)" if c.bus == dualsense.BUS_BLUETOOTH else " (USB)")
                                         for c in found) or "No PS5 controller connected - the settings are kept "
                                                            "for when one is.")
        self.stop()
        if found:
            self._send()
        if found and live:
            try:
                self.reader = self.reader_factory(found[0])
            except OSError:
                self.reader = None  # (no access: _send said so)
            if self.reader is not None:
                self.read_timer.start(30)

    def stop(self) -> None:
        self.read_timer.stop()
        if self.reader is not None:
            self.reader.close()
            self.reader = None
        for box in self.boxes.values():
            box.meter.set_value(0)

    def read(self) -> None:
        try:
            values = self.reader.poll() if self.reader is not None else None
        except OSError:  # switched off
            self.stop()
            return
        if values is not None:
            self.boxes["lt"].meter.set_value(values[0] / 255)
            self.boxes["rt"].meter.set_value(values[1] / 255)

    # the effects --------------------------------------------------------------------------------
    def changed(self) -> None:
        saved = self.config.setdefault("input", {}).setdefault("adaptive_triggers", {})
        for name, box in self.boxes.items():
            saved[name] = box.effect().to_dict()
        self.save_config(self.config)
        self._send()

    def _label_charge_only(self) -> None:
        self.charge_only.setText(("☑" if self.charge_only.isChecked() else "☐")
                                 + "  Charge only over USB - stays on Bluetooth")

    def set_charge_only(self, on: bool) -> None:
        from gamingcrypt.ui.tasks import run_async

        self._label_charge_only()
        self.charge_only.setEnabled(False)

        def done(result) -> None:
            ok, why = result
            self.charge_only.setEnabled(True)
            if not ok:
                self.charge_only.blockSignals(True)
                self.charge_only.setChecked(not on)  # as it was
                self.charge_only.blockSignals(False)
                self._label_charge_only()
                set_status(self.status, why, error=True)
                return
            self.config.setdefault("input", {})["ps5_charge_only"] = on
            self.save_config(self.config)
            set_status(self.status, "A PS5 controller on a cable now only charges - over Bluetooth" if on
                       else "A PS5 controller on a cable uses it again")
            QTimer.singleShot(2500, lambda: self.refresh(live=False))  # (it changes connection meanwhile)

        run_async(lambda: self.set_charge(on), done, lambda exc: done((False, str(exc))), owner=self)

    def _game_running(self) -> bool:
        """A game runs (GamingCrypt's game watcher) - also asked before this page is in the window."""
        from PySide6.QtWidgets import QApplication

        for window in (self.window(), *QApplication.topLevelWidgets()):
            watcher = getattr(window, "game_watcher", None)
            if watcher is not None and getattr(watcher, "active", False):
                return True
        return False

    def _send(self) -> None:
        if self._game_running():  # the triggers are the game's while it runs (app.adaptive_triggers)
            set_status(self.status, "Kept - a game is running, and the triggers are its own until it ends. "
                                    "Then they go to the controller.")
            return
        done, error = self.send(self.config)
        if error:
            set_status(self.status, error, error=True)
        elif done:
            set_status(self.status, "Sent to the controller - pull the trigger to feel it")
        else:
            set_status(self.status, "Kept - it goes to a PS5 controller once one is connected")

    def preset(self, lt: Effect | None, rt: Effect | None) -> None:
        for name, effect in (("lt", lt), ("rt", rt)):
            if effect is not None:
                self.boxes[name].set_effect(effect)
        self.changed()

    # (the old buttons' names, for whoever still calls them)
    def aim_preset(self) -> None:
        self.preset(PRESETS[0][1], None)

    def all_off(self) -> None:
        self.preset(Effect(OFF), Effect(OFF))
