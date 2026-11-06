"""Settings → Storage → Format: a USB stick, USB drive or SD card made new, ready for games.

Two questions, the second one in red: which file system - then really delete everything on it?
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

from gamingcrypt.system import removable
from gamingcrypt.ui.game_widgets import format_size
from gamingcrypt.ui.tasks import run_async
from gamingcrypt.ui.widgets import FlowLayout, big_button

NAMES = {"exfat": "exFAT", "ext4": "ext4"}


class FormatConfirm(QFrame):
    formatted = Signal(str)  # what happened
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, drive, formats: list[str] | None = None, run=None, parent=None):
        super().__init__(parent)
        self.drive, self.run = drive, run
        self.chosen = ""
        self.working = False
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(12)
        size = f", {format_size(drive.size)}" if drive.size else ""
        self.question = QLabel(f"Format {drive.name} ({removable.LABELS[drive.kind]}{size})? "
                               "Choose how - it's ready for games afterwards.")
        self.question.setWordWrap(True)
        layout.addWidget(self.question)
        formats = removable.formats() if formats is None else formats
        self.choices = {}
        for fstype in formats:
            text = QLabel(f"{NAMES[fstype]}: {removable.FORMATS[fstype][0]}")
            text.setObjectName("cardMeta")
            text.setWordWrap(True)
            layout.addWidget(text)
        row = FlowLayout(spacing=12)
        for fstype in formats:
            button = big_button(NAMES[fstype])
            button.clicked.connect(lambda _c=False, f=fstype: self.choose(f))
            row.addWidget(button)
            self.choices[fstype] = button
        self.format_button = big_button("🗑 Delete everything and format", "danger")
        self.format_button.clicked.connect(self.start)
        self.format_button.hide()
        row.addWidget(self.format_button)
        self.cancel_button = big_button("Cancel")
        self.cancel_button.clicked.connect(self.cancel)
        row.addWidget(self.cancel_button)
        layout.addLayout(row)
        if not formats:
            self.question.setText("This device can't format drives: install exfatprogs (for exFAT) or "
                                  "e2fsprogs (for ext4).")

    def focus_first(self) -> None:
        first = next(iter(self.choices.values()), self.cancel_button)
        first.setFocus(Qt.FocusReason.TabFocusReason)

    def choose(self, fstype: str) -> None:
        """The second question: everything on it is gone."""
        self.chosen = fstype
        for button in self.choices.values():
            button.hide()
        self.question.setText(f"Really delete everything on {self.drive.name}? It's formatted as {NAMES[fstype]} "
                              "and can't be undone.")
        self.format_button.show()
        self.cancel_button.setFocus(Qt.FocusReason.TabFocusReason)  # the safe answer first

    def start(self) -> None:
        if self.working or not self.chosen:
            return
        self.working = True
        self.format_button.setEnabled(False)
        self.cancel_button.setEnabled(False)
        self.question.setText(f"Formatting {self.drive.name}… keep it in")
        drive, fstype, run = self.drive, self.chosen, self.run
        label = drive.label or "GAMES"
        run_async(lambda: removable.format_drive(drive, fstype, label, run=run), self._done, self._failed, owner=self)

    def _done(self, now) -> None:
        self.working = False
        self.formatted.emit(f"{now.name} is formatted ({NAMES[self.chosen]}) and ready for games")

    def _failed(self, exc) -> None:
        self.working = False
        why = str(exc) if isinstance(exc, removable.FormatError) else f"{exc}"
        self.failed.emit(f"Could not format {self.drive.name}: {why}")

    def cancel(self) -> None:
        if not self.working:
            self.cancelled.emit()

    def gamepad_back(self) -> bool:
        self.cancel()
        return True
