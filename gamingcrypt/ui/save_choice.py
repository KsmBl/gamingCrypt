"""Which saves to play with: the game was played on here and on another device since the saves were
last the same (save_history CONFLICT). One button for each - the other ones stay in the history."""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QLabel, QVBoxLayout

from gamingcrypt.ui.widgets import big_button


def describe(version, me: str) -> str:
    """"This device · 24 Nov 2026 · 21:14 · 293 KB"."""
    from gamingcrypt.ui.game_widgets import format_size
    from gamingcrypt.ui.saves_page import when

    where = "This device" if version.device == me else version.device_name
    return f"{where}  ·  {when(version.made)}  ·  {format_size(version.size)}"


class SaveChoice(QFrame):
    def __init__(self, game_name: str, versions: list, me: str, choose, cancel):
        super().__init__()
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        places = list(dict.fromkeys("this device" if v.device == me else v.device_name for v in versions))
        where = ", ".join(places[:-1]) + f" and {places[-1]}" if len(places) > 1 else "two devices"
        question = QLabel(f"{game_name} was played on {where} since its saves were last the same. "
                          "Which saves do you want to play with?\nThe others stay in the history (Options → Saves).")
        question.setWordWrap(True)
        layout.addWidget(question)
        self.buttons = {}
        for version in versions:
            button = big_button(describe(version, me), "primary" if version.device == me else "")
            button.clicked.connect(lambda _=False, v=version: choose(v))
            layout.addWidget(button)
            self.buttons[version.id] = button
        self.cancel_button = big_button("Cancel")
        self.cancel_button.clicked.connect(cancel)
        layout.addWidget(self.cancel_button)
        self.cancel = cancel
        first = next(iter(self.buttons.values()), None)
        if first is not None:
            first.setFocus()

    def gamepad_back(self) -> bool:
        self.cancel()
        return True
