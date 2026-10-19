"""Games tab: Minecraft - the instances, signing in with a Microsoft account, a new instance and an
instance's page (installed on its first Play, then started).

The tab has the same pieces as for Windows and Linux games (see wine_pages), for the kind
"minecraft" - and minecraft_paths() / minecraft_account() for portablemc.
"""

from __future__ import annotations

import shiboken6
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit, QProgressBar, QScrollArea, QSizePolicy,
                               QVBoxLayout, QWidget)

from gamingcrypt.minecraft import installer, library, mods, portable
from gamingcrypt.minecraft.library import FABRIC, LATEST, VANILLA, MinecraftInstance
from gamingcrypt.ui.combo import ComboBox
from gamingcrypt.ui.game_widgets import Cover
from gamingcrypt.ui.tasks import run_async
from gamingcrypt.ui.widgets import (FlowLayout, KeyboardFocusFilter, OnScreenKeyboard, big_button,
                                    enable_touch_scroll, set_status)
from gamingcrypt.ui.wine_pages import WindowsLibraryPage, load_windows_cover, played

NOT_INSTALLED = "Minecraft's launcher (portablemc) isn't installed yet - open the Minecraft library while online"


class _Bridge(QObject):
    """From portablemc's threads to the page."""
    code = Signal(str, str)
    done = Signal(bool, str)
    progress = Signal(float, str)


def account_text(account) -> str:
    return f"Signed in as {account.username}" if account is not None else "Not signed in"


class MinecraftLibraryPage(WindowsLibraryPage):
    """Every instance - and who's signed in."""

    KIND = "minecraft"
    TITLE = "Minecraft"
    EMPTY = ("No Minecraft yet. + New makes an instance: its own worlds and settings, with the Minecraft "
             "version you choose. Sign in with the Microsoft account that owns Minecraft: Java Edition first.")

    def __init__(self, tab, games: list, parent: QWidget | None = None):
        super().__init__(tab, games, parent)
        self.add_button.setText("+  New")
        row = QHBoxLayout()
        self.account_label = QLabel("")
        self.account_label.setObjectName("cardMeta")
        row.addWidget(self.account_label, 1)
        self.account_button = big_button("")
        self.account_button.clicked.connect(self.account_action)
        row.addWidget(self.account_button)
        self.layout().insertLayout(1, row)
        if portable.available():
            self.show_account()
        else:
            self.account_label.setText("Setting up Minecraft's launcher (portablemc)…")
            self.account_button.hide()
            self.add_button.setEnabled(False)
            run_async(portable.ensure, self._ensured, lambda exc: self._ensured((False, str(exc))), owner=self)

    def _ensured(self, result) -> None:
        ok, message = result
        if not ok:
            self.account_label.setText(message)
            return
        self.account_button.show()
        self.add_button.setEnabled(True)
        self.show_account()

    def on_return(self) -> None:
        """Back from signing in (or out)."""
        self.show_account()

    def show_account(self) -> None:
        if not portable.available():
            self.account_label.setText(NOT_INSTALLED)
            self.account_button.hide()
            self.add_button.setEnabled(False)
            return
        account = self.tab.minecraft_account()
        self.account_label.setText(account_text(account))
        self.account_button.setText("Sign out" if account is not None else "Sign in with Microsoft")
        self.account_button.setObjectName("" if account is not None else "primary")
        self.account_button.style().unpolish(self.account_button)
        self.account_button.style().polish(self.account_button)

    def account_action(self) -> None:
        account = self.tab.minecraft_account()
        if account is None:
            self.tab.open_minecraft_signin()
            return
        from gamingcrypt.ui.modal import ask

        ask(self, f"Sign out {account.username}? Minecraft can't be played until you sign in again.", "Sign out",
            lambda: self.sign_out(account))

    def sign_out(self, account) -> None:
        paths = self.tab.minecraft_paths()

        def done(_ok) -> None:
            self.tab.minecraft_accounts = None
            self.show_account()

        run_async(lambda: portable.forget(paths, account), done, lambda _e: done(False), owner=self)


