"""Emulator controls: a picture of the emulated system's controller. Select one of its
buttons, then press the button on your controller that should be it.

Opened from Settings -> Controller, a system's page and the quick menu (while an
emulated game runs). RetroArch reads the layout when a game starts (see
emulation/layouts). The buttons are swapped, so no console button gets lost.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from gamingcrypt.emulation import layouts
from gamingcrypt.emulation.systems import BY_ID
from gamingcrypt.input import evdev as e
from gamingcrypt.ui import console_pictures as pictures
from gamingcrypt.ui import navigator, theme
from gamingcrypt.ui.controller_test import BUTTONS, TRIGGER_PICK
from gamingcrypt.ui.widgets import FlowLayout, big_button

SCAN_S = 10
CODES = {code: xbox for xbox, _label, code, *_rest in BUTTONS if xbox in layouts.XBOX_RETROPAD}
TRIGGERS = {e.ABS_Z: "lt", e.ABS_RZ: "rt"}
HATS = {(e.ABS_HAT0X, -1): "left", (e.ABS_HAT0X, 1): "right", (e.ABS_HAT0Y, -1): "up", (e.ABS_HAT0Y, 1): "down"}
HINT = "Select a button of the {name} controller, then press the button on your controller that should be it."


def _button_style(color: str | None, w: int, h: int) -> str:
    radius = min(w, h) // 2
    return (f"QPushButton {{ background: {color or '#3a4152'}; color: {theme.TEXT}; border-radius: {radius}px; "
            f"border: 4px solid transparent; padding: 0; font-weight: bold; }}"
            f"QPushButton:focus {{ border: 4px solid {theme.TEXT}; }}"
            f"QPushButton[scanning=\"true\"] {{ border: 4px solid {theme.ACCENT}; background: {theme.ACCENT}; }}")


class ControllerPicture(QWidget):
    """The drawing, with the console's buttons on top (scaled with the widget)."""

    pressed = Signal(str)  # console button

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.pic: pictures.Picture | None = None
        self.buttons: dict[str, QPushButton] = {}
        self.captions: dict[str, QLabel] = {}
        self.setMinimumSize(500, 280)

    def set_system(self, system_id: str, names: list[str]) -> None:
        for widget in [*self.buttons.values(), *self.captions.values()]:
            widget.deleteLater()
        self.buttons, self.captions = {}, {}
        self.pic = pictures.picture(system_id)
        for name in names:
            if name not in self.pic.buttons:
                continue
            button = QPushButton(pictures.button_text(name), self)
            button.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            button.setToolTip(name)
            button.clicked.connect(lambda _c=False, n=name: self.pressed.emit(n))
            caption = QLabel("", self)
            caption.setObjectName("cardMeta")
            caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
            caption.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            self.buttons[name], self.captions[name] = button, caption
            button.show()
            caption.show()
        self._place()
        self.update()

    def _scale(self) -> tuple[float, float, float]:
        scale = min(self.width() / pictures.W, self.height() / pictures.H)
        return scale, (self.width() - pictures.W * scale) / 2, (self.height() - pictures.H * scale) / 2

    def _place(self) -> None:
        if self.pic is None:
            return
        scale, dx, dy = self._scale()
        for name, button in self.buttons.items():
            x, y, kind = self.pic.buttons[name]
            w, h = (int(v * scale) for v in pictures.SIZES[kind])
            button.setGeometry(int(dx + x * scale - w / 2), int(dy + y * scale - h / 2), w, h)
            button.setStyleSheet(_button_style(self.pic.colors.get(name), w, h))
            font = button.font()
            font.setPixelSize(max(12, int(min(h * 0.42, 26 * scale + 6))))
            button.setFont(font)
            caption = self.captions[name]
            caption.setGeometry(int(dx + x * scale - 60), int(dy + y * scale + h / 2), 120, 26)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self._place()

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt API
        if self.pic is None:
            return
        painter = QPainter(self)
        scale, dx, dy = self._scale()
        painter.translate(dx, dy)
        painter.scale(scale, scale)
        pictures.paint(painter, self.pic)
        painter.end()


