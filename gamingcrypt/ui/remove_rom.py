"""Asking before an emulated game is removed - and whether its saves go too.

Used on the game's page (Options) and in Settings -> Storage.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from gamingcrypt.emulation import removal
from gamingcrypt.ui.game_widgets import format_size
from gamingcrypt.ui.tasks import run_async
from gamingcrypt.ui.widgets import big_button


class RemoveConfirm(QFrame):
    removed = Signal(str)  # what happened
    cancelled = Signal()

    def __init__(self, paths, game, parent=None):
        super().__init__(parent)
        self.paths, self.game = paths, game
        self.setObjectName("card")
        self.plan = removal.plan(paths, game)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        self.question = QLabel(f"Really remove {game.name}?\nIts game files ({format_size(self.plan.files_size)}) "
                               "are deleted from the drive.")
        self.question.setWordWrap(True)
        layout.addWidget(self.question)
        saves = self.plan.saves
        self.saves_button = big_button("", checkable=True)
        self.saves_button.toggled.connect(self._saves_text)
        self._saves_text(False)
        self.saves_button.setVisible(bool(saves))
        layout.addWidget(self.saves_button, alignment=Qt.AlignmentFlag.AlignLeft)
        if not saves:
            none = QLabel("It has no save states or memory card.")
            none.setObjectName("cardMeta")
            layout.addWidget(none)
        row = QHBoxLayout()
        self.remove_button = big_button("🗑 Remove", "danger")
        self.remove_button.clicked.connect(self.confirm)
        self.cancel_button = big_button("Cancel")
        self.cancel_button.clicked.connect(self.cancelled.emit)
        row.addWidget(self.remove_button)
        row.addWidget(self.cancel_button)
        row.addStretch()
        layout.addLayout(row)

    def _saves_text(self, on: bool) -> None:
        count = len(self.plan.saves)
        self.saves_button.setText(f"{'☑' if on else '☐'}  Also delete its save states and memory card "
                                  f"({count} file{'s' if count != 1 else ''}, {format_size(self.plan.saves_size)})")

    def gamepad_back(self) -> bool:
        self.cancelled.emit()
        return True

    def confirm(self) -> None:
        self.remove_button.setEnabled(False)
        self.cancel_button.setEnabled(False)
        with_saves = self.saves_button.isChecked()
        paths, game = self.paths, self.game

        def done(freed: int) -> None:
            kept = "" if with_saves or not self.plan.saves else " - its saves are kept"
            self.removed.emit(f"{game.name} removed, {format_size(freed)} freed{kept}")

        run_async(lambda: removal.remove(paths, game, with_saves), done,
                  lambda exc: self.removed.emit(f"Could not remove it: {exc}"), owner=self)