class SignInPage(QWidget):
    """Microsoft's device code: scan (or open microsoft.com/link) on a phone, type in the code there."""

    def __init__(self, tab, parent: QWidget | None = None, login_factory=None):
        super().__init__(parent)
        self.tab = tab
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 16, 30, 20)
        top = QHBoxLayout()
        top.addWidget(tab.back_button())
        title = QLabel("Sign in to Minecraft")
        title.setObjectName("title")
        top.addWidget(title, 1)
        layout.addLayout(top)
        body = QHBoxLayout()
        body.setSpacing(36)
        self.qr = QLabel()
        self.qr.setFixedSize(260, 260)
        self.qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body.addWidget(self.qr, alignment=Qt.AlignmentFlag.AlignTop)
        info = QVBoxLayout()
        info.setSpacing(14)
        self.hint = QLabel("Asking Microsoft for a code…")
        self.hint.setWordWrap(True)
        info.addWidget(self.hint)
        self.code = QLabel("")
        self.code.setObjectName("detailTitle")
        self.code.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        info.addWidget(self.code)
        self.status = QLabel("")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        info.addWidget(self.status)
        self.cancel_button = big_button("Cancel")
        self.cancel_button.clicked.connect(tab.back)
        info.addWidget(self.cancel_button, alignment=Qt.AlignmentFlag.AlignLeft)
        info.addStretch()
        body.addLayout(info, 1)
        layout.addLayout(body, 1)
        self.bridge = _Bridge(self)
        self.bridge.code.connect(self.show_code)
        self.bridge.done.connect(self.finished)
        self.login = (login_factory or portable.Login)(tab.minecraft_paths(), self.bridge.code.emit,
                                                       self.bridge.done.emit)
        self.login.start()
        self.destroyed.connect(lambda _o=None, login=self.login: login.cancel())  # (closed: stop waiting)

    def show_code(self, link: str, code: str) -> None:
        from gamingcrypt.ui.qr import qr_pixmap

        self.hint.setText(f"On your phone: scan the code - or open {link.removeprefix('https://')} - and enter "
                          "this code there, then sign in with the Microsoft account that owns Minecraft: "
                          "Java Edition.")
        self.code.setText(code)
        pixmap = qr_pixmap(f"{link}?otc={code}", 260)  # (Microsoft fills the code in itself)
        if pixmap is not None:
            self.qr.setPixmap(pixmap)

    def finished(self, ok: bool, message: str) -> None:
        if not shiboken6.isValid(self):
            return
        if ok:
            self.tab.minecraft_accounts = None  # (looked up again: who it is)
            self.tab.back()
            self.tab.home.show_notice(f"✓ Minecraft: {account_text(self.tab.minecraft_account())}")
            return
        if message:
            set_status(self.status, message, error=True)
            self.cancel_button.setText("‹ Back")


