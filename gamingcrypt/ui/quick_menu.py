"""Quick menu on the Windows button: audio devices, volume, brightness, refresh rate,
force quit. In gaming mode GamingCrypt comes to the front for it while the game keeps
running behind (gamescope shows one app at a time) and steps aside again when it closes.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from gamingcrypt.system import gamescope_ctl
from gamingcrypt.system.controls import SystemControls
from gamingcrypt.ui.system_settings import _label, _on_change, _slider
from gamingcrypt.ui.tasks import run_async
from gamingcrypt.ui.widgets import big_button, enable_touch_scroll, set_status

REFRESH_RATES = [40, 45, 50, 55, 60]
KEEP_SECONDS = 15


def _combo() -> QComboBox:
    """Long device names ("Family 17h/19h HD Audio Controller Speaker …") must not
    widen the panel past the screen - they get elided, the open list shows them whole."""
    combo = QComboBox()
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(8)
    return combo


class QuickMenu(QWidget):
    closed = Signal()
    force_quit = Signal(int)

    def __init__(self, parent: QWidget, system: SystemControls,
                 refresh_get: Callable[[], int] = gamescope_ctl.dynamic_refresh,
                 refresh_set: Callable[[int], bool] = gamescope_ctl.set_dynamic_refresh,
                 refresh_available: bool = True):
        super().__init__(parent)
        self.system = system
        self.refresh_get, self.refresh_set = refresh_get, refresh_set
        self.appid: int | None = None
        self.previous_refresh = 0
        self.remaining = 0
        self._quit_armed = False
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet("QuickMenu { background: rgba(0, 0, 0, 200); }")

        outer = QHBoxLayout(self)
        outer.addStretch()
        scroll = self.panel = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedWidth(560)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        enable_touch_scroll(scroll)
        card = QFrame()
        card.setObjectName("card")
        self.box = QVBoxLayout(card)
        self.box.setContentsMargins(24, 20, 24, 20)
        self.box.setSpacing(12)
        scroll.setWidget(card)
        outer.addWidget(scroll)

        self.title = QLabel("Quick menu")
        self.title.setObjectName("section")
        self.box.addWidget(self.title)
        self.back_button = big_button("▶  Back", "primary")
        self.back_button.clicked.connect(self.close_menu)
        self.box.addWidget(self.back_button)

        # audio
        self.output = _combo()
        self.input = _combo()
        self.output.currentIndexChanged.connect(lambda _i: self._device("output", self.output))
        self.input.currentIndexChanged.connect(lambda _i: self._device("input", self.input))
        self.volume_value = QLabel()
        self.volume = _slider(0, 100, 50)
        _on_change(self.volume, self._volume, lambda v: self.volume_value.setText(f"{v}%"))
        self.brightness_value = QLabel()
        self.brightness = _slider(5, 100, 50)
        _on_change(self.brightness, self._brightness, lambda v: self.brightness_value.setText(f"{v}%"))
        for caption, widget, value in (("Output", self.output, None), ("Input", self.input, None),
                                       ("Volume", self.volume, self.volume_value),
                                       ("Brightness", self.brightness, self.brightness_value)):
            self._row(caption, widget, value)

        # refresh rate (gamescope, at runtime) with keep / revert
        self.refresh = _combo()
        self.refresh.addItem("Default", 0)
        for hz in REFRESH_RATES:
            self.refresh.addItem(f"{hz} Hz", hz)
        self.refresh.currentIndexChanged.connect(self._refresh_chosen)
        self.refresh_row = self._row("Refresh rate", self.refresh, None)
        self.refresh_row.setVisible(refresh_available)
        self.confirm = QFrame()
        confirm = QHBoxLayout(self.confirm)
        confirm.setContentsMargins(0, 0, 0, 0)
        self.confirm_label = _label()
        confirm.addWidget(self.confirm_label, 1)
        self.keep_button = big_button("Keep", "primary")
        self.keep_button.clicked.connect(self.keep_refresh)
        self.revert_button = big_button("Revert")
        self.revert_button.clicked.connect(self.revert_refresh)
        confirm.addWidget(self.keep_button)
        confirm.addWidget(self.revert_button)
        self.confirm.hide()
        self.box.addWidget(self.confirm)
        self.countdown = QTimer(self)
        self.countdown.timeout.connect(self._tick)

        # running game
        self.quit_button = big_button("✕  Force quit", "danger")
        self.quit_button.clicked.connect(self._quit_tapped)
        self.box.addWidget(self.quit_button)
        self._disarm = QTimer(self)
        self._disarm.setSingleShot(True)
        self._disarm.timeout.connect(self._disarm_quit)
        self.status = _label("", "status")
        self.box.addWidget(self.status)
        self.box.addStretch()
        self.hide()

    def _row(self, caption: str, widget: QWidget, value: QLabel | None) -> QWidget:
        row = QWidget()
        row.setObjectName("menuRow")  # transparent on the card (theme.py)
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        cap = QLabel(caption)
        cap.setFixedWidth(130)
        line.addWidget(cap)
        line.addWidget(widget, 1)
        if value is not None:
            value.setFixedWidth(64)
            value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            line.addWidget(value)
        self.box.addWidget(row)
        return row

    # open / close -------------------------------------------------------------------
    def open_menu(self, appid: int | None = None, game_name: str = "") -> None:
        self.appid = appid
        self.title.setText(game_name or "Quick menu")
        self.back_button.setText("▶  Back to the game" if appid else "▶  Back")
        self.quit_button.setVisible(appid is not None)
        self._disarm_quit()
        set_status(self.status, "")
        self._load_values()
        self.setGeometry(self.parentWidget().rect())
        self.raise_()
        self.show()
        self.back_button.setFocus()

    def close_menu(self) -> None:
        if self.countdown.isActive():
            self.revert_refresh()  # leaving with an unconfirmed mode = revert
        self.hide()
        self.closed.emit()

    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt API
        """A tap on the dimmed area next to the panel closes the menu."""
        if not self.panel.geometry().contains(event.position().toPoint()):
            self.close_menu()
            event.accept()
            return
        super().mousePressEvent(event)

    def gamepad_back(self) -> bool:
        if self.isVisible():
            self.close_menu()
            return True
        return False

    def _load_values(self) -> None:
        audio, brightness = self.system.audio, self.system.brightness
        for combo, kind in ((self.output, "output"), (self.input, "input")):
            combo.blockSignals(True)
            combo.clear()
            devices = audio.devices(kind) if audio else []
            for d in devices:
                combo.addItem(d.description, d.name)
                if d.is_default:
                    combo.setCurrentIndex(combo.count() - 1)
                    if kind == "output":
                        self._set_quietly(self.volume, min(d.volume, 100))
                        self.volume_value.setText(f"{min(d.volume, 100)}%")
            combo.setEnabled(bool(devices))
            combo.blockSignals(False)
        level = brightness.get() if brightness else None
        self.brightness.setEnabled(level is not None)
        if level is not None:
            self._set_quietly(self.brightness, level)
            self.brightness_value.setText(f"{level}%")
        self.refresh.blockSignals(True)
        self.refresh.setCurrentIndex(max(0, self.refresh.findData(self.refresh_get())))
        self.refresh.blockSignals(False)

    @staticmethod
    def _set_quietly(slider, value: int) -> None:
        slider.blockSignals(True)
        slider.setValue(value)
        slider.blockSignals(False)

    # actions --------------------------------------------------------------------------
    def _device(self, kind: str, combo: QComboBox) -> None:
        name = combo.currentData()
        if name and self.system.audio and not self.system.audio.set_default(kind, name):
            set_status(self.status, f"Could not switch the {kind}", error=True)

    def _volume(self, percent: int) -> None:
        name = self.output.currentData()
        if name and self.system.audio:
            self.system.audio.set_volume("output", name, percent)

    def _brightness(self, percent: int) -> None:
        if self.system.brightness:
            self.system.brightness.set(percent)

    def _refresh_chosen(self, _index: int) -> None:
        hz = self.refresh.currentData() or 0
        if not self.countdown.isActive():
            self.previous_refresh = self.refresh_get()
        if not self.refresh_set(hz):
            set_status(self.status, "Could not change the refresh rate", error=True)
            return
        self.remaining = KEEP_SECONDS
        self.confirm.show()
        self._tick(start=True)
        self.revert_button.setFocus()

    def _tick(self, start: bool = False) -> None:
        if not start:
            self.remaining -= 1
        if self.remaining <= 0:
            self.revert_refresh()  # black screen? nobody could press Keep
            return
        self.confirm_label.setText(f"Keep this refresh rate? Reverting in {self.remaining} s")
        if start:
            self.countdown.start(1000)

    def keep_refresh(self) -> None:
        self.countdown.stop()
        self.confirm.hide()
        set_status(self.status, f"Refresh rate: {self.refresh.currentText()}")

    def revert_refresh(self) -> None:
        self.countdown.stop()
        self.confirm.hide()
        self.refresh_set(self.previous_refresh)
        self.refresh.blockSignals(True)
        self.refresh.setCurrentIndex(max(0, self.refresh.findData(self.previous_refresh)))
        self.refresh.blockSignals(False)
        set_status(self.status, "Refresh rate reverted")

    def _quit_tapped(self) -> None:
        if not self._quit_armed:
            self._quit_armed = True
            self.quit_button.setText("Tap again to force quit")
            self._disarm.start(4000)
            return
        self._disarm_quit()
        if self.appid is not None:
            set_status(self.status, "Quitting the game…")
            self.force_quit.emit(self.appid)

    def _disarm_quit(self) -> None:
        self._quit_armed = False
        self.quit_button.setText("✕  Force quit")
