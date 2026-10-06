"""First-start tour (a few screens on how to use GamingCrypt) and "What's new" after an
update (written by install.sh from the commits since the last install)."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from gamingcrypt.ui.widgets import big_button, enable_touch_scroll

TOUR = [
    ("🎮", "Welcome to GamingCrypt",
     "Your games live on an encrypted drive. GamingCrypt unlocks it with your code when the device "
     "starts and is the console screen for everything you play."),
    ("✚", "Controller",
     "D-pad or stick moves the highlight, A selects, B goes back, LB / RB switch tabs.\n"
     "The Windows button opens the quick menu - also in a game: volume, brightness, audio devices, "
     "battery, force quit."),
    ("⏻", "Power",
     "The power button puts the device to sleep. ⏻ at the top right: sleep, shut down, restart, "
     "restart into Windows and desktop mode."),
    ("▶", "Playing",
     "Continue playing sits at the top of Games. On a game's page, Options lets you choose the Proton "
     "version and an own power and FPS limit for that game."),
    ("✓", "If something doesn't work",
     "Settings → Health shows what's missing and how to fix it - usually by running ./install.sh again."),
]
MAX_NEWS_LINES = 40  # the list scrolls
WINDOW_MARGIN = 40  # the card keeps this far from the window's edges


class _Overlay(QWidget):
    """Dimmed full-window overlay with a card in the middle."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        outer = QVBoxLayout(self)
        outer.addStretch()
        self.card = QFrame()
        self.card.setObjectName("card")
        self.card.setFixedWidth(720)
        self.box = QVBoxLayout(self.card)
        self.box.setContentsMargins(32, 28, 32, 28)
        self.box.setSpacing(16)
        outer.addWidget(self.card, alignment=Qt.AlignmentFlag.AlignCenter)
        outer.addStretch()
        self.hide()

    def open(self) -> None:
        self.setGeometry(self.parentWidget().rect())
        self.raise_()
        self.show()

    def fit(self, label: QLabel) -> None:
        """Wrapped text: tell the layout how tall it really is at the card's width (it
        keeps the old height otherwise and cuts the text off)."""
        margins = self.box.contentsMargins()
        label.setMinimumHeight(label.heightForWidth(self.card.width() - margins.left() - margins.right()))


class Tour(_Overlay):
    finished = Signal()

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.icon = QLabel("")
        self.icon.setObjectName("title")
        self.title = QLabel("")
        self.title.setObjectName("section")
        top = QHBoxLayout()
        top.addWidget(self.icon)
        top.addWidget(self.title, 1)
        self.box.addLayout(top)
        self.text = QLabel("")
        self.text.setWordWrap(True)
        self.box.addWidget(self.text)
        self.step_label = QLabel("")
        self.step_label.setObjectName("cardMeta")
        self.box.addWidget(self.step_label)
        row = QHBoxLayout()
        self.skip_button = big_button("Skip")
        self.back_button = big_button("‹  Back")
        self.next_button = big_button("Next  ›", "primary")
        self.skip_button.clicked.connect(self.finish)
        self.back_button.clicked.connect(lambda: self.show_step(self.step - 1))
        self.next_button.clicked.connect(self.next)
        row.addWidget(self.skip_button)
        row.addStretch()
        row.addWidget(self.back_button)
        row.addWidget(self.next_button)
        self.box.addLayout(row)
        self.step = 0

    def open(self) -> None:
        super().open()
        self.show_step(0)

    def show_step(self, step: int) -> None:
        self.step = max(0, min(len(TOUR) - 1, step))
        icon, title, text = TOUR[self.step]
        self.icon.setText(icon)
        self.title.setText(title)
        self.text.setText(text)
        self.fit(self.text)
        self.step_label.setText(f"{self.step + 1} / {len(TOUR)}")
        self.back_button.setEnabled(self.step > 0)
        last = self.step == len(TOUR) - 1
        self.next_button.setText("Let's go" if last else "Next  ›")
        self.skip_button.setVisible(not last)
        self.next_button.setFocus()

    def next(self) -> None:
        if self.step == len(TOUR) - 1:
            self.finish()
        else:
            self.show_step(self.step + 1)

    def finish(self) -> None:
        self.hide()
        self.finished.emit()

    def gamepad_back(self) -> bool:
        if not self.isVisible():
            return False
        if self.step > 0:
            self.show_step(self.step - 1)
        else:
            self.finish()
        return True


def data_dir(env: dict | None = None) -> Path:
    env = os.environ if env is None else env
    base = env.get("XDG_DATA_HOME") or str(Path(env.get("HOME", str(Path.home()))) / ".local" / "share")
    return Path(base) / "gamingcrypt"


def news_file(env: dict | None = None) -> Path:
    return data_dir(env) / "whats-new.txt"


def read_news(path: Path) -> list[str]:
    try:
        lines = [line.strip() for line in path.read_text().splitlines()]
    except OSError:
        return []
    return [line for line in lines if line and not line.lower().startswith(("release ", "tests:"))]


def mark_news_read(path: Path) -> None:
    try:
        path.replace(path.with_suffix(".seen"))
    except OSError:
        pass


class WhatsNew(_Overlay):
    """The changes since the last update - in a list that scrolls when it's longer than the
    screen (finger, or up / down on the controller)."""

    closed = Signal()
    navigation_complete = True  # the controller stays in here

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.card.setFixedWidth(900)
        title = QLabel("What's new")
        title.setObjectName("section")
        self.box.addWidget(title)
        self.text = QLabel("")
        self.text.setWordWrap(True)
        self.text.setObjectName("detailMeta")
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setWidget(self.text)
        enable_touch_scroll(self.scroll)
        self.box.addWidget(self.scroll, 1)
        self.ok_button = big_button("OK", "primary")
        self.ok_button.clicked.connect(self.close_news)
        self.box.addWidget(self.ok_button, alignment=Qt.AlignmentFlag.AlignRight)

    def open_news(self, lines: list[str]) -> None:
        shown = lines[:MAX_NEWS_LINES]
        text = "\n".join(f"• {line}" for line in shown)
        if len(lines) > len(shown):
            text += f"\n… and {len(lines) - len(shown)} more"
        self.text.setText(text)
        self.open()
        self.fit_to_window()
        self.ok_button.setFocus()

    def fit_to_window(self) -> None:
        """As tall as the text needs - but never taller than the window (then it scrolls)."""
        margins = self.box.contentsMargins()
        width = self.card.width() - margins.left() - margins.right() - 16  # (room for the scroll bar)
        text_height = self.text.heightForWidth(width)
        others = self.card.sizeHint().height() - self.scroll.sizeHint().height()
        room = self.height() - 2 * WINDOW_MARGIN - others
        self.scroll.setFixedHeight(max(120, min(text_height + 4, room)))
        self.scroll.verticalScrollBar().setValue(0)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        if self.isVisible():
            self.fit_to_window()

    def gamepad_navigate(self, current, dx: int, dy: int):
        """Up / down scroll the list (the OK button is the only thing to select)."""
        if dy:
            bar = self.scroll.verticalScrollBar()
            bar.setValue(bar.value() + dy * 120)
        return None

    def close_news(self) -> None:
        self.hide()
        self.closed.emit()

    def gamepad_back(self) -> bool:
        if self.isVisible():
            self.close_news()
            return True
        return False
