"""Moving a game onto a USB stick, USB drive or SD card - or back onto the encrypted drive.

Asked over the game's page (⚙ Options → Move) and in Settings → Storage: one button per place it
can go, then how far the copy is. Cancel stops it; nothing is lost either way (moving.py).
"""

from __future__ import annotations

import shutil

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QProgressBar, QVBoxLayout

from gamingcrypt import moving
from gamingcrypt.ui.game_widgets import format_size
from gamingcrypt.ui.tasks import run_async
from gamingcrypt.ui.widgets import FlowLayout, big_button

ICONS = {"usb": "🔌", "drive": "🖴", "sd": "💾"}


def place_text(place: moving.Place) -> str:
    drive = place.removable
    if drive is None:
        return "🔒 To the encrypted drive"
    try:
        free = f" · {format_size(shutil.disk_usage(drive.mount).free)} free"
    except OSError:
        free = ""
    return f"{ICONS.get(drive.kind, '🔌')} To {drive.name}{free}"


class MoveGame(QFrame):
    moved = Signal(str)  # what happened
    failed = Signal(str)  # not moved: why
    cancelled = Signal()

    def __init__(self, game, places: list, emulation=None, parent=None):
        super().__init__(parent)
        self.game, self.emulation = game, emulation
        self.progress = moving.Progress()
        self.moving = False
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)
        where = f"It's on {game_place(game)}."
        self.question = QLabel(f"Move {game.name}? {where}")
        self.question.setWordWrap(True)
        layout.addWidget(self.question)
        self.note = QLabel("Its saves, save states and settings stay on the encrypted drive.")
        self.note.setObjectName("cardMeta")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.hide()
        layout.addWidget(self.bar)
        self.buttons = []
        row = FlowLayout(spacing=12)
        for place in places:
            button = big_button(place_text(place))
            button.clicked.connect(lambda _c=False, p=place: self.start(p))
            row.addWidget(button)
            self.buttons.append(button)
        self.cancel_button = big_button("Cancel")
        self.cancel_button.clicked.connect(self.cancel)
        row.addWidget(self.cancel_button)
        layout.addLayout(row)
        if not places:
            self.question.setText(f"{game.name} can't go anywhere else: put in a USB stick, USB drive or SD card.")
        self.timer = QTimer(self)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self.show_progress)
        game_ref = game
        run_async(lambda: moving.size_of(game_ref), self._measured, lambda _e: None, owner=self)

    def _measured(self, size: int) -> None:
        if not self.moving:
            self.question.setText(f"Move {self.game.name} ({format_size(size)})? It's on {game_place(self.game)}.")

    def focus_first(self) -> None:
        (self.buttons[0] if self.buttons else self.cancel_button).setFocus(Qt.FocusReason.TabFocusReason)

    def gamepad_back(self) -> bool:
        self.cancel()
        return True

    def start(self, place: moving.Place) -> None:
        if self.moving:
            return
        self.moving = True
        for button in self.buttons:
            button.setEnabled(False)
        self.cancel_button.setFocus(Qt.FocusReason.TabFocusReason)
        self.question.setText(f"Moving {self.game.name} to {place.name}…")
        self.bar.show()
        self.timer.start()
        game, emulation, progress = self.game, self.emulation, self.progress
        run_async(lambda: moving.move(game, place, emulation, progress),
                  lambda _where: self._done(f"{game.name} moved to {place.name}"), self._failed, owner=self)

    def show_progress(self) -> None:
        self.bar.setValue(round(self.progress.fraction * 1000))
        if self.progress.total:
            self.note.setText(f"{format_size(self.progress.done)} of {format_size(self.progress.total)} - "
                              "keep it in until it's done")

    def cancel(self) -> None:
        if self.moving:
            self.progress.cancelled.set()  # (the copy stops, what was copied is deleted: _failed)
            self.cancel_button.setEnabled(False)
            return
        self.cancelled.emit()

    def _done(self, message: str) -> None:
        self.timer.stop()
        self.moving = False
        self.moved.emit(message)

    def _failed(self, exc) -> None:
        self.timer.stop()
        self.moving = False
        if self.progress.cancelled.is_set():
            self.cancelled.emit()
            return
        self.failed.emit(str(exc) if isinstance(exc, moving.MoveError) else f"Could not move it: {exc}")


def game_place(game) -> str:
    """"the encrypted drive", "a USB stick" ..."""
    from gamingcrypt.system.removable import LABELS

    kind = getattr(game, "removable", "")
    return f"a {LABELS[kind]}" if kind else "the encrypted drive"


class Movable:
    """⚙ Options → Move on a game's page (RomGamePage, WindowsGamePage): needs self.tab, self.game,
    self.move_button, self.status."""

    move_box: MoveGame | None = None

    def move_places(self) -> list:
        return moving.places(self.game, getattr(self.tab, "drives", []), getattr(self.tab, "emulation", None))

    def drives_changed(self) -> None:
        """A stick put in / taken out: Move is there when the game can go somewhere (the admin's)."""
        self.move_button.setVisible(getattr(self.tab, "can_delete", True) and bool(self.move_places()))

    def ask_move(self) -> None:
        from gamingcrypt.ui.modal import show_modal

        if self.move_box is not None:
            return
        self.move_box = MoveGame(self.game, self.move_places(), getattr(self.tab, "emulation", None))
        self.move_box.cancelled.connect(self.close_move)
        self.move_box.moved.connect(self.game_moved)
        self.move_box.failed.connect(self.move_failed)
        self.move_modal = show_modal(self, self.move_box, self.close_move)
        self.move_box.focus_first()

    def close_move(self) -> None:
        box = self.move_box
        if box is None:
            return
        if box.moving:
            box.cancel()  # (stops the copy - cancelled comes when it has)
            return
        self.move_box = None
        self.move_modal.close_modal()
        self.move_button.setFocus()

    def game_moved(self, message: str) -> None:
        self.close_move()
        self.tab.home.show_notice(message)
        self.tab.back()  # (the page is about where it was)
        self.tab.reload_roms()

    def move_failed(self, message: str) -> None:
        self.close_move()
        from gamingcrypt.ui.widgets import set_status

        set_status(self.status, message, error=True)
        self.status.setVisible(True)
