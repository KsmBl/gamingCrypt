"""Main UI after unlocking: a top tab bar with the media sections."""

from __future__ import annotations

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget

from gamingcrypt.ui.widgets import ComingSoon, big_button

TABS = ["Games", "Movies", "Series", "Music", "Pictures", "Settings"]


class Shell(QWidget):
    exit_requested = Signal()

    def __init__(self, pages: dict[str, QWidget] | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        pages = pages or {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        bar = QFrame()
        bar.setObjectName("topBar")
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(12, 0, 12, 0)
        self.stack = QStackedWidget()
        self.tab_buttons = {}
        self.pages = {}
        for name in TABS:
            button = big_button(name, "tab", checkable=True)
            button.clicked.connect(lambda _=False, n=name: self.show_tab(n))
            bar_layout.addWidget(button)
            self.tab_buttons[name] = button
            page = pages.get(name) or ComingSoon(name)
            self.pages[name] = page
            self.stack.addWidget(page)
        bar_layout.addStretch()
        self.exit_button = big_button("⏻")
        self.exit_button.clicked.connect(self._exit_tapped)
        bar_layout.addWidget(self.exit_button)
        self._exit_armed = False
        self._exit_timer = QTimer(self)
        self._exit_timer.setSingleShot(True)
        self._exit_timer.timeout.connect(self._disarm_exit)

        layout.addWidget(bar)
        layout.addWidget(self.stack, 1)
        self.show_tab(TABS[0])

    def show_tab(self, name: str) -> None:
        self.current_tab = name
        self.stack.setCurrentWidget(self.pages[name])
        for tab, button in self.tab_buttons.items():
            button.setChecked(tab == name)

    def _exit_tapped(self) -> None:
        # Two taps so a stray touch doesn't close the launcher.
        if self._exit_armed:
            self.exit_requested.emit()
            return
        self._exit_armed = True
        self.exit_button.setText("Tap again to exit")
        self._exit_timer.start(3000)

    def _disarm_exit(self) -> None:
        self._exit_armed = False
        self.exit_button.setText("⏻")