class NewInstancePage(QWidget):
    """A name and a Minecraft version - its worlds and settings are its own."""

    def __init__(self, tab, parent: QWidget | None = None, versions=None, supported=None):
        super().__init__(parent)
        self.tab = tab
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 16, 30, 20)
        top = QHBoxLayout()
        top.addWidget(tab.back_button())
        title = QLabel("New Minecraft instance")
        title.setObjectName("title")
        top.addWidget(title, 1)
        layout.addLayout(top)
        card = QFrame()
        card.setObjectName("card")
        form = QVBoxLayout(card)
        form.setContentsMargins(22, 18, 22, 18)
        form.setSpacing(12)
        caption = QLabel("Name")
        caption.setObjectName("cardMeta")
        form.addWidget(caption)
        self.name = QLineEdit()
        self.name.setPlaceholderText("e.g. Survival")
        self.name.setText(self.free_name())
        form.addWidget(self.name)
        caption = QLabel("Minecraft version")
        caption.setObjectName("cardMeta")
        form.addWidget(caption)
        self.version = ComboBox()
        self.version.addItem("The newest release", LATEST)
        form.addWidget(self.version)
        self.releases: list[str] = []
        self.supported: set[str] | None = None  # (Controlify's versions, once known)
        self.controller_button = big_button("", checkable=True)
        self.controller_button.setChecked(True)
        self.controller_button.toggled.connect(self._controller_text)
        self.controller_button.toggled.connect(lambda _on: self.fill_versions())
        self._controller_text(True)
        form.addWidget(self.controller_button, alignment=Qt.AlignmentFlag.AlignLeft)
        self.controller_note = QLabel("The whole game with the controller - menus, inventory, chat with an "
                                      "on-screen keyboard (Fabric with Controlify and Sodium, from Modrinth). "
                                      "Only the versions Controlify is made for.")
        self.controller_note.setObjectName("cardMeta")
        self.controller_note.setWordWrap(True)
        form.addWidget(self.controller_note)
        note = QLabel("It stays on the version it's installed with - your worlds don't change by themselves.")
        note.setObjectName("cardMeta")
        note.setWordWrap(True)
        form.addWidget(note)
        self.create_button = big_button("+  Create", "primary")
        self.create_button.clicked.connect(self.create)
        form.addWidget(self.create_button, alignment=Qt.AlignmentFlag.AlignLeft)
        self.status = QLabel("")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        form.addWidget(self.status)
        layout.addWidget(card)
        layout.addStretch()
        self.keyboard = OnScreenKeyboard(self.name, compact=True)
        self.keyboard.submitted.connect(self.keyboard.hide)
        self.keyboard.dismissable = True
        self.keyboard.hide()
        self._focus_filter = KeyboardFocusFilter(self.keyboard, self)
        self._focus_filter.watch(self.name)
        layout.addWidget(self.keyboard)
        if portable.available():
            paths = tab.minecraft_paths()
            run_async(versions or (lambda: portable.releases(paths)), self.add_versions, lambda _e: None, owner=self)
            run_async(supported or mods.supported, self.set_supported, lambda _e: None, owner=self)

    def _controller_text(self, on: bool) -> None:
        self.controller_button.setText(f"{'☑' if on else '☐'}  Controller support")

    def free_name(self) -> str:
        taken = {g.name.casefold() for g in self.tab.minecraft_games}
        name, number = "Survival", 2
        while name.casefold() in taken:
            name, number = f"Survival {number}", number + 1
        return name

    def add_versions(self, found: list[str]) -> None:
        self.releases = list(found)
        self.fill_versions()

    def set_supported(self, found: set[str]) -> None:
        self.supported = set(found)
        self.fill_versions()

    def fill_versions(self) -> None:
        """Every release - with controller support the ones Controlify is made for (all until that's known)."""
        chosen = self.version.currentData()
        limit = self.supported if self.controller_button.isChecked() else None
        self.version.blockSignals(True)
        self.version.clear()
        self.version.addItem("The newest release", LATEST)
        for version in self.releases:
            if limit is None or version in limit:
                self.version.addItem(version, version)
        self.version.setCurrentIndex(max(0, self.version.findData(chosen)))
        self.version.blockSignals(False)

    def create(self) -> None:
        name = self.name.text().strip()
        if not name:
            set_status(self.status, "Give it a name", error=True)
            return
        root, version = self.tab.minecraft_root, self.version.currentData() or LATEST
        loader = FABRIC if self.controller_button.isChecked() else VANILLA
        self.create_button.setEnabled(False)

        def done(instance: MinecraftInstance) -> None:
            self.tab.back()
            self.tab.reload_minecraft()
            self.tab.open_minecraft_game(instance)

        def failed(exc: Exception) -> None:
            self.create_button.setEnabled(True)
            set_status(self.status, f"Could not create it: {exc}", error=True)

        run_async(lambda: library.create(root, name, version, loader), done, failed, owner=self)


