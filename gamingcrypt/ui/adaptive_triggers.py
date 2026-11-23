"""Settings → Controller → Adaptive triggers: what a PS5 controller's triggers push back with
(input/dualsense). Each change goes to the controller at once - pull the trigger to feel it."""

from __future__ import annotations

from typing import Callable

from PySide6.QtWidgets import QHBoxLayout, QLabel

from gamingcrypt.input import dualsense
from gamingcrypt.ui.combo import ComboBox
from gamingcrypt.ui.system_settings import Section, _label, _on_change, _slider
from gamingcrypt.ui.widgets import big_button, set_status

NAMES = {"lt": "LT / L2 (aim in most games)", "rt": "RT / R2 (shoot, gas)"}


class TriggerEffectBox(Section):
    """One trigger: its effect, where it starts, how strong."""

    def __init__(self, name: str, effect: dualsense.Effect, changed: Callable[[], None]):
        super().__init__(NAMES[name])
        self.name = name
        self.changed = changed
        self.kind = ComboBox()
        for kind, label, _text in dualsense.EFFECTS:
            self.kind.addItem(label, kind)
        self.kind.setCurrentIndex(max(0, self.kind.findData(effect.kind)))
        self.kind.currentIndexChanged.connect(lambda _i: self._kind_chosen())
        self.row("Effect", self.kind)
        self.about = _label("")
        self.body.addWidget(self.about)
        self.position_value, self.strength_value = QLabel(), QLabel()
        self.position = _slider(10, 90, effect.position)
        self.position.setSingleStep(10)
        self.position.setPageStep(10)
        _on_change(self.position, lambda _v: self.changed(), lambda v: self.position_value.setText(f"{v}%"))
        self.row("Where", self.position, self.position_value)
        self.strength = _slider(1, 8, effect.strength)
        self.strength.setPageStep(1)
        _on_change(self.strength, lambda _v: self.changed(), lambda v: self.strength_value.setText(f"{v} / 8"))
        self.row("Strength", self.strength, self.strength_value)
        self.position_value.setText(f"{self.position.value()}%")
        self.strength_value.setText(f"{self.strength.value()} / 8")
        self._show_kind()

    def effect(self) -> dualsense.Effect:
        return dualsense.Effect(self.kind.currentData(), round(self.position.value() / 10) * 10,
                                self.strength.value())

    def _show_kind(self) -> None:
        kind = self.kind.currentData()
        self.about.setText(next(text for k, _label, text in dualsense.EFFECTS if k == kind))
        on = kind != dualsense.OFF
        for widget in (self.position, self.strength, self.position_value, self.strength_value):
            widget.setEnabled(on)

    def _kind_chosen(self) -> None:
        self._show_kind()
        self.changed()


class AdaptiveTriggersSection(Section):
    """Both triggers, kept in config["input"]["adaptive_triggers"]; sent with ``send``."""

    def __init__(self, config: dict, save: Callable[[dict], None], send=dualsense.apply, find=dualsense.find):
        super().__init__("PS5 controller")
        self.config, self.save_config, self.send, self.find = config, save, send, find
        self.body.addWidget(_label("A PS5 controller's triggers can push back: e.g. a stop halfway down the aim "
                                   "trigger - a light pull aims, a harder one goes past it. Changes are felt "
                                   "right away. Works in every game, also over Bluetooth."))
        self.connected = _label("")
        self.body.addWidget(self.connected)
        lt, rt = dualsense.from_config(config)
        self.boxes = {"lt": TriggerEffectBox("lt", lt, self.changed), "rt": TriggerEffectBox("rt", rt, self.changed)}
        for box in self.boxes.values():
            self.body.addWidget(box)
        row = QHBoxLayout()
        self.aim_button = big_button("Aim stop on LT")
        self.aim_button.clicked.connect(self.aim_preset)
        row.addWidget(self.aim_button)
        self.off_button = big_button("Both off")
        self.off_button.clicked.connect(self.all_off)
        row.addWidget(self.off_button)
        row.addStretch()
        self.body.addLayout(row)
        self.body.addWidget(self.status)
        self.refresh()

    def refresh(self) -> None:
        """Which PS5 controller is connected - and send it what's set."""
        found = self.find()
        self.connected.setText(", ".join(c.name + (" (Bluetooth)" if c.bus == dualsense.BUS_BLUETOOTH else " (USB)")
                                         for c in found) or "No PS5 controller connected - the settings are kept "
                                                            "for when one is.")
        if found:
            self._send()

    def changed(self) -> None:
        saved = self.config.setdefault("input", {}).setdefault("adaptive_triggers", {})
        for name, box in self.boxes.items():
            saved[name] = box.effect().to_dict()
        self.save_config(self.config)
        self._send()

    def _send(self) -> None:
        done, error = self.send(self.config)
        if error:
            set_status(self.status, error, error=True)
        elif done:
            set_status(self.status, "Sent to the controller - pull the trigger to feel it")
        else:
            set_status(self.status, "Kept - it goes to a PS5 controller once one is connected")

    def _set(self, name: str, effect: dualsense.Effect) -> None:
        box = self.boxes[name]
        for widget in (box.kind, box.position, box.strength):
            widget.blockSignals(True)
        box.kind.setCurrentIndex(box.kind.findData(effect.kind))
        box.position.setValue(effect.position)
        box.strength.setValue(effect.strength)
        for widget in (box.kind, box.position, box.strength):
            widget.blockSignals(False)
        box.position_value.setText(f"{effect.position}%")
        box.strength_value.setText(f"{effect.strength} / 8")
        box._show_kind()

    def aim_preset(self) -> None:
        self._set("lt", dualsense.Effect(dualsense.STOP, 50, 6))
        self.changed()

    def all_off(self) -> None:
        for name in self.boxes:
            self._set(name, dualsense.Effect())
        self.changed()
