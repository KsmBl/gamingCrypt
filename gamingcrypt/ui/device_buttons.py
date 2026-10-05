"""Settings -> Controller -> Device buttons: record the quick menu / lock button."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from gamingcrypt.input import evdev as e
from gamingcrypt.input import hotkeys
from gamingcrypt.input.key_capture import KeyCapture
from gamingcrypt.ui import navigator
from gamingcrypt.ui.widgets import big_button, set_status

CAPTURE_S = 10
# alone they'd stop working in GamingCrypt itself
RESERVED_PAD = {e.BTN_SOUTH: "A", e.BTN_EAST: "B"}


class _Bridge(QObject):
    key = Signal(str, int, int)


class Recorder(QObject):
    """First button pressed, optionally a second one while the first is held; done when
    everything is released again."""

    done = Signal(object)  # Binding or None (timeout)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self.codes: list[int] = []
        self.source = ""
        self.device = ""
        self.held: set[int] = set()

    def feed(self, source: str, code: int, pressed: bool, device: str = "") -> None:
        code = hotkeys.ALIASES.get(code, code)
        if self.source and source != self.source:
            return  # one source per binding
        if pressed:
            if not self.codes:
                self.source, self.device = source, device
            if code not in self.codes and len(self.codes) < 2:
                self.codes.append(code)
            self.held.add(code)
        else:
            self.held.discard(code)
            if self.codes and not self.held:
                self.done.emit(hotkeys.Binding(self.source, tuple(self.codes), self.device))


class DeviceButtonsSection(QFrame):
    changed = Signal()

    def __init__(self, config: dict, save: Callable[[dict], None],
                 capture_factory: Callable = KeyCapture, parent: QWidget | None = None):
        super().__init__(parent)
        self.config, self.save = config, save
        self.capture_factory = capture_factory
        self.setObjectName("card")
        body = QVBoxLayout(self)
        body.setContentsMargins(24, 18, 24, 18)
        heading = QLabel("Device buttons")
        heading.setObjectName("section")
        body.addWidget(heading)
        hint = QLabel("Which button opens the quick menu and which locks right away - not every handheld "
                      "has a Windows key. Hold one button and press another for a combination.")
        hint.setObjectName("cardMeta")
        hint.setWordWrap(True)
        body.addWidget(hint)
        grid = QGridLayout()
        self.labels: dict[str, QLabel] = {}
        self.change_buttons: dict[str, object] = {}
        self.default_buttons: dict[str, object] = {}
        for row, (action, name) in enumerate(hotkeys.ACTIONS.items()):
            grid.addWidget(QLabel(name), row, 0)
            label = QLabel("")
            label.setObjectName("detailMeta")
            grid.addWidget(label, row, 1)
            change = big_button("Change")
            change.clicked.connect(lambda _c=False, a=action: self.record(a))
            reset = big_button("Default")
            reset.clicked.connect(lambda _c=False, a=action: self.reset(a))
            grid.addWidget(change, row, 2)
            grid.addWidget(reset, row, 3)
            self.labels[action], self.change_buttons[action], self.default_buttons[action] = label, change, reset
        grid.setColumnStretch(1, 1)
        body.addLayout(grid)
        self.status = QLabel("")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        body.addWidget(self.status)
        self.recording: str | None = None
        self.recorder: Recorder | None = None
        self.capture = None
        self.bridge = _Bridge(self)
        self.bridge.key.connect(lambda name, code, value: self._feed(hotkeys.KEY, code, value == 1, name))
        self.timeout = QTimer(self)
        self.timeout.setSingleShot(True)
        self.timeout.timeout.connect(self._timed_out)
        self.show_bindings()

    def show_bindings(self) -> None:
        bindings = hotkeys.load(self.config)
        own = self.config.get("input", {}).get("hotkeys", {})
        for action, label in self.labels.items():
            label.setText(bindings[action].describe() + ("" if action in own else "   (default)"))

    # recording ---------------------------------------------------------------------------
    def record(self, action: str) -> None:
        self.stop_recording()
        self.recording = action
        self.recorder = Recorder(self)
        self.recorder.done.connect(self._recorded)
        self.capture = self.capture_factory(self.bridge.key.emit)
        self.capture.start()
        navigator.LISTENERS.append(self._pad_event)
        self.timeout.start(CAPTURE_S * 1000)
        set_status(self.status, f"Press the button for \"{hotkeys.ACTIONS[action]}\" now…")

    def _pad_event(self, ev_type: int, code: int, value: int) -> bool:
        if ev_type == e.EV_KEY and value in (0, 1):
            self._feed(hotkeys.PAD, code, value == 1)
        return True  # while recording, nothing navigates

    def _feed(self, source: str, code: int, pressed: bool, device: str = "") -> None:
        if self.recorder is not None:
            self.recorder.feed(source, code, pressed, device)

    def _recorded(self, binding: hotkeys.Binding) -> None:
        action = self.recording
        self.stop_recording()
        if action is None:
            return
        if binding.source == hotkeys.PAD and len(binding.codes) == 1 and binding.codes[0] in RESERVED_PAD:
            set_status(self.status, f"{RESERVED_PAD[binding.codes[0]]} alone is needed to use GamingCrypt - "
                                    "choose another button or a combination", error=True)
            return
        hotkeys.save(self.config, action, binding)
        self.save(self.config)
        self.show_bindings()
        set_status(self.status, f"{hotkeys.ACTIONS[action]}: {binding.describe()}")
        self.changed.emit()

    def _timed_out(self) -> None:
        self.stop_recording()
        set_status(self.status, "No button pressed - nothing changed")

    def stop_recording(self) -> None:
        self.timeout.stop()
        if self._pad_event in navigator.LISTENERS:
            navigator.LISTENERS.remove(self._pad_event)
        if self.capture is not None:
            self.capture.stop()
            self.capture = None
        self.recorder = None
        self.recording = None

    def reset(self, action: str) -> None:
        hotkeys.save(self.config, action, None)
        self.save(self.config)
        self.show_bindings()
        set_status(self.status, f"{hotkeys.ACTIONS[action]}: back to the default")
        self.changed.emit()

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt API
        self.stop_recording()  # never keep listening behind the user's back
        super().hideEvent(event)