class MinecraftInstancePage(QWidget):
    """An instance: Play (installs it the first time), Options - its version, remove; favorite."""

    def __init__(self, tab, game: MinecraftInstance, parent: QWidget | None = None, installer=installer.install):
        super().__init__(parent)
        self.tab, self.game, self.installer = tab, game, installer
        self.installing = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 16, 30, 20)
        top = QHBoxLayout()
        top.addWidget(tab.back_button())
        top.addStretch()
        layout.addLayout(top)
        body = QHBoxLayout()
        body.setSpacing(36)
        self.cover = Cover()
        self.cover.setFixedSize(300, 450)
        load_windows_cover(self.cover, game, None, 300, 450)
        body.addWidget(self.cover, alignment=Qt.AlignmentFlag.AlignTop)
        info = QVBoxLayout()
        info.setSpacing(14)
        self.title = QLabel(game.name)
        self.title.setObjectName("detailTitle")
        self.title.setWordWrap(True)
        info.addWidget(self.title)
        self.facts = QLabel()
        self.facts.setObjectName("detailMeta")
        self.facts.setWordWrap(True)
        info.addWidget(self.facts)
        self.actions = QWidget()
        actions = FlowLayout(self.actions, spacing=16)
        actions.setContentsMargins(0, 0, 0, 0)
        self.actions.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Maximum)
        self.main_button = big_button("▶  Play", "primary")
        self.main_button.setMinimumWidth(220)
        self.main_button.clicked.connect(self.play)
        actions.addWidget(self.main_button)
        self.options_button = big_button("⚙ Options", checkable=True)
        self.options_button.toggled.connect(self.toggle_options)
        actions.addWidget(self.options_button)
        self.favorite_button = big_button("", checkable=True)
        self.favorite_button.setChecked(tab.profiles.is_favorite(game.appid))
        self._favorite_text()
        self.favorite_button.toggled.connect(self.toggle_favorite)
        actions.addWidget(self.favorite_button)
        info.addWidget(self.actions)
        self.progress = QProgressBar()
        self.progress.setRange(0, 1000)
        self.progress.setTextVisible(False)
        self.progress.hide()
        info.addWidget(self.progress)
        self.status = QLabel("")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        self.status.hide()
        info.addWidget(self.status)
        self.options_panel = QFrame()
        self.options_panel.setObjectName("card")
        options = QVBoxLayout(self.options_panel)
        options.setContentsMargins(22, 18, 22, 18)
        options.setSpacing(12)
        self.folder_note = QLabel(f"Worlds, settings and resource packs: its own folder on the drive "
                                  f"(Minecraft/{library.INSTANCES}/{game.path.name})")
        self.folder_note.setObjectName("cardMeta")
        self.folder_note.setWordWrap(True)
        options.addWidget(self.folder_note)
        self.mods_button = big_button("🧩  Mods")
        self.mods_button.clicked.connect(self.open_mods)
        options.addWidget(self.mods_button, alignment=Qt.AlignmentFlag.AlignLeft)
        self.reinstall_button = big_button("⟳  Install again")
        self.reinstall_button.clicked.connect(self.reinstall)
        options.addWidget(self.reinstall_button, alignment=Qt.AlignmentFlag.AlignLeft)
        self.remove_button = big_button("🗑 Remove", "danger")
        self.remove_button.clicked.connect(self.ask_remove)
        self.remove_button.setVisible(getattr(tab, "can_delete", True))  # the admin's
        options.addWidget(self.remove_button, alignment=Qt.AlignmentFlag.AlignLeft)
        from gamingcrypt.ui.options_popup import options_popup

        self.options_popup = options_popup(self, self.options_panel, self.options_button, game.name)
        info.addStretch()
        body.addLayout(info, 1)
        content = QWidget()
        content.setLayout(body)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setWidget(content)
        enable_touch_scroll(self.scroll)
        layout.addWidget(self.scroll, 1)
        self.bridge = _Bridge(self)
        self.bridge.progress.connect(self.show_progress)
        self._show_facts()

    def _show_facts(self) -> None:
        game = self.game
        state = "installed" if game.installed else "installed on its first Play"
        self.facts.setText(f"{installer.describe(game)} · {state}\n{played(game)}")
        # (mods need Fabric - and the Minecraft version they're for, known once it's installed)
        self.mods_button.setVisible(game.controller and bool(game.installed and game.game_version))

    def _favorite_text(self) -> None:
        self.favorite_button.setText("★ Favorite" if self.favorite_button.isChecked() else "☆ Favorite")

    def toggle_favorite(self, on: bool) -> None:
        self._favorite_text()
        self.tab.profiles.set(self.game.appid, "favorite", True if on else None)
        home = getattr(self.tab, "home", None)
        if home is not None and hasattr(home, "update_favorites"):
            home.update_favorites()

    def toggle_options(self, on: bool) -> None:
        self.options_popup.set_open(on)

    def show_status(self, text: str, error: bool = False) -> None:
        set_status(self.status, text, error=error)
        self.status.setVisible(bool(text))

    # playing ----------------------------------------------------------------------------
    def play(self) -> None:
        if self.installing:
            return
        if not portable.available():
            self.show_status(NOT_INSTALLED, error=True)
            return
        if self.tab.minecraft_account() is None:
            self.show_status("Sign in with your Microsoft account first", error=True)
            self.tab.open_minecraft_signin()
            return
        if not self.game.installed:
            self.install(then_play=True)
            return
        self.start()

    def start(self) -> None:
        launcher = self.tab.minecraft_launcher
        ok, message = launcher(self.game) if launcher else (False, "Minecraft can't be started here")
        self.show_status(message, error=not ok)

    def install(self, then_play: bool = False) -> None:
        self.installing = True
        self.main_button.setEnabled(False)
        self.reinstall_button.setEnabled(False)
        self.progress.setValue(0)
        self.progress.show()
        self.show_status("Getting Minecraft ready - the first time takes a few minutes…")
        paths, game, installer = self.tab.minecraft_paths(), self.game, self.installer
        progress = self.bridge.progress.emit  # (from the worker thread)

        def done(result) -> None:
            ok, message, version = result
            self.installing = False
            self.main_button.setEnabled(True)
            self.reinstall_button.setEnabled(True)
            self.progress.hide()
            if not ok:
                self.show_status(message, error=True)
                return
            game.installed = version or game.version
            run_async(lambda: library.save(game), owner=self)  # (and its mods, its Minecraft version)
            self._show_facts()
            self.show_status("")
            if then_play:
                self.start()

        run_async(lambda: installer(paths, game, progress), done,
                  lambda exc: done((False, f"Installing didn't work: {exc}", "")), owner=self)

    def show_progress(self, fraction: float, text: str) -> None:
        self.progress.setValue(int(fraction * 1000))
        self.show_status(text)

    def open_mods(self) -> None:
        self.options_popup.set_open(False)
        page = ModsPage(self.tab, self.game)
        self.tab.push(page)
        page.search.setFocus()

    def reinstall(self) -> None:
        """Everything checked and downloaded again (a broken download) - the worlds stay."""
        self.options_popup.set_open(False)
        self.game.installed = ""
        self.install()

    # removing ---------------------------------------------------------------------------
    def ask_remove(self) -> None:
        from gamingcrypt.ui.modal import ask

        self.options_popup.set_open(False)
        ask(self, f"Really remove {self.game.name}? Its worlds are deleted from the drive too.", "🗑 Remove",
            self.remove)

    def remove(self) -> None:
        game = self.game

        def done(_r) -> None:
            self.tab.back()
            self.tab.reload_minecraft()
            self.tab.home.show_notice(f"{game.name} removed")

        run_async(lambda: library.remove(game), done,
                  lambda exc: self.show_status(f"Could not remove it: {exc}", error=True), owner=self)


