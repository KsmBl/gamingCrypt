"""Settings -> Security -> Users: the admin adds, renames and deletes users, gives each a code
and an age; a user changes their own code. (What a user is: gamingcrypt/users.py.)"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from gamingcrypt import users
from gamingcrypt.ui.combo import ComboBox
from gamingcrypt.ui.secret_input import METHOD_LABELS, SecretInput
from gamingcrypt.ui.tasks import run_async
from gamingcrypt.ui.widgets import OnScreenKeyboard, big_button, set_status


class NamePage(QWidget):
    """A name, typed on the on-screen keyboard."""

    entered = Signal(str)
    cancelled = Signal()

    def __init__(self, title: str, name: str = "", check: Callable[[str], str] | None = None):
        super().__init__()
        self.check = check
        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 20, 40, 20)
        heading = QLabel(title)
        heading.setObjectName("title")
        layout.addWidget(heading)
        self.edit = QLineEdit(name)
        self.edit.setMaxLength(users.MAX_NAME)
        self.edit.setPlaceholderText("Name")
        layout.addWidget(self.edit)
        self.status = QLabel("")
        self.status.setObjectName("status")
        layout.addWidget(self.status)
        self.keyboard = OnScreenKeyboard(self.edit, compact=True)
        self.keyboard.submitted.connect(self.submit)
        layout.addWidget(self.keyboard)
        buttons = QHBoxLayout()
        self.cancel_button = big_button("Cancel")
        self.cancel_button.clicked.connect(self.cancelled.emit)
        buttons.addWidget(self.cancel_button)
        buttons.addStretch()
        self.ok_button = big_button("Continue", "primary")
        self.ok_button.clicked.connect(self.submit)
        buttons.addWidget(self.ok_button)
        layout.addLayout(buttons)

    def submit(self) -> None:
        try:
            name = self.check(self.edit.text()) if self.check else self.edit.text().strip()
        except users.UserError as exc:
            set_status(self.status, str(exc), error=True)
            return
        self.entered.emit(name)

    def gamepad_back(self) -> bool:
        self.cancelled.emit()
        return True


class CodeFlow(QWidget):
    """Asks for codes, one after the other: ``steps`` are ("code", key, method, prompt) - a code
    entered with that method - ("new", key, prompt) - a new code: its method is chosen, then it's
    entered twice. ``finish(answers) -> str`` does the work (in the background: making a key from
    a code takes a second) and returns what to say; a users.UserError is shown and the flow starts
    again. answers: {key: code, key + "_method": method}."""

    done = Signal(str)
    cancelled = Signal()

    def __init__(self, title: str, steps: list[tuple], finish: Callable[[dict], str]):
        super().__init__()
        self.steps, self.finish = steps, finish
        self.answers: dict[str, str] = {}
        self.index = 0
        self.busy = False
        self.pending: str | None = None  # a new code, waiting to be repeated
        # Little around the pad: the 5 x 5 pattern needs the height (it was cut off on 1280 x 800).
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 8, 30, 8)
        layout.setSpacing(4)
        top = QHBoxLayout()
        self.cancel_button = big_button("Cancel")
        self.cancel_button.clicked.connect(self._cancel)
        top.addWidget(self.cancel_button)
        heading = QLabel(title)
        heading.setObjectName("section")
        top.addWidget(heading)
        self.prompt = QLabel("")
        self.prompt.setObjectName("subtitle")
        top.addWidget(self.prompt, 1)
        layout.addLayout(top)
        self.status = QLabel("")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.body = QVBoxLayout()
        layout.addLayout(self.body, 1)
        self.widget: QWidget | None = None
        self.method_buttons: dict[str, QWidget] = {}
        self.input: SecretInput | None = None
        self.show_step()

    def _show(self, widget: QWidget) -> None:
        if self.widget is not None:
            self.body.removeWidget(self.widget)
            self.widget.hide()  # (gone at once: it would lie over the next one until it's deleted)
            self.widget.deleteLater()
        self.widget = widget
        self.body.addWidget(widget, 1)

    def _ask(self, method: str, prompt: str, handler) -> None:
        self.prompt.setText(prompt)
        self.input = SecretInput(method)
        self.input.secret_entered.connect(handler)
        self.input.invalid.connect(lambda text: set_status(self.status, text, error=True))
        self.method_buttons = {}
        self._show(self.input)

    def show_step(self) -> None:
        self.pending = None
        while self.index < len(self.steps) and self.steps[self.index][1] in self.answers:
            self.index += 1  # entered already (a wrong code after it is asked again on its own)
        if self.index >= len(self.steps):
            self._finish()
            return
        step = self.steps[self.index]
        if step[0] == "code":
            _kind, key, method, prompt = step
            self._ask(method, prompt, lambda secret: self._answer(key, secret))
            return
        _kind, key, prompt = step
        self.prompt.setText(prompt)
        box = QWidget()
        row = QHBoxLayout(box)
        row.addStretch()
        self.method_buttons = {}
        for method, label in METHOD_LABELS.items():
            button = big_button(label)
            button.clicked.connect(lambda _c=False, m=method: self.choose_method(m))
            row.addWidget(button)
            self.method_buttons[method] = button
        row.addStretch()
        self.input = None
        self._show(box)

    def choose_method(self, method: str) -> None:
        _kind, key, _prompt = self.steps[self.index]
        self.answers[key + "_method"] = method
        self._ask(method, f"Choose the new {METHOD_LABELS[method]}", self._new_entered)

    def _new_entered(self, secret: str) -> None:
        _kind, key, _prompt = self.steps[self.index]
        method = self.answers[key + "_method"]
        if self.pending is None:
            self.pending = secret
            set_status(self.status, "")
            self._ask(method, f"Repeat the new {METHOD_LABELS[method]}", self._new_entered)
            return
        if secret != self.pending:
            self.pending = None
            set_status(self.status, "That didn't match - try again", error=True)
            self._ask(method, f"Choose the new {METHOD_LABELS[method]}", self._new_entered)
            return
        self._answer(key, secret)

    def _answer(self, key: str, secret: str) -> None:
        self.answers[key] = secret
        self.index += 1
        set_status(self.status, "")
        self.show_step()

    def _finish(self) -> None:
        self.busy = True
        self.cancel_button.setEnabled(False)
        self.prompt.setText("One moment…")
        self._show(QWidget())
        answers = dict(self.answers)
        run_async(lambda: self.finish(answers), self._finished, self._failed, owner=self)

    def _finished(self, message: str) -> None:
        self.busy = False
        self.done.emit(message or "")

    def _failed(self, exc: Exception) -> None:
        self.busy = False
        self.cancel_button.setEnabled(True)
        keys = [step[1] for step in self.steps]
        wrong = getattr(exc, "step", None) if isinstance(exc, users.UserError) else None
        if wrong in keys:  # only that code again: the new one, chosen and repeated before, stays
            self.answers.pop(wrong, None)
            self.index = keys.index(wrong)
        else:
            self.answers, self.index = {}, 0
        self.show_step()
        set_status(self.status, str(exc) if isinstance(exc, users.UserError) else f"That didn't work: {exc}",
                   error=True)

    def _cancel(self) -> None:
        if not self.busy:
            self.cancelled.emit()

    def gamepad_back(self) -> bool:
        self._cancel()
        return True


class UsersSection(QFrame):
    """The list of users with what can be done with each. ``tab``: the Settings tab (its config,
    its save and its stack of pages); ``admin_check(code) -> bool``: is that the code the admin
    unlocked with? (needed once, for the very first user); ``code_changed(code)``: whoever is
    logged in has a new code (the lock after sleep checks that one from now on)."""

    changed = Signal()

    def __init__(self, tab, admin_check: Callable[[str], bool] | None = None,
                 code_changed: Callable[[str], None] | None = None):
        super().__init__()
        self.tab, self.admin_check, self.code_changed = tab, admin_check, code_changed
        self.setObjectName("card")
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(24, 18, 24, 18)
        heading = QLabel("Users")
        heading.setObjectName("section")
        self.body.addWidget(heading)
        self.hint = QLabel("")
        self.hint.setObjectName("cardMeta")
        self.hint.setWordWrap(True)
        self.body.addWidget(self.hint)
        self.list = QVBoxLayout()
        self.body.addLayout(self.list)
        self.add_button = big_button("+  Add a user", "primary")
        self.add_button.clicked.connect(self.add_user)
        self.body.addWidget(self.add_button, alignment=Qt.AlignmentFlag.AlignLeft)
        self.rows: dict[str, dict] = {}
        self.refresh()

    @property
    def config(self) -> dict:
        return self.tab.config

    def refresh(self) -> None:
        while self.list.count():
            item = self.list.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.rows = {}
        me = users.current(self.config)
        self.add_button.setVisible(me.admin)
        self.hint.setText("Each user unlocks the drive with a code of their own. Only the admin can delete games; "
                          "a user with an age sees only the games rated for it."
                          if me.admin else f"You're logged in as {me.name}.")
        for user in users.all_users(self.config):
            if not me.admin and user.id != me.id:
                continue  # the others are the admin's business
            row = QWidget()
            row.setObjectName("menuRow")
            line = QHBoxLayout(row)
            line.setContentsMargins(0, 0, 0, 0)
            code = "" if users.has_code(self.config, user.id) else "  ·  needs a new code"
            label = QLabel(f"{user.name}  ·  {'Admin' if user.admin else 'User'}{code}")
            label.setObjectName("cardTitle" if user.id == me.id else "detailMeta")
            line.addWidget(label, 1)
            widgets: dict = {"label": label}
            if me.admin:
                rename = big_button("Rename")
                rename.clicked.connect(lambda _c=False, u=user: self.rename_user(u))
                line.addWidget(rename)
                widgets["rename"] = rename
            if me.admin and not user.admin:
                age = ComboBox()
                age.addItem("Any age", None)
                for years in users.AGES:
                    age.addItem(f"Age {years}", years)
                if user.age is not None and age.findData(user.age) < 0:
                    age.addItem(f"Age {user.age}", user.age)
                age.setCurrentIndex(max(0, age.findData(user.age)))
                age.currentIndexChanged.connect(lambda _i, u=user, c=age: self.set_age(u, c.currentData()))
                line.addWidget(age)
                widgets["age"] = age
            if me.admin and not user.admin and self.steam_accounts():
                # (Settings -> Games isn't there for users: the admin says which Steam account is theirs)
                steam = ComboBox()
                steam.addItem("Steam: as it is", "")
                for account in self.steam_accounts():
                    steam.addItem(f"Steam: {account.persona}", account.steam_id)
                chosen = next((u.get("steam", {}).get("account", "") for u in self.config.get("users", [])
                               if isinstance(u, dict) and u.get("id") == user.id), "")
                steam.setCurrentIndex(max(0, steam.findData(chosen)))
                steam.currentIndexChanged.connect(lambda _i, u=user, c=steam: self.set_steam(u, c))
                line.addWidget(steam)
                widgets["steam"] = steam
            if not user.admin:
                code_button = big_button("New code")
                code_button.clicked.connect(lambda _c=False, u=user: self.new_code(u))
                line.addWidget(code_button)
                widgets["code"] = code_button
            if me.admin and not user.admin:
                delete = big_button("Delete", "danger")
                delete.clicked.connect(lambda _c=False, u=user: self.delete_user(u))
                line.addWidget(delete)
                widgets["delete"] = delete
            self.list.addWidget(row)
            if me.admin and not user.admin:  # what this user doesn't get
                locks = QWidget()
                locks.setObjectName("menuRow")
                lock_line = QHBoxLayout(locks)
                lock_line.setContentsMargins(24, 0, 0, 6)
                caption = QLabel("Locked:")
                caption.setObjectName("cardMeta")
                lock_line.addWidget(caption)
                widgets["locks"] = {}
                for tab in users.LOCKABLE:
                    button = big_button("", checkable=True)
                    button.setChecked(tab in user.locked)
                    button.setText(("🔒 " if tab in user.locked else "") + tab)
                    button.toggled.connect(lambda on, u=user, t=tab: self.set_locked(u, t, on))
                    lock_line.addWidget(button)
                    widgets["locks"][tab] = button
                lock_line.addStretch()
                self.list.addWidget(locks)
            self.rows[user.id] = widgets

    def _saved(self, message: str = "") -> None:
        self.tab.save(self.config)
        users.write_sidecar(self.config)
        self.refresh()
        self.changed.emit()
        if message:
            set_status(self.tab.status, message)

    def _open(self, page: QWidget) -> None:
        self.tab.addWidget(page)
        self.tab.setCurrentWidget(page)

    def _close(self, message: str = "") -> None:
        self.tab.close_page(message)
        self.refresh()

    # what the admin does ------------------------------------------------------------------------
    def set_age(self, user, age) -> None:
        users.set_age(self.config, user.id, age)
        self._saved(f"{user.name}: games for {'any age' if age is None else f'age {age}'}")

    def steam_accounts(self) -> list:
        """The Steam accounts that logged in on this device."""
        if not hasattr(self, "_steam_accounts"):
            try:
                self._steam_accounts = list(self.tab.steam.accounts())
            except Exception:  # noqa: BLE001 - no Steam: nothing to choose
                self._steam_accounts = []
        return self._steam_accounts

    def set_steam(self, user, combo) -> None:
        users.set_steam_account(self.config, user.id, combo.currentData() or "")
        self._saved(f"{user.name}: {combo.currentText()} - from their next login")

    def set_locked(self, user, tab: str, locked: bool) -> None:
        users.set_locked(self.config, user.id, tab, locked)
        self._saved(f"{user.name}: {tab} {'locked' if locked else 'open again'} - from their next login")

    def rename_user(self, user) -> None:
        page = NamePage(f"Rename {user.name}", user.name, lambda text: users.check_name(self.config, text, user.id))

        def entered(name: str) -> None:
            users.rename(self.config, user.id, name)
            self.tab.save(self.config)
            users.write_sidecar(self.config)
            self._close(f"{user.name} is {name} now")
            self.changed.emit()

        page.entered.connect(entered)
        page.cancelled.connect(lambda: self._close())
        self._open(page)

    def add_user(self) -> None:
        page = NamePage("Name of the new user", check=lambda text: users.check_name(self.config, text))
        page.entered.connect(self._add_named)
        page.cancelled.connect(lambda: self._close())
        self._open(page)

    def _admin_step(self) -> tuple:
        me = users.admin(self.config)
        return ("code", "admin", me.method, f"Now the admin's code ({me.name}) - it lets the new code open the drive")

    def _add_named(self, name: str) -> None:
        self.tab.close_page("")
        config, check = self.config, self.admin_check

        def finish(answers: dict) -> str:
            master = users.admin_master(config, answers["admin"], check)
            users.add(config, name, answers["new_method"], answers["new"], master)
            return f"{name} can log in now"

        flow = CodeFlow(f"A code for {name}", [("new", "new", f"How does {name} unlock?"), self._admin_step()],
                        finish)
        self._run(flow)

    def new_code(self, user) -> None:
        """The admin gives a user another code - or the user changes their own (with the old one)."""
        config, check = self.config, self.admin_check
        me = users.current(config)
        if me.admin:
            def finish(answers: dict) -> str:
                master = users.admin_master(config, answers["admin"], check)
                users.set_code(config, user.id, answers["new_method"], answers["new"], master)
                return f"{user.name} has a new code"

            steps = [("new", "new", f"How does {user.name} unlock from now on?"), self._admin_step()]
        else:
            def finish(answers: dict) -> str:
                master = users.user_master(config, user.id, answers["old"])
                if master is None:
                    raise users.UserError("That's not your current code", step="old")
                users.set_code(config, user.id, answers["new_method"], answers["new"], master)
                return "Your code is changed"

            steps = [("code", "old", user.method, f"Your current {METHOD_LABELS.get(user.method, 'code')}"),
                     ("new", "new", "How do you want to unlock from now on?")]
        flow = CodeFlow(f"A new code for {user.name}", steps, finish)
        own = user.id == me.id
        self._run(flow, lambda: self.code_changed(flow.answers["new"]) if own and self.code_changed else None)

    def _run(self, flow: CodeFlow, then: Callable[[], None] | None = None) -> None:
        def done(message: str) -> None:
            self.tab.save(self.config)
            users.write_sidecar(self.config)
            if then is not None:
                then()
            self._close(message)
            self.changed.emit()

        flow.done.connect(done)
        flow.cancelled.connect(lambda: self._close())
        self._open(flow)

    def delete_user(self, user) -> None:
        from gamingcrypt.ui.modal import ask

        def delete() -> None:
            users.remove(self.config, user.id)
            self._saved(f"{user.name} is deleted")

        ask(self.tab, f"Delete the user {user.name}?\nTheir code won't open the drive any more. Their save "
                      "states stay on the drive.", "Delete", delete)
