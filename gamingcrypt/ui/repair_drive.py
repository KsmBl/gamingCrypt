"""Settings → Storage → Repair: a stick mounted read-only because it wasn't ejected safely - its
file system checked and repaired, then it's usable again. Every step on screen, as when formatting."""

from __future__ import annotations

import time

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QHBoxLayout, QFrame, QLabel, QProgressBar, QVBoxLayout, QWidget

from gamingcrypt.system import removable
from gamingcrypt.ui import theme
from gamingcrypt.ui.format_drive import MARKS, elapsed
from gamingcrypt.ui.tasks import run_async
from gamingcrypt.ui.widgets import big_button, set_status


class RepairBox(QFrame):
    repaired = Signal(str)  # what happened (the box stays until OK)
    failed = Signal(str)
    cancelled = Signal()
    finished = Signal()  # OK / Close after it ran

    def __init__(self, drive, run=None, parent=None, clock=time.monotonic):
        super().__init__(parent)
        self.drive, self.run, self.clock = drive, run, clock
        self.working = False
        self.over = False
        self.reached: list[str] = []  # (appended in the worker thread, read by the timer)
        self.started_at = 0.0
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        self.title = QLabel(f"🛠 Repair {drive.name}")
        self.title.setObjectName("cardTitle")  # (as a card's, not a page's heading)
        layout.addWidget(self.title)
        self.question = QLabel("It can only be read: it was taken out without ejecting it, and its file system "
                               "needs a check. Nothing on it is deleted.")
        self.question.setWordWrap(True)
        layout.addWidget(self.question)
        self.steps = QWidget()
        steps = QVBoxLayout(self.steps)
        steps.setContentsMargins(0, 4, 0, 4)
        steps.setSpacing(6)
        self.step_labels: dict[str, QLabel] = {}
        for key, _text in removable.REPAIR_STEPS:
            label = QLabel()
            steps.addWidget(label)
            self.step_labels[key] = label
        self.steps.hide()
        layout.addWidget(self.steps)
        self.bar = QProgressBar()
        self.bar.setRange(0, len(removable.REPAIR_STEPS))
        self.bar.setTextVisible(False)
        self.bar.hide()
        layout.addWidget(self.bar)
        self.state = QLabel("")
        self.state.setObjectName("status")
        self.state.setWordWrap(True)
        self.state.hide()
        layout.addWidget(self.state)
        row = QHBoxLayout()  # (as every question: the buttons on the right, Cancel first)
        row.setSpacing(12)
        row.addStretch()
        self.repair_button = big_button("🛠 Repair", "primary")
        self.repair_button.clicked.connect(self.start)
        row.addWidget(self.repair_button)
        self.ok_button = big_button("OK", "primary")
        self.ok_button.clicked.connect(self.finished.emit)
        self.ok_button.hide()
        row.addWidget(self.ok_button)
        self.cancel_button = big_button("Cancel")
        self.cancel_button.clicked.connect(self.cancel)
        row.insertWidget(1, self.cancel_button)
        layout.addLayout(row)
        self.timer = QTimer(self)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self.show_steps)

    def focus_first(self) -> None:
        self.repair_button.setFocus(Qt.FocusReason.TabFocusReason)

    def start(self) -> None:
        if self.working or self.over:
            return
        self.working = True
        self.repair_button.hide()
        self.cancel_button.hide()  # (half way it can't be stopped)
        self.title.setText(f"Repairing {self.drive.name}")
        self.question.setText("Keep it in until it's done.")
        for widget in (self.steps, self.bar, self.state):
            widget.show()
        self.started_at = self.clock()
        self.show_steps()
        self.timer.start()
        drive, run, reached = self.drive, self.run, self.reached
        run_async(lambda: removable.repair(drive, run=run, step=reached.append), self._done, self._failed, owner=self)

    def show_steps(self, failed: bool = False, done: bool = False) -> None:
        reached = list(self.reached)
        current = reached[-1] if reached else ""
        for key, label in self.step_labels.items():
            if done or (key in reached and key != current):
                state = "done"
            elif key == current:
                state = "failed" if failed else "now"
            else:
                state = "waiting"
            color = {"done": theme.SUCCESS, "now": theme.ACCENT, "failed": theme.DANGER}.get(state, theme.TEXT_DIM)
            label.setText(f"{MARKS[state]}  {dict(removable.REPAIR_STEPS)[key]}{'…' if state == 'now' else ''}")
            label.setStyleSheet(f"color: {color}; font-weight: {'600' if state in ('now', 'failed') else '400'};")
            label.setProperty("state", state)
        self.bar.setValue(len(self.step_labels) if done else sum(1 for k in reached if k != current))
        if self.working:
            now = f"{dict(removable.REPAIR_STEPS)[current]}…" if current else "Starting…"
            set_status(self.state, f"{now}  ·  {elapsed(self.clock() - self.started_at)}")

    def _end(self) -> None:
        self.timer.stop()
        self.working, self.over = False, True
        self.ok_button.show()
        self.ok_button.setFocus(Qt.FocusReason.TabFocusReason)

    def _done(self, now) -> None:
        self.show_steps(done=True)
        self._end()
        self.title.setText(f"✓ {self.drive.name} is repaired")
        self.question.setText(f"It can be written to again. Took {elapsed(self.clock() - self.started_at)}. "
                              "Take it out only when nothing is being copied to it.")
        set_status(self.state, "")
        self.state.hide()
        self.repaired.emit(f"{self.drive.name} is repaired")

    def _failed(self, exc) -> None:
        self.show_steps(failed=True)
        self._end()
        self.ok_button.setText("Close")
        why = str(exc)
        self.title.setText(f"✗ {self.drive.name} wasn't repaired")
        self.question.setText("It's as it was: it can be read, not written to.")
        set_status(self.state, why, error=True)
        self.failed.emit(f"Could not repair {self.drive.name}: {why}")

    def cancel(self) -> None:
        if self.over:
            self.finished.emit()
        elif not self.working:
            self.cancelled.emit()

    def gamepad_back(self) -> bool:
        self.cancel()
        return True