class ModsPage(QWidget):
    """An instance's mods: the ones in its folder (remove), and any Fabric mod from Modrinth for its
    Minecraft version (search, add - with what it needs)."""

    def __init__(self, tab, game: MinecraftInstance, parent: QWidget | None = None, get=None, fetch=None):
        super().__init__(parent)
        self.tab, self.game = tab, game
        self.get, self.fetch = get or mods.get_json, fetch or mods.get_bytes
        self.folder = game.path / mods.MODS
        self.busy = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 16, 30, 10)
        top = QHBoxLayout()
        top.addWidget(tab.back_button())
        title = QLabel(f"Mods · {game.name}")
        title.setObjectName("title")
        top.addWidget(title, 1)
        layout.addLayout(top)
        search_row = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(f"🔍  Search Modrinth for Minecraft {game.game_version}")
        self.search.returnPressed.connect(self.run_search)
        search_row.addWidget(self.search, 1)
        self.search_button = big_button("Search")
        self.search_button.clicked.connect(self.run_search)
        search_row.addWidget(self.search_button)
        layout.addLayout(search_row)
        self.status = QLabel("")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        self.status.hide()
        layout.addWidget(self.status)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        enable_touch_scroll(scroll)
        content = QWidget()
        self.rows = QVBoxLayout(content)
        self.rows.setContentsMargins(0, 8, 0, 8)
        self.rows.setSpacing(10)
        self.installed_heading = QLabel("Installed")
        self.installed_heading.setObjectName("section")
        self.rows.addWidget(self.installed_heading)
        self.installed_box = QVBoxLayout()
        self.installed_box.setSpacing(10)
        self.rows.addLayout(self.installed_box)
        self.found_heading = QLabel("Popular on Modrinth")
        self.found_heading.setObjectName("section")
        self.rows.addWidget(self.found_heading)
        self.found_box = QVBoxLayout()
        self.found_box.setSpacing(10)
        self.rows.addLayout(self.found_box)
        self.rows.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        self.keyboard = OnScreenKeyboard(self.search, compact=True)
        self.keyboard.submitted.connect(lambda: (self.keyboard.hide(), self.run_search()))
        self.keyboard.dismissable = True
        self.keyboard.hide()
        self._focus_filter = KeyboardFocusFilter(self.keyboard, self)
        self._focus_filter.watch(self.search)
        layout.addWidget(self.keyboard)
        self.found: list = []
        self.show_installed()
        self.run_search()

    def show_status(self, text: str, error: bool = False) -> None:
        set_status(self.status, text, error=error)
        self.status.setVisible(bool(text))

    @staticmethod
    def _clear(box: QVBoxLayout) -> None:
        while box.count():
            item = box.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()

    def _row(self, title: str, meta: str, action: str, slot, danger: bool = False, enabled: bool = True) -> QFrame:
        row = QFrame()
        row.setObjectName("card")
        line = QHBoxLayout(row)
        line.setContentsMargins(18, 12, 18, 12)
        text = QVBoxLayout()
        name = QLabel(title)
        name.setObjectName("cardTitle")
        name.setWordWrap(True)
        text.addWidget(name)
        if meta:
            detail = QLabel(meta)
            detail.setObjectName("cardMeta")
            detail.setWordWrap(True)
            text.addWidget(detail)
        line.addLayout(text, 1)
        button = big_button(action, "danger" if danger else "")
        button.setEnabled(enabled)
        button.clicked.connect(slot)
        line.addWidget(button, alignment=Qt.AlignmentFlag.AlignVCenter)
        row.button = button
        return row

    # what's there -----------------------------------------------------------------------
    def show_installed(self) -> None:
        self._clear(self.installed_box)
        names = mods.installed(self.folder)
        for name in names:
            needed = name.lower().startswith(mods.CONTROLLER)
            meta = "for the controller" if needed else ("" if name in self.game.mods else "put there by hand")
            self.installed_box.addWidget(self._row(mods.friendly(name), meta, "🗑 Remove",
                                                   lambda _c=False, n=name: self.ask_remove(n)))
        if not names:
            empty = QLabel("No mods yet.")
            empty.setObjectName("cardMeta")
            self.installed_box.addWidget(empty)

    def ask_remove(self, name: str) -> None:
        from gamingcrypt.ui.modal import ask

        warning = " Without it there's no controller support." if name.lower().startswith(mods.CONTROLLER) else ""
        ask(self, f"Remove {mods.friendly(name)}?{warning}", "🗑 Remove", lambda: self.remove(name))

    def remove(self, name: str) -> None:
        self.game.mods = mods.remove(name, self.folder, self.game.mods)
        self.game.projects.pop(name, None)
        library.save(self.game)
        self.show_installed()
        self.show_found()
        self.show_status(f"{mods.friendly(name)} removed")

    # Modrinth ---------------------------------------------------------------------------
    def run_search(self) -> None:
        query, version, get = self.search.text(), self.game.game_version, self.get
        if not version:
            self.show_status("Play it once first - mods are for the Minecraft version it gets", error=True)
            return
        self.found_heading.setText(f'Found for "{query.strip()}"' if query.strip() else "Popular on Modrinth")
        self.show_status("Searching Modrinth…")
        run_async(lambda: mods.search(query, version, get), self._found,
                  lambda exc: self.show_status(f"Modrinth can't be reached - is the device online? ({exc})",
                                               error=True), owner=self)

    def _found(self, found: list) -> None:
        self.found = found
        self.show_status("" if found else "Nothing found for this Minecraft version")
        self.show_found()

    def show_found(self) -> None:
        self._clear(self.found_box)
        files = set(mods.installed(self.folder))
        have = {project for name, project in self.game.projects.items() if name in files}
        for mod in self.found:
            there = mod.project in have
            meta = f"{mod.description}\n{mod.author} · {mod.downloads:,} downloads".replace(",", ".")
            self.found_box.addWidget(self._row(mod.title, meta, "Installed" if there else "+  Add",
                                               lambda _c=False, m=mod: self.add(m), enabled=not there and not self.busy))

    def add(self, mod) -> None:
        if self.busy:
            return
        self.busy = True
        self.show_status(f"Adding {mod.title}…")
        self.show_found()
        game, folder, get, fetch = self.game, self.folder, self.get, self.fetch

        def done(files: list) -> None:
            self.busy = False
            game.mods = sorted(set(game.mods) | {f.filename for f in files}, key=str.casefold)
            game.projects.update({f.filename: f.project for f in files})
            library.save(game)
            self.show_installed()
            self.show_found()
            self.show_status(f"✓ {mod.title} added - it's there on the next start")

        def failed(exc: Exception) -> None:
            self.busy = False
            self.show_found()
            self.show_status(f"{mod.title} could not be added: {exc}", error=True)

        run_async(lambda: mods.add(mod.project, game.game_version, folder, get, fetch), done, failed, owner=self)
