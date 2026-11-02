"""A game's saves: who has how much, since when - back them up, restore, delete, and the admin can
copy them from one user to another. A user only sees their own."""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from gamingcrypt import saves
from gamingcrypt.ui.game_widgets import format_size
from gamingcrypt.ui.tasks import run_async
from gamingcrypt.ui.widgets import big_button, enable_touch_scroll, set_status


def when(timestamp: float) -> str:
    return f"{datetime.fromtimestamp(timestamp):%d %b %Y · %H:%M}"


class CopyTarget(QFrame):
    """Copy to whom? (The question over the page.)"""

    def __init__(self, source: str, targets: list[tuple[str, str]], choose, cancel):
        super().__init__()
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        question = QLabel(f"Copy {source}'s saves to whom?")
        question.setWordWrap(True)
        layout.addWidget(question)
        self.buttons = {}
        for user, name in targets:
            button = big_button(name)
            button.clicked.connect(lambda _=False, u=user: choose(u))
            layout.addWidget(button)
            self.buttons[user] = button
        self.cancel_button = big_button("Cancel")
        self.cancel_button.clicked.connect(cancel)
        layout.addWidget(self.cancel_button)
        self.cancel = cancel

    def gamepad_back(self) -> bool:
        self.cancel()
        return True


class SavesPage(QWidget):
    def __init__(self, tab, game, box, parent: QWidget | None = None):
        super().__init__(parent)
        self.tab, self.game, self.box = tab, game, box
        self.buttons: dict = {}  # (user, what, which backup): its button
        self.last_pressed = None
        self.modal = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 16, 30, 20)
        layout.setSpacing(12)
        top = QHBoxLayout()
        top.addWidget(tab.back_button())
        title = QLabel(f"Saves · {game.name}")
        title.setObjectName("title")
        top.addWidget(title, 1)
        layout.addLayout(top)
        self.note = QLabel(self._note_text())
        self.note.setObjectName("cardMeta")
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        self.status = QLabel("")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        self.status.hide()
        layout.addWidget(self.status)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        enable_touch_scroll(scroll)
        self.inner = QWidget()
        self.rows = QVBoxLayout(self.inner)
        self.rows.setContentsMargins(0, 0, 0, 0)
        self.rows.setSpacing(12)
        self.rows.addStretch()
        scroll.setWidget(self.inner)
        layout.addWidget(scroll, 1)
        self.reload()

    # who ------------------------------------------------------------------------------------
    @property
    def is_admin(self) -> bool:
        return self.tab.user is None or self.tab.user.admin

    @property
    def me(self) -> str:
        return "" if self.is_admin else self.tab.user.id

    def people(self) -> dict[str, str]:
        """The users as they're called here: id ("" the admin) -> name."""
        listed = self.tab.people() if getattr(self.tab, "people", None) is not None else []
        names = {("" if user.admin else user.id): user.name for user in listed}
        names.setdefault("", "Admin")
        return names

    def name_of(self, user: str) -> str:
        return self.people().get(user, "A deleted user")

    def _note_text(self) -> str:
        parts = [self.box.NOTE, f"The {saves.MAX_BACKUPS} newest backups of each user are kept."]
        if not self.is_admin:
            parts.insert(0, "Saves from before everyone had their own are with the admin, who can copy them to you here.")
        return " ".join(part for part in parts if part)

    # what's there ---------------------------------------------------------------------------
    def reload(self) -> None:
        users = list(self.people()) if self.is_admin else [self.me]
        box, me, admin = self.box, self.me, self.is_admin

        def look() -> list:
            found = saves.overview(box, users)
            return found if admin else [row for row in found if row.user == me]  # only your own

        run_async(look, self._show, lambda exc: self.say(f"Couldn't look at the saves: {exc}", error=True), owner=self)

    def _show(self, found: list) -> None:
        self.found = found
        self.buttons = {}
        while self.rows.count() > 1:
            widget = self.rows.takeAt(0).widget()
            widget.setParent(None)
            widget.deleteLater()
        for index, row in enumerate(found):
            self.rows.insertWidget(index, self._card(row))
        self.inner.setEnabled(True)
        target = self.buttons.get(self.last_pressed) or next(iter(self.buttons.values()), None)
        if target is not None and self.isVisible():
            target.setFocus(Qt.FocusReason.TabFocusReason)

    def _card(self, row) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(22, 16, 22, 16)
        layout.setSpacing(10)
        name = QLabel(self.name_of(row.user))
        name.setObjectName("cardTitle")
        layout.addWidget(name)
        facts = (f"{format_size(row.size)}  ·  last changed {when(row.changed)}" if row.has_saves else "No saves yet")
        meta = QLabel(facts)
        meta.setObjectName("cardMeta")
        layout.addWidget(meta)
        if row.has_saves:
            actions = QHBoxLayout()
            self._button(actions, row, "backup", "💾 Back up", lambda: self.back_up(row))
            if self.is_admin and self._targets(row):
                self._button(actions, row, "copy", "📋 Copy to…", lambda: self.ask_copy(row))
            self._button(actions, row, "delete", "🗑 Delete", lambda: self.ask_delete(row), "danger")
            actions.addStretch()
            layout.addLayout(actions)
        for backup in row.backups:
            line = QHBoxLayout()
            label = QLabel(f"Backup of {when(backup.made)}  ·  {format_size(backup.size)}")
            label.setObjectName("cardMeta")
            line.addWidget(label, 1)
            self._button(line, row, "restore", "↩ Restore", lambda b=backup: self.ask_restore(row, b), which=backup.path.name)
            self._button(line, row, "drop", "🗑", lambda b=backup: self.ask_delete_backup(b), which=backup.path.name)
            layout.addLayout(line)
        return card

    def _button(self, layout, row, what: str, text: str, action, kind: str = "", which: str = ""):
        button = big_button(text, kind) if kind else big_button(text)
        key = (row.user, what, which)

        def pressed() -> None:
            self.last_pressed = key
            action()

        button.clicked.connect(pressed)
        layout.addWidget(button)
        self.buttons[key] = button
        return button

    def _targets(self, row) -> list[tuple[str, str]]:
        return [(user, name) for user, name in self.people().items() if user != row.user]

    def say(self, text: str, error: bool = False) -> None:
        set_status(self.status, text, error=error)
        self.status.setVisible(bool(text))

    # what can be done -----------------------------------------------------------------------
    def _game_running(self) -> bool:
        watcher = getattr(self.window(), "game_watcher", None)
        if watcher is not None and watcher.active:
            self.say("Close the running game first", error=True)
            return True
        return False

    def _run(self, busy_text: str, work, done_text: str) -> None:
        if self._game_running():
            return
        self.say(busy_text)
        self.inner.setEnabled(False)

        def finished(_result) -> None:
            self.say(done_text)
            self.reload()

        def failed(exc: Exception) -> None:
            self.say(str(exc), error=True)
            self.reload()

        run_async(work, finished, failed, owner=self)

    def _ask(self, question: str, action: str, on_yes, danger: bool = True) -> None:
        from gamingcrypt.ui.modal import ask

        ask(self, question, action, on_yes, danger)

    def back_up(self, row) -> None:
        box = self.box
        self._run("Backing up… this can take a while", lambda: saves.back_up(box, row.user), "Backed up ✓")

    def ask_delete(self, row) -> None:
        box = self.box
        self._ask(f"Delete {self.name_of(row.user)}'s saves of {self.game.name}?\n"
                  "Their backups stay. Without one, the saves can't be brought back.", "🗑 Delete",
                  lambda: self._run("Deleting…", lambda: saves.delete(box, row.user), "Deleted"))

    def ask_restore(self, row, backup) -> None:
        box = self.box
        self._ask(f"Go back to the backup of {when(backup.made)}?\nThe saves as they are now are backed up first.",
                  "↩ Restore", lambda: self._run("Restoring… this can take a while",
                                                 lambda: saves.restore(box, row.user, backup), "Restored ✓"),
                  danger=False)

    def ask_delete_backup(self, backup) -> None:
        self._ask(f"Delete the backup of {when(backup.made)}?", "🗑 Delete",
                  lambda: self._run("Deleting…", lambda: saves.delete_backup(backup), "Backup deleted"))

    def ask_copy(self, row) -> None:
        from gamingcrypt.ui.modal import show_modal

        def close() -> None:
            if self.modal is not None:
                self.modal.close_modal()
                self.modal = None

        def chosen(user: str) -> None:
            close()
            self.confirm_copy(row, user)

        box = CopyTarget(self.name_of(row.user), self._targets(row), chosen, close)
        self.modal = show_modal(self, box, close)

    def confirm_copy(self, row, target: str) -> None:
        box = self.box
        source_name, target_name = self.name_of(row.user), self.name_of(target)
        has = next((r.has_saves for r in self.found if r.user == target), False)
        replaced = f"\n{target_name}'s saves are replaced - they're backed up first." if has else ""
        self._ask(f"Copy {source_name}'s saves of {self.game.name} to {target_name}?{replaced}", "📋 Copy",
                  lambda: self._run("Copying… this can take a while", lambda: saves.copy_to(box, row.user, target),
                                    f"Copied to {target_name} ✓"), danger=has)
