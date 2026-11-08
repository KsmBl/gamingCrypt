"""Moving a game onto a USB stick, USB drive or SD card - or back onto the encrypted drive.

Asked over the whole screen (⚙ Options → Move on the game's page, Settings → Storage): one button per
place it can go. While it moves: every step with what's done, what's going on now and what's next,
the bar, how much is copied, how fast, how long it still takes and the file it's on. At the end where
the game is now (or what went wrong, at the step it did) - it stays on screen until OK. Cancel stops
it; nothing is lost either way (moving.py).
"""

from __future__ import annotations

import shutil
import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QLabel, QProgressBar, QVBoxLayout, QWidget

from gamingcrypt import moving
from gamingcrypt.ui import theme
from gamingcrypt.ui.game_widgets import format_size
from gamingcrypt.ui.tasks import run_async
from gamingcrypt.ui.widgets import FlowLayout, big_button, set_status

ICONS = {"usb": "🔌", "drive": "🖴", "sd": "💾"}
MARKS = {"waiting": "○", "now": "◐", "done": "✓", "failed": "✗"}


def place_text(place: moving.Place) -> str:
    drive = place.removable
    if drive is None:
        return "🔒 To the encrypted drive"
    try:
        free = f" · {format_size(shutil.disk_usage(drive.mount).free)} free"
    except OSError:
        free = ""
    return f"{ICONS.get(drive.kind, '🔌')} To {drive.name}{free}"


def clock_text(seconds: float) -> str:
    seconds = max(0, int(seconds))
    if seconds >= 3600:
        return f"{seconds // 3600}:{seconds % 3600 // 60:02d}:{seconds % 60:02d}"
    return f"{seconds // 60}:{seconds % 60:02d}"


