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
from PySide6.QtWidgets import QHBoxLayout, QFrame, QLabel, QProgressBar, QVBoxLayout, QWidget

from gamingcrypt.system import removable
from gamingcrypt.ui import theme
from gamingcrypt.ui.game_widgets import format_size
from gamingcrypt.ui.tasks import run_async
from gamingcrypt.ui.widgets import FlowLayout, big_button, set_status

NAMES = {"exfat": "exFAT", "ext4": "ext4"}
SHARES = ((1.0, "All of it"), (0.75, "¾"), (0.5, "½"), (0.25, "¼"))  # how much of it is encrypted
MARKS = {"waiting": "○", "now": "◐", "done": "✓", "failed": "✗"}


def elapsed(seconds: float) -> str:
    seconds = int(seconds)
    return f"{seconds // 60}:{seconds % 60:02d}"


class FormatConfirm(QFrame):
    formatted = Signal(str)  # it's done (the box stays until OK): what happened
    failed = Signal(str)  # not formatted: why (the box stays until Close)
    cancelled = Signal()
    finished = Signal()  # OK / Close after it ran: the box can go

    def __init__(self, drive, formats: list[str] | None = None, run=None, parent=None, clock=time.monotonic,
                 encrypt=None, no_encrypt_reason: str = "", check_code=None, method: str = "password"):
        """encrypt(stick, password, progress) -> the stick opened (stick_crypt.create) - None: it can't be
        encrypted (no_encrypt_reason says why). check_code(code) -> the drive's password, None when it's
        the wrong code: encrypting asks for the code of whoever is logged in first (method: its kind)."""
        super().__init__(parent)
        self.drive, self.run, self.clock = drive, run, clock
        self.encrypt = encrypt if check_code is not None else None
        self.check_code, self.method = check_code, method
        self.password: str | None = None  # (encrypting: from the code, once it's entered)
        self.code = None  # the code's input, while it's asked for
        self.percent = 0.0  # how far the container is (written in the worker thread)
        self.chosen = ""
        self.name = removable.clean_label(drive.label) if drive.label else "GAMES"  # what it's called afterwards
        self.share = 1.0  # encrypted: how much of it (the rest stays a normal drive)
        self.details = None  # the step with its name and how much is encrypted
        self.working = False
        self.over = False  # formatted or failed: only OK / Close is left
        self.reached: list[str] = []  # the steps started (appended in the worker thread, read by the timer)
        self.started_at = 0.0
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        self.title = QLabel(f"Format {drive.name}")
        self.title.setObjectName("cardTitle")  # (as a card's, not a page's heading)
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
        # encrypted: a VeraCrypt container with the drive's code (on unless it can't be)
        self.encrypt_button = big_button("", checkable=True)
        self.encrypt_button.setChecked(self.encrypt is not None)
        self.encrypt_button.setEnabled(self.encrypt is not None)
        self.encrypt_button.toggled.connect(self._encrypt_text)
        layout.addWidget(self.encrypt_button, alignment=Qt.AlignmentFlag.AlignLeft)
        self.encrypt_note = QLabel("Its games are in a VeraCrypt container that opens with the same code as your "
                                   "drive (PIN, password or pattern) - only while GamingCrypt is unlocked. Inside it's ext4: "
                                   "Linux games start from it with either file system. You're asked for your code."
                                   if self.encrypt is not None else no_encrypt_reason or "It can't be encrypted now.")
        self.encrypt_note.setObjectName("cardMeta")
        self.encrypt_note.setWordWrap(True)
        layout.addWidget(self.encrypt_note)
        self._encrypt_text()
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
        row = QHBoxLayout()  # (as every question: the buttons on the right, Cancel first)
        row.setSpacing(12)
        row.addStretch()
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
        row.insertWidget(1, self.cancel_button)
        layout.addLayout(row)
        self.timer = QTimer(self)
        self.timer.setInterval(200)
        self.timer.timeout.connect(self.show_steps)
        if not formats:
            self.question.setText("This device can't format drives: install exfatprogs (for exFAT) or "
                                  "e2fsprogs (for ext4).")

    @property
    def encrypting(self) -> bool:
        return self.encrypt is not None and self.encrypt_button.isChecked()

    def _encrypt_text(self, _on: bool = False) -> None:
        self.encrypt_button.setText("🔒 Encrypted: on" if self.encrypting else "🔓 Encrypted: off")

    def focus_first(self) -> None:
        first = next(iter(self.choices.values()), self.cancel_button)
        first.setFocus(Qt.FocusReason.TabFocusReason)

    def choose(self, fstype: str) -> None:
        """Its name, and how much is encrypted (ask_details) - then, encrypted, the code (ask_code) - then
        the last question: everything on it is gone."""
        self.chosen = fstype
        for widget in [*self.choices.values(), *self.hints, self.encrypt_button, self.encrypt_note]:
            widget.hide()
        self.ask_details()

    def ask_details(self) -> None:
        """A step of its own (a 600 px high screen hasn't room for it all on the first one)."""
        from PySide6.QtWidgets import QHBoxLayout, QLineEdit

        self.title.setText(f"Format {self.drive.name}")
        self.question.setText("What should it be called?" + (" And how much of it should be encrypted?"
                                                              if self.encrypting else ""))
        self.details = QWidget()
        box = QVBoxLayout(self.details)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(10)
        line = QHBoxLayout()
        self.name_field = QLineEdit(self.name)
        self.name_field.setMaxLength(11)  # (what every file system takes)
        self.name_field.setPlaceholderText("GAMES")
        line.addWidget(self.name_field, 1)
        self.keyboard_button = big_button("⌨")
        self.keyboard_button.clicked.connect(self.open_keyboard)
        line.addWidget(self.keyboard_button)
        box.addLayout(line)
        self.name_field.installEventFilter(self)  # (a tap on it: the keyboard, as on any text field)
        self.share_buttons = {}
        if self.encrypting:
            note = QLabel("Encrypted - the rest stays a normal drive, for anything else:")
            note.setObjectName("cardMeta")
            note.setWordWrap(True)
            box.addWidget(note)
            shares = FlowLayout(spacing=10)
            for share, text in SHARES:
                button = big_button(text, choice=True)
                button.setChecked(share == self.share)
                button.clicked.connect(lambda _c=False, v=share: self.choose_share(v))
                shares.addWidget(button)
                self.share_buttons[share] = button
            box.addLayout(shares)
        self.next_button = big_button("Continue ›", "primary")
        self.next_button.clicked.connect(self.details_done)
        box.addWidget(self.next_button, alignment=Qt.AlignmentFlag.AlignRight)
        self.layout().insertWidget(self.layout().indexOf(self.question) + 1, self.details)
        self.next_button.setFocus(Qt.FocusReason.TabFocusReason)

    def open_keyboard(self) -> None:
        """The app's on-screen keyboard (keyboard_overlay - as for every text field) for the name."""
        from gamingcrypt.ui.keyboard_overlay import KeyboardOverlay

        window = self.window()
        overlay = getattr(window, "keyboard_overlay", None)
        if overlay is None:
            overlay = window.keyboard_overlay = KeyboardOverlay(window)
        overlay.open_for(self.name_field)
        self.keyboard = overlay

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt API
        from PySide6.QtCore import QEvent

        if watched is getattr(self, "name_field", None) and event.type() == QEvent.Type.MouseButtonRelease:
            self.open_keyboard()
        return super().eventFilter(watched, event)

    def choose_share(self, share: float) -> None:
        self.share = share
        for value, button in self.share_buttons.items():
            button.setChecked(value == share)

    def details_done(self) -> None:
        self.name = removable.clean_label(self.name_field.text())
        if self.details is not None:
            self.details.hide()
            self.details.deleteLater()
            self.details = None
        if self.encrypting and self.password is None:
            self.ask_code()
            return
        self.confirm()

    def ask_code(self) -> None:
        """Encrypting it with your code: entered again - the whole screen, as on the lock screen - and
        checked; the container gets the drive's password. Cancel: not formatted."""
        from gamingcrypt.ui.code_prompt import ask_code

        screen = ask_code(self, f"🔒 Encrypt {self.drive.name}", "It's encrypted with your code - the one that "
                          "unlocks GamingCrypt.", self.method, self.check_code, self._code_entered,
                          self._code_cancelled)
        self.code = screen.entry

    def _code_cancelled(self) -> None:
        self.code = None
        self.cancelled.emit()

    def _code_entered(self, password: str) -> None:
        self.password = password
        self.code = None
        self.title.setText(f"Format {self.drive.name}")
        self.confirm()

    def confirm(self) -> None:
        """The last question: everything on it is gone."""
        fstype = self.chosen
        share = dict(SHARES).get(self.share, "") if self.share < 1.0 else ""
        how = (f"{NAMES[fstype]}, encrypted" + (f" ({share} of it)" if share else "")) if self.encrypting \
            else NAMES[fstype]
        self.question.setText(f"Really delete everything on {self.drive.name}? It's formatted as {how} and called "
                              f"{self.name} - this can't be undone.")
        self.format_button.show()
        self.cancel_button.setFocus(Qt.FocusReason.TabFocusReason)  # the safe answer first

    def start(self) -> None:
        if self.working or not self.chosen or self.over or (self.encrypting and not self.password):
            return
        self.working = True
        self.format_button.hide()
        self.cancel_button.hide()  # (it can't be stopped half way)
        self.title.setText(f"Formatting {self.drive.name} as {NAMES[self.chosen]}"
                           + (", encrypted" if self.encrypting else ""))
        self.question.setText("Keep it in until it's done.")
        wanted = {key for key, _t in removable.steps(self.encrypting)}
        for key, label in self.step_labels.items():
            label.setVisible(key in wanted)
        self.bar.setRange(0, len(wanted))
        self.steps.show()
        self.bar.show()
        self.state.show()
        self.started_at = self.clock()
        self.show_steps()
        self.timer.start()
        drive, fstype, run, reached = self.drive, self.chosen, self.run, self.reached
        label = self.name or "GAMES"
        encrypt = None
        if self.encrypting:
            make, password, share = self.encrypt, self.password, self.share

            def encrypt(stick):
                return make(stick, password, progress=lambda pct: setattr(self, "percent", pct), share=share)

        run_async(lambda: removable.format_drive(drive, fstype, label, run=run, step=reached.append, encrypt=encrypt),
                  self._done, self._failed, owner=self)

    def step_text(self, key: str) -> str:
        return dict(removable.STEPS)[key].format(fs=NAMES.get(self.chosen, self.chosen))

    def show_steps(self, failed: bool = False, done: bool = False) -> None:
        """Each step: done, going on now, failed, still to come."""
        reached = list(self.reached)
        current = reached[-1] if reached else ""
        for key, label in self.step_labels.items():
            if label.isHidden() and self.working:
                continue
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
            percent = f" {round(self.percent)}%" if key == "encrypt" and state == "now" and self.percent else ""
            label.setText(f"{MARKS[state]}  {self.step_text(key)}{'…' if state == 'now' else ''}{percent}")
            label.setStyleSheet(f"color: {color}; font-weight: {weight};")
            label.setProperty("state", state)
        finished = sum(1 for k in reached if k != current) + (1 if done else 0)
        if current == "encrypt" and not done:
            finished += self.percent / 100  # (the long one: its own progress)
        self.bar.setRange(0, len(removable.steps(self.encrypting)) * 100)
        self.bar.setValue(self.bar.maximum() if done and not failed else round(finished * 100))
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
        self.title.setText(f"✓ {now.name} is ready for games" + (" - encrypted" if self.encrypting else ""))
        if self.encrypting:
            self.question.setText(f"Encrypted with your code{space}. Took {took}. It opens by itself while GamingCrypt "
                                  "is unlocked - move games onto it in Settings → Storage or on a game's page.")
        else:
            self.question.setText(f"{NAMES[self.chosen]}{space}. Took {took}. Put ROMs in Emulation/roms/<system>, "
                                  "Windows games in Windows Games, Linux games in Linux Games - or move games onto "
                                  "it.")
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
        elif not self.working and not (self.code is not None and self.code.working):
            self.cancelled.emit()

    def gamepad_back(self) -> bool:
        self.cancel()
        return True
