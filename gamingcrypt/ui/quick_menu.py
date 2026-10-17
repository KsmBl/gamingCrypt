"""Quick menu on the Windows button: audio devices, volume, brightness, refresh rate,
Bluetooth, force quit - and an emulated game's save states and speed. In gaming mode GamingCrypt comes to the front for it while the game keeps
running behind (gamescope shows one app at a time) and steps aside again when it closes.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QBoxLayout, QComboBox, QFrame, QHBoxLayout, QLabel, QScrollArea, QSizePolicy,
                               QVBoxLayout, QWidget)

from gamingcrypt.system import gamescope_ctl
from gamingcrypt.system.battery import read_battery
from gamingcrypt.system.controls import SystemControls
from gamingcrypt.ui.combo import ComboBox
from gamingcrypt.ui.system_settings import _label, _on_change, _slider
from gamingcrypt.ui.tasks import run_async
from gamingcrypt.ui.widgets import big_button, set_status

REFRESH_RATES = [40, 45, 50, 55, 60]
KEEP_SECONDS = 15


def _combo() -> QComboBox:
    """Long device names ("Family 17h/19h HD Audio Controller Speaker …") must not
    widen the panel past the screen - they get elided, the open list shows them whole."""
    combo = ComboBox()
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(8)
    return combo


PANEL_WIDTH = 940  # wider when the text is larger (QuickMenu.fit)
TAP_ROOM = 120  # left of the panel, always: a tap there closes the menu
CAPTION_WIDTH = 130  # at least - the longest caption sets it for all rows


class QuickMenu(QWidget):
    closed = Signal()
    force_quit = Signal(int)
    lock_now = Signal()
    power_chosen = Signal(int)  # watts: the running game's profile, or Settings without a game
    fps_chosen = Signal(int)
    screenshot = Signal()
    states_requested = Signal(str)  # emulated game: the slots to "save" into / to "load"
    controls_requested = Signal()  # emulated game: its button layout
    bluetooth_requested = Signal()  # pair / connect a controller or headphones, the game keeps running
    speed_chosen = Signal(float)  # emulated game: 0.1 - 10 times as fast
    in_step_chosen = Signal(bool)  # emulated 50 Hz game: at the screen's 60 FPS (a fifth faster)
    disc_chosen = Signal(int)  # emulated game on several discs: change to this one (0-based)
    pad_chosen = Signal(object)  # emulated game: the console's controller to play with (Wii U: Pro / GamePad)

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
        self.captions: list[QLabel] = []
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

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
        self.battery.setWordWrap(True)  # "… to full · Charging" must not widen the column
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
        self.bluetooth_button = big_button("Bluetooth devices")
        self.bluetooth_button.clicked.connect(self._bluetooth)
        self.left_column.addWidget(self.bluetooth_button)
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
        self.pair_rows = [row]  # below each other where they don't fit next to each other (fit)

        # emulated game: save / load state
        row = QWidget()
        row.setObjectName("menuRow")
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        self.save_state_button = big_button("💾  Save state")
        self.save_state_button.clicked.connect(lambda: self._states("save"))
        self.load_state_button = big_button("↺  Load state")
        self.load_state_button.clicked.connect(lambda: self._states("load"))
        self.controls_button = big_button("🕹  Controls")
        self.controls_button.clicked.connect(self._controls)
        line.addWidget(self.save_state_button, 1)
        line.addWidget(self.load_state_button, 1)
        self.box.addWidget(row)
        self.state_row = row
        self.pair_rows.append(row)
        row.hide()
        row = QWidget()  # its own line: three buttons don't fit next to each other
        row.setObjectName("menuRow")
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 0)
        line.addWidget(self.controls_button, 1)
        self.in_step_button = big_button("", checkable=True)
        self.in_step_button.toggled.connect(self._in_step_toggled)
        self.in_step_button.hide()
        line.addWidget(self.in_step_button, 1)
        self.pad_button = big_button("")  # each tap: the next controller
        self.pad_button.clicked.connect(self._next_pad)
        self.pad_button.hide()
        line.addWidget(self.pad_button, 1)
        self.pads: list[tuple[str | None, str]] = []
        self.pad, self.running_pad = None, None
        self.box.addWidget(row)
        self.controls_row = row
        self.pair_rows.append(row)
        row.hide()
        from gamingcrypt.emulation.retroarch import SPEEDS

        self.speed_value = QLabel()
        self.speed = _slider(0, len(SPEEDS) - 1, SPEEDS.index(1.0))
        self.speed.setPageStep(1)
        # chosen here, applied once the menu is closed (the game is paused meanwhile)
        _on_change(self.speed, self._speed_chosen, lambda v: self.speed_value.setText(f"{SPEEDS[v]:g}x"))
        self.running_speed, self.running_in_step, self.with_states = 1.0, False, True  # (the game as it runs)
        self.speed_row = self._row("Speed", self.speed, self.speed_value)
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
        self.lock_button = big_button("🔒  Lock now")
        self.lock_button.clicked.connect(self._lock)
        self.box.addWidget(self.lock_button)
        from gamingcrypt.input import hotkeys

        hint = self.lock_hint = _label("", "cardMeta")
        hint.setWordWrap(True)
        self.set_lock_shortcut(hotkeys.WINDOWS["lock"])  # (the app says which it is on this device)
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
                [self.keep_button, self.revert_button], [self.power], [self.fps], [self.bluetooth_button]]
        right = [[self.back_button], [self.overlay_button, self.screenshot_button],
                 [self.save_state_button, self.load_state_button], [self.controls_button, self.in_step_button, self.pad_button],
                 [self.speed], [self.disc_prev, self.disc_next], [self.quit_button],
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
        cap.setFixedWidth(CAPTION_WIDTH)
        self.captions.append(cap)
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
        # it's only drawn over a game: without one the switch would seem to do nothing
        self.overlay_button.setEnabled(in_game)
        self.overlay_button.setText("Performance overlay" if in_game else "Performance overlay · in games")
        self.screenshot_button.setVisible(in_game)
        self.tools_row.setVisible(overlay is not None or in_game)

    def set_emulated(self, emulated: bool, speed: float | None = None, states: bool = True) -> None:
        """RetroArch game: states (where its core can save them), controls and how fast it runs
        right now (1 = as the console)."""
        self.state_row.setVisible(emulated and states)
        self.controls_row.setVisible(emulated)
        self.speed_row.setVisible(emulated and speed is not None)
        self.with_states = states
        if speed is not None:
            self.show_speed(speed)
            self.running_speed = speed

    def set_in_step(self, offered: bool, on: bool = False) -> None:
        """A 50 Hz game: the box to run it at the screen's 60 FPS - not offered for other games."""
        self.in_step_button.blockSignals(True)
        self.in_step_button.setChecked(on)
        self.in_step_button.blockSignals(False)
        self._in_step_text()
        self.in_step_button.setVisible(offered)
        self.running_in_step = on

    def set_pads(self, pads: list[tuple[str | None, str]], running=None, chosen: tuple | None = None) -> None:
        """The controllers the game can be played with ((key, name), the console's own first) - the
        one it runs with and the one chosen meanwhile ((key,), None: none); hidden when there's only one."""
        self.pads = pads
        self.running_pad = running
        self.pad = chosen[0] if chosen else running
        self._pad_text()
        self.pad_button.setVisible(bool(pads))

    def _pad_name(self, key) -> str:
        return next((name for k, name in self.pads if k == key), "").split(" - ")[0]

    def _pad_text(self) -> None:
        self.pad_button.setText("🎮  " + self._pad_name(self.pad))

    def _next_pad(self) -> None:
        keys = [key for key, _name in self.pads]
        if not keys:
            return
        self.pad = keys[(keys.index(self.pad) + 1) % len(keys)] if self.pad in keys else keys[0]
        self._pad_text()
        self.pad_chosen.emit(self.pad)  # applied once the menu is closed
        self._restart_note()

    def _in_step_text(self) -> None:
        self.in_step_button.setText(("☑" if self.in_step_button.isChecked() else "☐") + "  60 FPS (50 Hz game)")

    def _in_step_toggled(self, on: bool) -> None:
        self._in_step_text()
        self.in_step_chosen.emit(on)  # applied once the menu is closed
        self._restart_note()

    def _speed_chosen(self, index: int) -> None:
        from gamingcrypt.emulation.retroarch import SPEEDS

        self.speed_chosen.emit(SPEEDS[index])  # applied once the menu is closed
        self._restart_note()

    RESTART_NOTE = "When you go back, the game starts again {what} - where you are is kept"
    NEXT_START_NOTE = "{what} from the next start - this game can't be saved while it runs"

    def _restart_note(self) -> None:
        """A new speed, 60 FPS or controller is applied by starting the game again, after the menu
        is closed: said here, while it can still be read - the game going black and back is no surprise."""
        from gamingcrypt.emulation.retroarch import SPEEDS

        speed = SPEEDS[self.speed.value()]
        in_step = self.in_step_button.isChecked() if self.in_step_button.isVisibleTo(self) else self.running_in_step
        rates = []
        if speed != self.running_speed:
            rates.append(f"{speed:g}x")
        if in_step != self.running_in_step:
            rates.append("60 FPS" if in_step else "50 FPS")
        pad = (f"the {self._pad_name(self.pad)}"
               if self.pad_button.isVisibleTo(self) and self.pad != self.running_pad else "")
        if not rates and not pad:
            set_status(self.status, "")
            return
        if self.with_states:
            what = " and ".join(([f"at {' and '.join(rates)}"] if rates else []) + ([f"with {pad}"] if pad else []))
            set_status(self.status, self.RESTART_NOTE.format(what=what))
            return
        what = " and ".join(rates + ([pad] if pad else []))
        set_status(self.status, self.NEXT_START_NOTE.format(what=what[0].upper() + what[1:]))  # (starts the sentence)

    def show_speed(self, speed: float) -> None:
        """The speed the game runs at - nothing is applied."""
        from gamingcrypt.emulation.retroarch import SPEEDS

        self._set_quietly(self.speed, SPEEDS.index(speed) if speed in SPEEDS else SPEEDS.index(1.0))
        self.speed_value.setText(f"{SPEEDS[self.speed.value()]:g}x")

    def set_speed_busy(self, busy: bool, text: str = "") -> None:
        """While the game comes back at a new speed: no other one yet."""
        self.speed.setEnabled(not busy)
        self.in_step_button.setEnabled(not busy)
        self.pad_button.setEnabled(not busy)
        set_status(self.status, text)

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

    def _leave_for_page(self) -> None:
        """Not close_menu: GamingCrypt stays in front for a page of its own over the game."""
        if self.countdown.isActive():
            self.revert_refresh()
        self.battery_timer.stop()
        self.hide()

    def _states(self, mode: str) -> None:
        self._leave_for_page()
        self.states_requested.emit(mode)

    def _controls(self) -> None:
        self._leave_for_page()
        self.controls_requested.emit()

    def _bluetooth(self) -> None:
        self._leave_for_page()
        self.bluetooth_requested.emit()

    def _overlay_toggled(self, on: bool) -> None:
        from gamingcrypt.system import gamescope_ctl

        # remembered; it appears when the game is in front again (not over this menu)
        if not gamescope_ctl.set_overlay_wanted(on):
            set_status(self.status, "Could not switch the overlay", error=True)

    def _screenshot(self) -> None:
        self.close_menu()  # the game has to be on screen for it
        self.screenshot.emit()

    def open_menu(self, appid: int | None = None, game_name: str = "") -> None:
        from gamingcrypt.movies.library import is_movie_appid

        self.appid = appid
        self.movie = is_movie_appid(appid)  # its place is kept: stopping needs no second tap
        self.title.setText(game_name or "Quick menu")
        self.back_button.setText(("▶  Back to the movie" if self.movie else "▶  Back to the game") if appid
                                 else "▶  Back")
        self.quit_button.setVisible(appid is not None)
        self._quit_label()
        self._restart_note()  # (a controller for the next start: still said)
        self._load_values()
        self.update_battery()
        self.battery_timer.start(1000)
        self.setGeometry(self.parentWidget().rect())
        self.fit()
        self.panel.verticalScrollBar().setValue(0)  # always from the top
        self.raise_()
        self.show()
        self.back_button.setFocus()

    def set_lock_shortcut(self, binding, controller=None) -> None:
        """The device buttons that lock (hotkeys.Binding) - set in Settings, they differ per device -
        and a connected controller's, where they're others."""
        text = f"Lock shortcut: {binding.how_to()}"
        if controller is not None and controller != binding:
            text += f" - on a controller: {controller.how_to()}"
        self.lock_hint.setText(text)

    def fit(self) -> None:
        """Everything inside the panel, with every text size (nothing cut off at the right):
        the captions as wide as the longest one, the panel as wide as what's in it (up to the
        screen, less the room to tap next to it) - and the button pairs below each other if
        that still isn't enough."""
        width = max([CAPTION_WIDTH] + [cap.sizeHint().width() for cap in self.captions])
        for cap in self.captions:
            cap.setFixedWidth(width)
        room = self.width() - TAP_ROOM
        card = self.panel.widget()
        edges = 2 * self.panel.frameWidth() + self.panel.verticalScrollBar().sizeHint().width()
        for direction in (QBoxLayout.Direction.LeftToRight, QBoxLayout.Direction.TopToBottom):
            for row in self.pair_rows:
                row.layout().setDirection(direction)
            need = card.minimumSizeHint().width() + edges
            if need <= room:
                break
        self.panel.setFixedWidth(max(min(max(PANEL_WIDTH, need), room), 0))

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
            return
        if kind == "output" and name and self.system.audio:
            # the slider is that output's: its own level (it showed the old one's, and the first
            # touch set the new one to it)
            level = next((d.volume for d in self.system.audio.devices("output") if d.name == name), None)
            if level is not None:
                self._set_quietly(self.volume, min(level, 100))
                self.volume_value.setText(f"{min(level, 100)}%")

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
        if getattr(self, "movie", False) and self.appid is not None:
            set_status(self.status, "Stopping the movie…")
            self.force_quit.emit(self.appid)
            return
        if self.appid is None:
            return
        from gamingcrypt.ui.modal import ask

        name = self.title.text()
        ask(self, f"Force quit {name}?\nWhat wasn't saved in the game is lost.", "✕  Force quit", self._quit_now)

    def _quit_now(self) -> None:
        if self.appid is not None:
            set_status(self.status, "Quitting the game…")
            self.force_quit.emit(self.appid)

    def _quit_label(self) -> None:
        self.quit_button.setText("■  Stop the movie" if getattr(self, "movie", False) else "✕  Force quit")