class MoveGame(QFrame):
    moved = Signal(str)  # it's moved (the box stays until OK): what happened
    failed = Signal(str)  # not moved: why (the box stays until Close)
    cancelled = Signal()  # closed before it started, or stopped half way
    finished = Signal()  # OK / Close after it ran: the box can go

    def __init__(self, game, places: list, emulation=None, parent=None, clock=time.monotonic):
        super().__init__(parent)
        self.game, self.emulation, self.clock = game, emulation, clock
        self.progress = moving.Progress()
        self.moving = False
        self.over = False  # moved or failed: only OK / Close is left
        self.place: moving.Place | None = None
        self.started_at = 0.0
        self.speed_from: tuple[float, int] = (0.0, 0)  # (when, bytes) a moment ago: how fast it copies
        self.speed = 0.0
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        self.title = QLabel(f"Move {game.name}")
        self.title.setObjectName("section")
        self.title.setWordWrap(True)
        layout.addWidget(self.title)
        self.question = QLabel(f"It's on {game_place(game)}. Where should it go?")
        self.question.setWordWrap(True)
        layout.addWidget(self.question)
        self.note = QLabel("Its saves, save states and settings stay on the encrypted drive.")
        self.note.setObjectName("cardMeta")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        # while it moves: the steps, the bar, the numbers
        self.steps = QWidget()
        steps = QVBoxLayout(self.steps)
        steps.setContentsMargins(0, 4, 0, 4)
        steps.setSpacing(6)
        self.step_labels: dict[str, QLabel] = {}
        for key, _text in moving.STAGES:
            label = QLabel()
            steps.addWidget(label)
            self.step_labels[key] = label
        self.steps.hide()
        layout.addWidget(self.steps)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.hide()
        layout.addWidget(self.bar)
        self.numbers = QLabel("")  # 1.2 GB of 3.4 GB · 35% · 42 MB/s · about 0:53 left
        self.numbers.setWordWrap(True)
        self.numbers.hide()
        layout.addWidget(self.numbers)
        self.state = QLabel("")  # the file it's on / what went wrong
        self.state.setObjectName("status")
        self.state.setWordWrap(True)
        self.state.hide()
        layout.addWidget(self.state)
        self.buttons = []
        row = FlowLayout(spacing=12)
        for place in places:
            button = big_button(place_text(place))
            button.clicked.connect(lambda _c=False, p=place: self.start(p))
            row.addWidget(button)
            self.buttons.append(button)
        self.ok_button = big_button("OK", "primary")
        self.ok_button.clicked.connect(self.finished.emit)
        self.ok_button.hide()
        row.addWidget(self.ok_button)
        self.cancel_button = big_button("Cancel")
        self.cancel_button.clicked.connect(self.cancel)
        row.addWidget(self.cancel_button)
        layout.addLayout(row)
        if not places:
            self.question.setText("It can't go anywhere else: put in a USB stick, USB drive or SD card.")
        self.timer = QTimer(self)
        self.timer.setInterval(250)
        self.timer.timeout.connect(self.show_progress)
        run_async(lambda g=game: moving.size_of(g), self._measured, lambda _e: None, owner=self)

    def _measured(self, size: int) -> None:
        if not self.moving and not self.over:
            self.question.setText(f"{format_size(size)}, on {game_place(self.game)}. Where should it go?")

    def focus_first(self) -> None:
        (self.buttons[0] if self.buttons else self.cancel_button).setFocus(Qt.FocusReason.TabFocusReason)

    def gamepad_back(self) -> bool:
        self.cancel()
        return True

    # moving ---------------------------------------------------------------------------------
    def start(self, place: moving.Place) -> None:
        if self.moving or self.over:
            return
        self.moving, self.place = True, place
        for button in self.buttons:
            button.hide()
        self.cancel_button.setText("Stop")
        self.cancel_button.setFocus(Qt.FocusReason.TabFocusReason)
        self.title.setText(f"Moving {self.game.name} to {place.name}")
        self.question.setText("Keep it in until it's done.")
        self.note.hide()
        for widget in (self.steps, self.bar, self.numbers, self.state):
            widget.show()
        self.started_at = self.clock()
        self.speed_from = (self.started_at, 0)
        self.show_progress()
        self.timer.start()
        game, emulation, progress = self.game, self.emulation, self.progress
        run_async(lambda: moving.move(game, place, emulation, progress), self._done, self._failed, owner=self)

    def step_text(self, key: str) -> str:
        source = "the stick" if getattr(self.game, "removable", "") else "the encrypted drive"
        to = self.place.name if self.place is not None else ""
        return dict(moving.STAGES)[key].format(to=to, source=source)

    def show_steps(self, failed: bool = False, done: bool = False) -> None:
        order = [key for key, _t in moving.STAGES]
        current = self.progress.stage
        at = order.index(current) if current in order else -1
        for i, (key, label) in enumerate(self.step_labels.items()):
            if done or i < at:
                state = "done"
            elif i == at:
                state = "failed" if failed else "now"
            else:
                state = "waiting"
            color = {"done": theme.SUCCESS, "now": theme.ACCENT, "failed": theme.DANGER}.get(state, theme.TEXT_DIM)
            weight = "600" if state in ("now", "failed") else "400"
            text = self.step_text(key)
            if key == "copy" and state == "now" and self.progress.files > 1:
                text += f" - file {min(self.progress.copied + 1, self.progress.files)} of {self.progress.files}"
            label.setText(f"{MARKS[state]}  {text}{'…' if state == 'now' else ''}")
            label.setStyleSheet(f"color: {color}; font-weight: {weight};")
            label.setProperty("state", state)

    def show_progress(self) -> None:
        p = self.progress
        self.show_steps()
        self.bar.setValue(round(p.fraction * 1000))
        now = self.clock()
        then, copied = self.speed_from
        if now - then >= 1.0:  # (over a second: steady, not jumping with each chunk)
            fresh = (p.done - copied) / (now - then)
            self.speed = fresh if not self.speed else 0.6 * self.speed + 0.4 * fresh
            self.speed_from = (now, p.done)
        parts = [f"{format_size(p.done)} of {format_size(p.total)}" if p.total else "Measuring…"]
        if p.total:
            parts.append(f"{round(p.fraction * 100)}%")
        if self.speed > 0:
            parts.append(f"{format_size(int(self.speed))}/s")
            if p.total > p.done and p.stage == "copy":
                parts.append(f"about {clock_text((p.total - p.done) / self.speed)} left")
        parts.append(f"{clock_text(now - self.started_at)} so far")
        self.numbers.setText("  ·  ".join(parts))
        set_status(self.state, f"Copying {p.current}" if p.stage == "copy" and p.current else "")

    def cancel(self) -> None:
        if self.over:
            self.finished.emit()
        elif self.moving:
            self.progress.cancelled.set()  # (the copy stops, what was copied is deleted: _failed)
            self.cancel_button.setEnabled(False)
            self.cancel_button.setText("Stopping…")
        else:
            self.cancelled.emit()

    def _end(self) -> None:
        self.timer.stop()
        self.moving, self.over = False, True
        self.cancel_button.hide()
        self.numbers.setText(f"Took {clock_text(self.clock() - self.started_at)}")
        self.ok_button.show()
        self.ok_button.setFocus(Qt.FocusReason.TabFocusReason)

    def _done(self, where) -> None:
        self.bar.setValue(1000)
        self.show_steps(done=True)
        self._end()
        name = self.place.name
        self.title.setText(f"✓ {self.game.name} is on {name} now")
        self.question.setText(f"In {where}. It's in the game list as before - with its favorite, play time and "
                              "saves.")
        set_status(self.state, "")
        self.state.hide()
        self.ok_button.setText("OK")
        self.moved.emit(f"{self.game.name} moved to {name}")

    def _failed(self, exc) -> None:
        stopped = self.progress.cancelled.is_set()
        self.show_steps(failed=not stopped)
        self._end()
        self.ok_button.setText("Close")
        if stopped:
            self.title.setText(f"{self.game.name} wasn't moved")
            self.question.setText(f"Stopped. What was copied is deleted again - it's on {game_place(self.game)} "
                                  "as before.")
            set_status(self.state, "")
            self.state.hide()
            self.cancelled.emit()
            return
        why = str(exc) if isinstance(exc, moving.MoveError) else f"Could not move it: {exc}"
        self.title.setText(f"✗ {self.game.name} wasn't moved")
        stage = self.progress.stage
        at = f" while {self.step_text(stage)[0].lower()}{self.step_text(stage)[1:]}" if stage else ""
        self.question.setText(f"It went wrong{at}.")
        set_status(self.state, why, error=True)
        self.state.show()
        self.failed.emit(why)


