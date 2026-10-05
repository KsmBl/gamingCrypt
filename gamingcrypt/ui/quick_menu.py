"""Quick menu on the Windows button: audio devices, volume, brightness, refresh rate,
force quit. In gaming mode GamingCrypt comes to the front for it while the game keeps
running behind (gamescope shows one app at a time) and steps aside again when it closes.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel, QScrollArea, QSizePolicy, QVBoxLayout,
                               QWidget)

from gamingcrypt.system import gamescope_ctl
from gamingcrypt.system.battery import read_battery
from gamingcrypt.system.controls import SystemControls
from gamingcrypt.ui.system_settings import _label, _on_change, _slider
from gamingcrypt.ui.tasks import run_async
from gamingcrypt.ui.widgets import big_button, set_status

REFRESH_RATES = [40, 45, 50, 55, 60]
KEEP_SECONDS = 15


def _combo() -> QComboBox:
    """Long device names ("Family 17h/19h HD Audio Controller Speaker …") must not
    widen the panel past the screen - they get elided, the open list shows them whole."""
    combo = QComboBox()
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(8)
    return combo


PANEL_WIDTH = 940


class QuickMenu(QWidget):
    closed = Signal()
    force_quit = Signal(int)
    lock_now = Signal()
    power_chosen = Signal(int)  # watts: the running game's profile, or Settings without a game
    fps_chosen = Signal(int)
    screenshot = Signal()
    emulator_command = Signal(str)  # RetroArch: SAVE_STATE / LOAD_STATE
    controls_requested = Signal()  # emulated game: its button layout
    speed_mode_chosen = Signal(str)  # emulated game: slow / normal / fast, right away
    disc_chosen = Signal(int)  # emulated game on several discs: change to this one (0-based)

    def __init__(self, parent: QWidget, system: SystemControls,
                 refresh_get: Callable[[], int] = gamescope_ctl.dynamic_refresh,
                 refresh_set: Callable[[int], bool] = gamescope_ctl.set_dynamic_refresh,
                 refresh_available: bool = True, battery_reader=read_battery):
        super().__init__(parent)
        self.battery_reader = battery_reader
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
        # Two columns - device settings left, the game right - so everything fits on the screen:
        # no scrolling, and taps always reach the buttons (no flick-scrolling to swallow them).
        scroll = self.panel = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedWidth(PANEL_WIDTH)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        card = QFrame()
        card.setObjectName("card")
        columns = QHBoxLayout(card)
        columns.setContentsMargins(24, 16, 24, 12)
        columns.setSpacing(28)
        self.left_column, self.right_column = QVBoxLayout(), QVBoxLayout()
        for column in (self.left_column, self.right_column):
            column.setSpacing(10)
            columns.addLayout(column, 1)
        scroll.setWidget(card)
        outer.addWidget(scroll)

        self.box = self.right_column
        self.title = QLabel("Quick menu")
        self.title.setObjectName("section")
        self.title.setWordWrap(True)  # long game names must not widen the column
        self.title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.box.addWidget(self.title)
        self.back_button = big_button("▶  Back", "primary")
        self.back_button.clicked.connect(self.close_menu)
        self.box.addWidget(self.back_button)

        self.box = self.left_column
        # battery, refreshed every second while the menu is open
        self.battery = QLabel()
        self.battery.setObjectName("battery")  # green when plugged in, red when low (theme.py)
        self.battery_row = self._row("Battery", self.battery, None)
        self.battery_timer = QTimer(self)
        self.battery_timer.timeout.connect(self.update_battery)

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

        # performance: power limit, FPS limit (the running game's profile), overlay
        self.power_value = QLabel()
        self.power = _slider(5, 28, 15)
        _on_change(self.power, self.power_chosen.emit, lambda v: self.power_value.setText(f"{v} W"))
        self.power_row = self._row("Power limit", self.power, self.power_value)
        self.fps = _combo()
        from gamingcrypt.game_profiles import FPS_CHOICES

        for fps in FPS_CHOICES:
            self.fps.addItem(f"{fps} FPS" if fps else "No limit", fps)
        self.fps.currentIndexChanged.connect(lambda _i: self.fps_chosen.emit(self.fps.currentData() or 0))
        self.fps_row = self._row("FPS limit", self.fps, None)
        self.left_column.addStretch()
        self.box = self.right_column
        row = QWidget()
        row.setObjectName("menuRow")
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        self.overlay_button = big_button("Performance overlay", checkable=True)
        self.overlay_button.toggled.connect(self._overlay_toggled)
        self.screenshot_button = big_button("📷  Screenshot")
        self.screenshot_button.clicked.connect(self._screenshot)
        line.addWidget(self.overlay_button, 1)
        line.addWidget(self.screenshot_button, 1)
        self.box.addWidget(row)
        self.tools_row = row

        # emulated game: save / load state
        row = QWidget()
        row.setObjectName("menuRow")
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        self.save_state_button = big_button("💾  Save state")
        self.save_state_button.clicked.connect(lambda: self._emulator("SAVE_STATE"))
        self.load_state_button = big_button("↺  Load state")
        self.load_state_button.clicked.connect(lambda: self._emulator("LOAD_STATE"))
        self.controls_button = big_button("🕹  Controls")
        self.controls_button.clicked.connect(self._controls)
        line.addWidget(self.save_state_button, 1)
        line.addWidget(self.load_state_button, 1)
        self.box.addWidget(row)
        self.state_row = row
        row.hide()
        row = QWidget()  # its own line: three buttons don't fit next to each other
        row.setObjectName("menuRow")
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        line.addWidget(self.controls_button)
        self.box.addWidget(row)
        self.controls_row = row
        row.hide()
        speed = QWidget()
        speed.setObjectName("menuRow")
        line = QHBoxLayout(speed)
        line.setContentsMargins(0, 0, 0, 0)
        self.speed_buttons: dict[str, QWidget] = {}
        for mode in ("slow", "normal", "fast"):
            button = big_button(mode.capitalize(), checkable=True)
            button.clicked.connect(lambda _c=False, m=mode: self._speed_mode(m))
            line.addWidget(button, 1)
            self.speed_buttons[mode] = button
        self.box.addWidget(speed)  # no caption: the three buttons need the width
        self.speed_row = speed
        self.speed_row.hide()
        discs = QWidget()
        discs.setObjectName("menuRow")
        line = QHBoxLayout(discs)
        line.setContentsMargins(0, 0, 0, 0)
        self.disc_prev = big_button("◀")
        self.disc_prev.clicked.connect(lambda: self._disc(self.disc - 1))
        self.disc_label = QLabel("")
        self.disc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.disc_next = big_button("▶")
        self.disc_next.clicked.connect(lambda: self._disc(self.disc + 1))
        line.addWidget(self.disc_prev)
        line.addWidget(self.disc_label, 1)
        line.addWidget(self.disc_next)
        self.box.addWidget(discs)
        self.disc_row = discs
        self.disc_row.hide()
        self.disc, self.disc_count = 0, 0

        # running game
        self.quit_button = big_button("✕  Force quit", "danger")
        self.quit_button.clicked.connect(self._quit_tapped)
        self.box.addWidget(self.quit_button)
        self._disarm = QTimer(self)
        self._disarm.setSingleShot(True)
        self._disarm.timeout.connect(self._disarm_quit)
        self.lock_button = big_button("🔒  Lock now")
        self.lock_button.clicked.connect(self._lock)
        self.box.addWidget(self.lock_button)
        hint = _label("Lock shortcut: hold the Windows button and press Volume Down", "cardMeta")
        hint.setWordWrap(True)
        self.left_column.addWidget(hint)  # under the settings: the game column is the full one
        self.status = _label("", "status")
        self.box.addWidget(self.status)
        self.box.addStretch()
        self.hide()

    # controller: the grid as it looks ------------------------------------------------------
    navigation_complete = True  # never jump outside the menu

    def _rows(self) -> tuple[list[list[QWidget]], list[list[QWidget]]]:
        """(left column, right column): rows of what can be selected, top to bottom."""
        def usable(row):
            return [w for w in row if w.isVisibleTo(self) and w.isEnabled()]

        left = [[self.output], [self.input], [self.volume], [self.brightness], [self.refresh],
                [self.keep_button, self.revert_button], [self.power], [self.fps]]
        right = [[self.back_button], [self.overlay_button, self.screenshot_button],
                 [self.save_state_button, self.load_state_button], [self.controls_button],
                 list(self.speed_buttons.values()), [self.disc_prev, self.disc_next], [self.quit_button],
                 [self.lock_button]]
        return [r for r in map(usable, left) if r], [r for r in map(usable, right) if r]

    def gamepad_navigate(self, current: QWidget | None, dx: int, dy: int) -> QWidget | None:
        """Up / down: the row above / below in the same column (the button under it);
        left / right: the neighbour in the row, past its end over to the other column."""
        columns = self._rows()
        place = next(((c, r, i) for c, rows in enumerate(columns) for r, row in enumerate(rows)
                      for i, w in enumerate(row) if w is current), None)
        if place is None:
            return self.back_button if self.back_button.isVisibleTo(self) else None
        column, row_index, index = place
        rows = columns[column]
        row = rows[row_index]
        if dy:
            target = row_index + dy
            if not 0 <= target < len(rows):
                return None  # the column's end
            return self._closest_in(rows[target], current)
        target = index + dx
        if 0 <= target < len(row):
            return row[target]
        other = columns[1 - column] if (dx > 0) == (column == 0) else None
        if not other:
            return None
        y = current.mapTo(self, current.rect().center()).y()
        nearest = min(other, key=lambda r: abs(r[0].mapTo(self, r[0].rect().center()).y() - y))
        return nearest[0] if dx > 0 else nearest[-1]

    def _closest_in(self, row: list[QWidget], current: QWidget) -> QWidget:
        x = current.mapTo(self, current.rect().center()).x()
        return min(row, key=lambda w: abs(w.mapTo(self, w.rect().center()).x() - x))

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
    def set_performance(self, limit=None, watts: int | None = None, fps: int = 0, overlay: bool | None = None,
                        in_game: bool = False) -> None:
        """limit: PowerLimit or None (not adjustable); overlay: None = no mangoapp."""
        self.power_row.setVisible(limit is not None)
        if limit is not None:
            self.power.blockSignals(True)
            self.power.setRange(limit.min_w, limit.max_w)
            self.power.setValue(watts or limit.current_w)
            self.power.blockSignals(False)
            self.power_value.setText(f"{self.power.value()} W")
        self.fps_row.setVisible(in_game)
        self.fps.blockSignals(True)
        self.fps.setCurrentIndex(max(0, self.fps.findData(fps)))
        self.fps.blockSignals(False)
        self.overlay_button.setVisible(overlay is not None)
        self.overlay_button.blockSignals(True)
        self.overlay_button.setChecked(bool(overlay))
        self.overlay_button.blockSignals(False)
        self.screenshot_button.setVisible(in_game)
        self.tools_row.setVisible(overlay is not None or in_game)

    def set_emulated(self, emulated: bool, speed: tuple[float, float, str] | None = None) -> None:
        """RetroArch game: states, controls and the speed - (fast rate, slow rate, current mode)."""
        self.state_row.setVisible(emulated)
        self.controls_row.setVisible(emulated)
        self.speed_row.setVisible(emulated and speed is not None)
        if speed is not None:
            fast, slow, mode = speed
            self.speed_buttons["fast"].setText(f"Fast {fast:g}x")
            self.speed_buttons["slow"].setText(f"Slow {slow:g}x")
            self._show_speed_mode(mode)

    def set_discs(self, count: int, current: int = 0) -> None:
        """A game on several discs: which one is in (0-based) - hidden for one disc."""
        self.disc_count = count
        self.disc_row.setVisible(count > 1)
        self._show_disc(current)

    def _show_disc(self, index: int) -> None:
        self.disc = index
        self.disc_label.setText(f"💿  Disc {index + 1} of {self.disc_count}")
        self.disc_prev.setEnabled(index > 0)
        self.disc_next.setEnabled(index < self.disc_count - 1)

    def _disc(self, index: int) -> None:
        if 0 <= index < self.disc_count and index != self.disc:
            self._show_disc(index)
            self.disc_chosen.emit(index)  # right away; the menu stays open

    def _show_speed_mode(self, mode: str) -> None:
        for name, button in self.speed_buttons.items():
            button.setChecked(name == mode)

    def _speed_mode(self, mode: str) -> None:
        self._show_speed_mode(mode)
        self.speed_mode_chosen.emit(mode)  # instant; the menu stays open

    def _emulator(self, command: str) -> None:
        self.close_menu()  # back into the game; RetroArch saves / loads right away
        self.emulator_command.emit(command)

    def _controls(self) -> None:
        if self.countdown.isActive():
            self.revert_refresh()
        self.battery_timer.stop()
        self.hide()  # not close_menu: GamingCrypt stays in front for the controls page
        self.controls_requested.emit()

    def _overlay_toggled(self, on: bool) -> None:
        from gamingcrypt.system import gamescope_ctl

        # remembered; it appears when the game is in front again (not over this menu)
        if not gamescope_ctl.set_overlay_wanted(on):
            set_status(self.status, "Could not switch the overlay", error=True)

    def _screenshot(self) -> None:
        self.close_menu()  # the game has to be on screen for it
        self.screenshot.emit()

    def open_menu(self, appid: int | None = None, game_name: str = "") -> None:
        self.appid = appid
        self.title.setText(game_name or "Quick menu")
        self.back_button.setText("▶  Back to the game" if appid else "▶  Back")
        self.quit_button.setVisible(appid is not None)
        self._disarm_quit()
        set_status(self.status, "")
        self._load_values()
        self.update_battery()
        self.battery_timer.start(1000)
        self.setGeometry(self.parentWidget().rect())
        self.panel.setFixedWidth(min(PANEL_WIDTH, self.width() - 200))  # room to tap next to it
        self.panel.verticalScrollBar().setValue(0)  # always from the top
        self.raise_()
        self.show()
        self.back_button.setFocus()

    def close_menu(self) -> None:
        if self.countdown.isActive():
            self.revert_refresh()  # leaving with an unconfirmed mode = revert
        self.battery_timer.stop()
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

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt API
        self.battery_timer.stop()  # also when hidden directly (game over)
        super().hideEvent(event)

    def update_battery(self) -> None:
        state = self.battery_reader() if self.battery_reader else None
        self.battery_row.setVisible(state is not None)  # no battery: no row
        if state is None:
            return
        self.battery.setText(f"{state.label}  ·  {state.status}")
        self.battery.setProperty("low", state.low)
        self.battery.setProperty("charging", state.plugged)
        self.battery.style().unpolish(self.battery)
        self.battery.style().polish(self.battery)

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

    def _lock(self) -> None:
        self.hide()
        self.lock_now.emit()

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
