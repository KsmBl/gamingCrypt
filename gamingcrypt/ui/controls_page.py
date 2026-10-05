"""Emulator controls: what each controller button is in an emulated system - shown and changed.

Opened from Settings -> Controller, a system's page and the quick menu (while an
emulated game runs). Works with D-pad + A as well as touch. RetroArch reads the
layout when a game starts (see emulation/layouts).
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from gamingcrypt.emulation import layouts
from gamingcrypt.emulation.systems import BY_ID
from gamingcrypt.ui.widgets import FlowLayout, big_button

ROWS_PER_COLUMN = 6


class ControlsPage(QWidget):
    closed = Signal()

    def __init__(self, store: layouts.Store, system_id: str | None = None, systems: list[str] | None = None,
                 note: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        self.store = store
        self.picked: str | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 16, 30, 16)
        top = QHBoxLayout()
        self.title = QLabel("Emulator controls")
        self.title.setObjectName("title")
        top.addWidget(self.title, 1)
        self.system_combo = QComboBox()
        for sid in systems or []:
            self.system_combo.addItem(BY_ID[sid].name, sid)
        if system_id and self.system_combo.findData(system_id) < 0:
            self.system_combo.addItem(BY_ID[system_id].name, system_id)
        if system_id:
            self.system_combo.setCurrentIndex(self.system_combo.findData(system_id))
        self.system_combo.setVisible(self.system_combo.count() > 1)
        self.system_combo.currentIndexChanged.connect(lambda _i: self.refresh())
        top.addWidget(self.system_combo)
        self.reset_button = big_button("Default layout")
        self.reset_button.clicked.connect(self.reset_layout)
        top.addWidget(self.reset_button)
        self.done_button = big_button("Done", "primary")
        self.done_button.clicked.connect(self.close_page)
        top.addWidget(self.done_button)
        layout.addLayout(top)
        self.hint = QLabel("")
        self.hint.setObjectName("cardMeta")
        self.hint.setWordWrap(True)
        layout.addWidget(self.hint)
        self.note = QLabel(note)
        self.note.setObjectName("status")
        self.note.setWordWrap(True)
        self.note.setVisible(bool(note))
        layout.addWidget(self.note)

        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        self.buttons: dict[str, object] = {}
        for index, (xbox, name) in enumerate(layouts.XBOX_NAMES.items()):
            column, row = divmod(index, ROWS_PER_COLUMN)
            label = QLabel(name)
            label.setObjectName("cardTitle")
            label.setMinimumWidth(80)
            button = big_button("")
            button.clicked.connect(lambda _c=False, b=xbox: self.pick(b))
            grid.addWidget(label, row, column * 2)
            grid.addWidget(button, row, column * 2 + 1)
            self.buttons[xbox] = button
        layout.addLayout(grid)

        self.choices_heading = QLabel("")
        self.choices_heading.setObjectName("section")
        layout.addWidget(self.choices_heading)
        self.choices_box = QWidget()
        self.choices = FlowLayout(self.choices_box)
        layout.addWidget(self.choices_box)
        layout.addStretch()
        self.refresh()

    @property
    def system(self) -> str:
        return self.system_combo.currentData() or ""

    def refresh(self) -> None:
        self.cancel_choice()
        system = self.system
        name = BY_ID[system].name if system in BY_ID else ""
        self.title.setText(f"Controls · {name}" if name else "Emulator controls")
        self.hint.setText(f"What each button of your controller is in {name}. Select one to change it - "
                          "the D-pad isn't changed. A game picks up changes when it starts.")
        current, custom = self.store.labels(system), self.store.get(system)
        for xbox, button in self.buttons.items():
            meaning = current.get(xbox, "")
            button.setText(f"{meaning}  ✎" if xbox in custom else (meaning or "-"))
            button.setProperty("custom", xbox in custom)
        self.reset_button.setVisible(bool(custom))

    def pick(self, xbox: str) -> None:
        self.picked = xbox
        while self.choices.count():
            item = self.choices.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        current = self.store.labels(self.system).get(xbox, "")
        first = None
        for name in self.store.choices(self.system):
            choice = big_button(name, "primary" if name == current else "")
            choice.clicked.connect(lambda _c=False, n=name: self.choose(n))
            self.choices.addWidget(choice)
            first = first or choice
        self.choices_heading.setText(f"{layouts.XBOX_NAMES[xbox]} should be:")
        self.choices_heading.show()
        self.choices_box.show()
        if first is not None:
            first.setFocus()

    def choose(self, name: str) -> None:
        xbox = self.picked
        self.store.set(self.system, xbox, name)
        self.refresh()
        self.buttons[xbox].setFocus()

    def cancel_choice(self) -> None:
        picked, self.picked = self.picked, None
        self.choices_heading.hide()
        self.choices_box.hide()
        if picked is not None:
            self.buttons[picked].setFocus()

    def reset_layout(self) -> None:
        self.store.reset(self.system)
        self.refresh()
        self.buttons["a"].setFocus()

    def close_page(self) -> None:
        self.cancel_choice()
        self.closed.emit()

    def gamepad_back(self) -> bool:
        if self.picked is not None:
            self.cancel_choice()
        else:
            self.close_page()
        return True

    def showEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().showEvent(event)
        self.buttons["a"].setFocus(Qt.FocusReason.OtherFocusReason)