def put_in_text(game) -> str:
    """"put GAMES in again" - or its kind, when its name isn't known."""
    if getattr(game, "away", ""):
        return f"put {game.away} in again"
    kind = getattr(game, "removable", "")
    return f"put its {dict(usb='USB stick', drive='USB drive', sd='SD card').get(kind, 'USB stick')} in again"


def faded(card) -> None:
    """A remembered game whose stick isn't in: its card greyed out, and where it is."""
    from PySide6.QtWidgets import QGraphicsOpacityEffect

    effect = QGraphicsOpacityEffect(card.cover)
    effect.setOpacity(0.35)
    card.cover.setGraphicsEffect(effect)
    card.meta.setText(f"On {card.game.away} · not in")
    card.setProperty("away", True)


def game_place(game) -> str:
    """"the encrypted drive", "a USB stick" ..."""
    from gamingcrypt.system.removable import LABELS

    kind = getattr(game, "removable", "")
    return f"a {LABELS[kind]}" if kind else "the encrypted drive"


def over_everything(widget: QWidget, content: QWidget, close):
    """The box in the middle of the window - not of a page that's taller than the screen (Settings
    → Storage scrolls), where it was below the screen's edge and only the dimming showed."""
    from gamingcrypt.ui.modal import show_modal

    return show_modal(widget.window() or widget, content, close)


class Movable:
    """⚙ Options → Move on a game's page (RomGamePage, WindowsGamePage): needs self.tab, self.game,
    self.move_button, self.status."""

    move_box: MoveGame | None = None
    move_worked = False

    def move_places(self) -> list:
        return moving.places(self.game, getattr(self.tab, "drives", []), getattr(self.tab, "emulation", None))

    def drives_changed(self) -> None:
        """A stick put in / taken out: Move is there when the game can go somewhere (the admin's)."""
        if getattr(self.game, "away", "") or self.gone:
            self.move_button.hide()
            return
        self.move_button.setVisible(getattr(self.tab, "can_delete", True) and bool(self.move_places()))

    gone = False  # its stick was taken out (game_found)

    def game_found(self, game) -> None:
        """The libraries were looked at again (GamesTab.refresh_game_pages): the game as it is now -
        None: not there (its stick taken out). Play waits until it's back."""
        if self.move_box is not None and self.move_box.moving:
            return  # (it's being moved: the page follows when it's done)
        if game is None or getattr(game, "away", ""):  # (away: remembered - its stick isn't in)
            if game is not None:
                self.game = game
            if not self.gone:
                self.gone = True
                self.main_button.setEnabled(False)
                self.move_button.hide()
                set_status(self.status, f"Not here at the moment - {put_in_text(self.game)} to play it", error=True)
                self.status.setVisible(True)
            return
        if self.gone:
            self.gone = False
            self.main_button.setEnabled(True)
            set_status(self.status, "")
        self.game = game
        self.cover.set_badge(getattr(game, "removable", ""))
        self.drives_changed()

    def ask_move(self) -> None:
        if self.move_box is not None:
            return
        self.move_worked = False
        self.move_box = MoveGame(self.game, self.move_places(), getattr(self.tab, "emulation", None))
        self.move_box.cancelled.connect(self._move_cancelled)
        self.move_box.moved.connect(self.game_moved)
        self.move_box.failed.connect(self.move_failed)
        self.move_box.finished.connect(self.close_move)
        self.move_modal = over_everything(self, self.move_box, self.close_move)
        self.move_box.focus_first()

    def _move_cancelled(self) -> None:
        if self.move_box is not None and not self.move_box.over:
            self.close_move()  # (closed before it began; stopped half way: it says so until Close)

    def close_move(self) -> None:
        box = self.move_box
        if box is None or box.moving:
            return  # (a tap beside it doesn't stop a copy: Stop does)
        self.move_box = None
        self.move_modal.close_modal()
        if self.move_worked:
            self.tab.back()  # (the page is about where it was)
        else:
            self.move_button.setFocus()

    def game_moved(self, message: str) -> None:
        self.move_worked = True
        self.tab.home.show_notice(message)
        self.tab.reload_roms()

    def move_failed(self, message: str) -> None:
        set_status(self.status, message, error=True)
        self.status.setVisible(True)
