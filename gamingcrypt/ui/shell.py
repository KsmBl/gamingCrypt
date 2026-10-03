"""Main UI after unlocking: a top tab bar with the media sections."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget

from gamingcrypt.ui.power_menu import PowerMenu
from gamingcrypt.ui.widgets import ComingSoon, big_button

TABS = ["Games", "Downloads", "Movies", "Shows", "Music", "Pictures", "Settings"]


class Shell(QWidget):
    exit_requested = Signal()  # desktop mode
    power_requested = Signal(str)  # "shutdown" / "restart"

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
        self.exit_button.clicked.connect(self.open_power_menu)
        bar_layout.addWidget(self.exit_button)

        layout.addWidget(bar)
        layout.addWidget(self.stack, 1)
        downloads = self.pages.get("Downloads")
        if hasattr(downloads, "count_changed"):
            downloads.count_changed.connect(lambda n: self.set_badge("Downloads", n))
        self.show_tab(TABS[0])

        self.power_menu = PowerMenu(self)
        self.power_menu.desktop.connect(self.exit_requested.emit)
        self.power_menu.shutdown.connect(lambda: self.power_requested.emit("shutdown"))
        self.power_menu.restart.connect(lambda: self.power_requested.emit("restart"))

    def open_power_menu(self) -> None:
        self.power_menu.open_menu()

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self.power_menu.setGeometry(self.rect())

    def cycle_tab(self, delta: int) -> None:
        """LB / RB on the controller."""
        index = (TABS.index(self.current_tab) + delta) % len(TABS)
        self.show_tab(TABS[index])

    def set_badge(self, name: str, count: int) -> None:
        """e.g. "Downloads (2)" - plain name when there's nothing."""
        self.tab_buttons[name].setText(f"{name} ({count})" if count else name)

    def show_tab(self, name: str) -> None:
        self.current_tab = name
        self.stack.setCurrentWidget(self.pages[name])
        for tab, button in self.tab_buttons.items():
            button.setChecked(tab == name)