class ControlsPage(QWidget):
    closed = Signal()

    def __init__(self, store: layouts.Store, system_id: str | None = None, systems: list[str] | None = None,
                 note: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.store = store
        self.scanning: str | None = None  # console button waiting for a press
        self._swallow: int | None = None  # the release of the button just pressed
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 16, 30, 16)
        top = QHBoxLayout()
        self.title = QLabel("Emulator controls")
        self.title.setObjectName("title")
        top.addWidget(self.title, 1)
        self.system_combo = QComboBox()
        for sid in systems or []:
            self.system_combo.addItem(BY_ID[sid].name, sid)
        if system_id and self.system_combo.findData(system_id) < 0:
            self.system_combo.addItem(BY_ID[system_id].name, system_id)
        if system_id:
            self.system_combo.setCurrentIndex(self.system_combo.findData(system_id))
        self.system_combo.setVisible(self.system_combo.count() > 1)
        self.system_combo.currentIndexChanged.connect(lambda _i: self.refresh(rebuild=True))
        top.addWidget(self.system_combo)
        self.reset_button = big_button("Default layout")
        self.reset_button.clicked.connect(self.reset_layout)
        top.addWidget(self.reset_button)
        self.done_button = big_button("Done", "primary")
        self.done_button.clicked.connect(self.close_page)
        top.addWidget(self.done_button)
        layout.addLayout(top)
        self.hint = QLabel("")
        self.hint.setObjectName("cardMeta")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        self.note = QLabel(note)
        self.note.setObjectName("status")
        self.note.setWordWrap(True)
        self.note.setVisible(bool(note))
        layout.addWidget(self.note)

        self.picture = ControllerPicture()
        self.picture.pressed.connect(self.start_scan)
        layout.addWidget(self.picture, 1)

        # while scanning: what to press, and the controller's buttons to tap instead
        self.scan_box = QFrame()
        self.scan_box.setObjectName("card")
        scan = QVBoxLayout(self.scan_box)
        scan.setContentsMargins(20, 12, 20, 12)
        self.scan_label = QLabel("")
        self.scan_label.setObjectName("section")
        scan.addWidget(self.scan_label)
        taps = QWidget()
        self.taps = FlowLayout(taps)
        self.tap_buttons: dict[str, QPushButton] = {}
        for xbox, name in layouts.XBOX_NAMES.items():
            button = big_button(name)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # the controller is scanned, not navigated
            button.clicked.connect(lambda _c=False, x=xbox: self.assign(x))
            self.taps.addWidget(button)
            self.tap_buttons[xbox] = button
        self.cancel_button = big_button("Cancel")
        self.cancel_button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.cancel_button.clicked.connect(self.stop_scan)
        self.taps.addWidget(self.cancel_button)
        scan.addWidget(taps)
        self.scan_box.hide()
        layout.addWidget(self.scan_box)
        self.scan_timer = QTimer(self)
        self.scan_timer.setSingleShot(True)
        self.scan_timer.timeout.connect(self.stop_scan)
        self.refresh(rebuild=True)

    @property
    def system(self) -> str:
        return self.system_combo.currentData() or ""

    @property
    def buttons(self) -> dict[str, QPushButton]:
        return self.picture.buttons

    def refresh(self, rebuild: bool = False) -> None:
        system = self.system
        name = BY_ID[system].name if system in BY_ID else ""
        if rebuild:
            self.stop_scan()
            self.picture.set_system(system, self.store.choices(system))
        self.title.setText(f"Controls · {name}" if name else "Emulator controls")
        self.hint.setText(HINT.format(name=name))
        holders, custom = self.store.holders(system), self.store.get(system)
        for console_name, caption in self.picture.captions.items():
            pressed_by = holders.get(console_name, [])
            caption.setText(" / ".join(layouts.CAPTIONS[x] for x in pressed_by) or "–")
            changed = any(x in custom for x in pressed_by)
            caption.setStyleSheet(f"color: {theme.ACCENT_HI if changed else theme.TEXT_DIM};")
        self.reset_button.setVisible(bool(custom))

    # scanning -----------------------------------------------------------------------------------
    def start_scan(self, name: str) -> None:
        self.stop_scan()
        self.scanning = name
        button = self.buttons[name]
        button.setProperty("scanning", True)
        button.style().unpolish(button)
        button.style().polish(button)
        self.scan_label.setText(f"Press the button for {name} …  (or tap it, {SCAN_S} s)")
        self.scan_box.show()
        self.scan_timer.start(SCAN_S * 1000)

    def stop_scan(self) -> None:
        name, self.scanning = self.scanning, None
        self.scan_timer.stop()
        self.scan_box.hide()
        button = self.buttons.get(name) if name else None
        if button is not None:
            button.setProperty("scanning", False)
            button.style().unpolish(button)
            button.style().polish(button)
            button.setFocus()

    def assign(self, xbox: str) -> None:
        name = self.scanning
        if name is None:
            return
        self.store.assign(self.system, name, xbox)
        self.stop_scan()
        self.refresh()

    def on_event(self, ev_type: int, code: int, value: int) -> bool:
        if self.scanning is None:
            if ev_type == e.EV_KEY and code == self._swallow and value == 0:
                self._swallow = None
                return True  # its release must not select the button again
            return False
        if ev_type == e.EV_KEY and value == 1 and code in CODES:
            self._swallow = code
            self.assign(CODES[code])
        elif ev_type == e.EV_ABS and code in TRIGGERS and value >= TRIGGER_PICK:
            self.assign(TRIGGERS[code])
        elif ev_type == e.EV_ABS and (code, value) in HATS:
            self.assign(HATS[(code, value)])
        return True  # nothing navigates while waiting for the button

    # page ---------------------------------------------------------------------------------------
    def reset_layout(self) -> None:
        self.stop_scan()
        self.store.reset(self.system)
        self.refresh()

    def close_page(self) -> None:
        self.stop_scan()
        self.closed.emit()

    def gamepad_back(self) -> bool:
        if self.scanning is None:
            self.close_page()
        return True

    def showEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().showEvent(event)
        if self.on_event not in navigator.LISTENERS:
            navigator.LISTENERS.append(self.on_event)
        first = next(iter(self.buttons.values()), None)
        if first is not None:
            first.setFocus(Qt.FocusReason.OtherFocusReason)

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt API
        self.stop_scan()
        if self.on_event in navigator.LISTENERS:
            navigator.LISTENERS.remove(self.on_event)
        super().hideEvent(event)
