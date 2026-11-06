"""Settings → Storage → Format: a USB stick, USB drive or SD card made new, ready for games.

Two questions, the second one in red: which file system - then really delete everything on it?
While it's formatted: every step with what's done, what's going on now and what's next, a bar and
the time it's taking. At the end what the stick is now (or what went wrong, at the step it did) -
it stays on screen until OK.
"""

from __future__ import annotations

import shutil
import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QFrame, QLabel, QProgressBar, QVBoxLayout, QWidget

from gamingcrypt.system import removable
from gamingcrypt.ui import theme
from gamingcrypt.ui.game_widgets import format_size
from gamingcrypt.ui.tasks import run_async
from gamingcrypt.ui.widgets import FlowLayout, big_button, set_status

NAMES = {"exfat": "exFAT", "ext4": "ext4"}
MARKS = {"waiting": "○", "now": "◐", "done": "✓", "failed": "✗"}


def elapsed(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 60}:{seconds % 60:02d}"


class FormatConfirm(QFrame):
    formatted = Signal(str)  # it's done (the box stays until OK): what happened
    failed = Signal(str)  # not formatted: why (the box stays until Close)
    cancelled = Signal()
    finished = Signal()  # OK / Close after it ran: the box can go

    def __init__(self, drive, formats: list[str] | None = None, run=None, parent=None, clock=time.monotonic):
        super().__init__(parent)
        self.drive, self.run, self.clock = drive, run, clock
        self.chosen = ""
        self.working = False
        self.over = False  # formatted or failed: only OK / Close is left
        self.reached: list[str] = []  # the steps started (appended in the worker thread, read by the timer)
        self.started_at = 0.0
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        self.title = QLabel(f"Format {drive.name}")
        self.title.setObjectName("section")
        layout.addWidget(self.title)
        size = f", {format_size(drive.size)}" if drive.size else ""
        now = f" · now {drive.fstype}" if drive.fstype else ""
        self.question = QLabel(f"{removable.LABELS[drive.kind]}{size}{now}. How should it be formatted? "
                               "It's ready for games afterwards.")
        self.question.setWordWrap(True)
        layout.addWidget(self.question)
        formats = removable.formats() if formats is None else formats
        self.hints = []
        for fstype in formats:
            hint = QLabel(f"{NAMES[fstype]}: {removable.FORMATS[fstype][0]}")
            hint.setObjectName("cardMeta")
            hint.setWordWrap(True)
            layout.addWidget(hint)
            self.hints.append(hint)
        # while it runs: the steps, the bar, the time
        self.steps = QWidget()
        steps = QVBoxLayout(self.steps)
        steps.setContentsMargins(0, 4, 0, 4)
        steps.setSpacing(6)
        self.step_labels: dict[str, QLabel] = {}
        for key, _text in removable.STEPS:
            label = QLabel()
            steps.addWidget(label)
            self.step_labels[key] = label
        self.steps.hide()
        layout.addWidget(self.steps)
        self.bar = QProgressBar()
        self.bar.setRange(0, len(removable.STEPS))
        self.bar.setTextVisible(False)
        self.bar.hide()
        layout.addWidget(self.bar)
        self.state = QLabel("")
        self.state.setObjectName("status")
        self.state.setWordWrap(True)
        self.state.hide()
        layout.addWidget(self.state)
        row = FlowLayout(spacing=12)
        self.choices = {}
        for fstype in formats:
            button = big_button(NAMES[fstype])
            button.clicked.connect(lambda _c=False, f=fstype: self.choose(f))
            row.addWidget(button)
            self.choices[fstype] = button
        self.format_button = big_button("🗑 Delete everything and format", "danger")
        self.format_button.clicked.connect(self.start)
        self.format_button.hide()
        row.addWidget(self.format_button)
        self.ok_button = big_button("OK", "primary")
        self.ok_button.clicked.connect(self.finished.emit)
        self.ok_button.hide()
        row.addWidget(self.ok_button)
        self.cancel_button = big_button("Cancel")
        self.cancel_button.clicked.connect(self.cancel)
        row.addWidget(self.cancel_button)
        layout.addLayout(row)
        self.timer = QTimer(self)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self.show_steps)
        if not formats:
            self.question.setText("This device can't format drives: install exfatprogs (for exFAT) or "
                                  "e2fsprogs (for ext4).")

    def focus_first(self) -> None:
        first = next(iter(self.choices.values()), self.cancel_button)
        first.setFocus(Qt.FocusReason.TabFocusReason)

    def choose(self, fstype: str) -> None:
        """The second question: everything on it is gone."""
        self.chosen = fstype
        for widget in [*self.choices.values(), *self.hints]:
            widget.hide()
        self.question.setText(f"Really delete everything on {self.drive.name}? It's formatted as {NAMES[fstype]} - "
                              "this can't be undone.")
        self.format_button.show()
        self.cancel_button.setFocus(Qt.FocusReason.TabFocusReason)  # the safe answer first

    def start(self) -> None:
        if self.working or not self.chosen or self.over:
            return
        self.working = True
        self.format_button.hide()
        self.cancel_button.hide()  # (it can't be stopped half way)
        self.title.setText(f"Formatting {self.drive.name} as {NAMES[self.chosen]}")
        self.question.setText("Keep it in until it's done.")
        self.steps.show()
        self.bar.show()
        self.state.show()
        self.started_at = self.clock()
        self.show_steps()
        self.timer.start()
        drive, fstype, run, reached = self.drive, self.chosen, self.run, self.reached
        label = drive.label or "GAMES"
        run_async(lambda: removable.format_drive(drive, fstype, label, run=run, step=reached.append),
                  self._done, self._failed, owner=self)

    def step_text(self, key: str) -> str:
        return dict(removable.STEPS)[key].format(fs=NAMES.get(self.chosen, self.chosen))

    def show_steps(self, failed: bool = False, done: bool = False) -> None:
        """Each step: done, going on now, failed, still to come."""
        reached = list(self.reached)
        current = reached[-1] if reached else ""
        for key, label in self.step_labels.items():
            if done and key in reached:
                state = "done"
            elif key == current:
                state = "failed" if failed else ("done" if done else "now")
            elif key in reached:
                state = "done"
            else:
                state = "waiting"
            color = {"done": theme.SUCCESS, "now": theme.ACCENT, "failed": theme.DANGER}.get(state, theme.TEXT_DIM)
            weight = "600" if state in ("now", "failed") else "400"
            label.setText(f"{MARKS[state]}  {self.step_text(key)}{'…' if state == 'now' else ''}")
            label.setStyleSheet(f"color: {color}; font-weight: {weight};")
            label.setProperty("state", state)
        finished = sum(1 for k in reached if k != current) + (1 if done else 0)
        self.bar.setValue(len(self.step_labels) if done and not failed else finished)
        if self.working:
            now = f"{self.step_text(current)}…" if current else "Starting…"
            set_status(self.state, f"{now}  ·  {elapsed(self.clock() - self.started_at)}")

    def _done(self, now) -> None:
        self.working, self.over = False, True
        self.timer.stop()
        self.show_steps(done=True)
        try:
            usage = shutil.disk_usage(now.mount)
            space = f" · {format_size(usage.free)} free of {format_size(usage.total)}"
        except OSError:
            space = ""
        took = elapsed(self.clock() - self.started_at)
        self.title.setText(f"✓ {now.name} is ready for games")
        self.question.setText(f"{NAMES[self.chosen]}{space}. Took {took}. Put ROMs in Emulation/roms/<system>, "
                              "Windows games in Windows Games, Linux games in Linux Games - or move games onto it.")
        set_status(self.state, "")
        self.state.hide()
        self.ok_button.setText("OK")
        self.ok_button.show()
        self.ok_button.setFocus(Qt.FocusReason.TabFocusReason)
        self.formatted.emit(f"{now.name} is formatted ({NAMES[self.chosen]}) and ready for games")

    def _failed(self, exc) -> None:
        self.working, self.over = False, True
        self.timer.stop()
        self.show_steps(failed=True)
        why = str(exc) if isinstance(exc, removable.FormatError) else f"{exc}"
        self.title.setText(f"✗ {self.drive.name} wasn't formatted")
        current = self.reached[-1] if self.reached else ""
        at = f" while {self.step_text(current)[0].lower()}{self.step_text(current)[1:]}" if current else ""
        self.question.setText(f"It went wrong{at}.")
        set_status(self.state, why, error=True)
        self.ok_button.setText("Close")
        self.ok_button.show()
        self.ok_button.setFocus(Qt.FocusReason.TabFocusReason)
        self.failed.emit(f"Could not format {self.drive.name}: {why}")

    def cancel(self) -> None:
        if self.over:
            self.finished.emit()
        elif not self.working:
            self.cancelled.emit()

    def gamepad_back(self) -> bool:
        self.cancel()
        return True
