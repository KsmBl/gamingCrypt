"""Games tab: the Windows games library (Proton / Wine), a game's page and how games get there -
and the same for native Linux games (the Linux* classes at the end).

A game is a folder copied over the network share as it is (<drive>/Windows Games/<Game>);
its start file and what runs it (a Proton or a Wine) are chosen in its Options. The tab has the
same pieces per kind ("windows" / "linux"): <kind>_covers, <kind>_launcher, <kind>_runners(),
open_<kind>_game, open_<kind>_upload.
"""

from __future__ import annotations

from pathlib import Path

import shiboken6
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QScrollArea,
                               QSizePolicy, QVBoxLayout, QWidget)

from gamingcrypt.ui.game_widgets import (COVER_H, COVER_W, Cover, Tappable, card_margins, format_date,
                                        format_playtime, format_size, placeholder_cover)
from gamingcrypt.ui.movies_tab import MovieUploadPage
from gamingcrypt.ui.tasks import run_async
from gamingcrypt.ui.widgets import FlowLayout, big_button, enable_touch_scroll, set_status, settle_focus
from gamingcrypt.linux import library as linux_library
from gamingcrypt.wine import library
from gamingcrypt.wine.library import WindowsGame


def load_windows_cover(label: QLabel, game: WindowsGame, covers, w: int, h: int) -> None:
    """A drawn cover first; Steam's picture of the game when it's found."""
    label.setPixmap(placeholder_cover(game.name, w, h))
    if covers is None:
        return

    def show(path) -> None:
        if path is None or not shiboken6.isValid(label):
            return
        pixmap = QPixmap(str(path))
        if not pixmap.isNull():
            scaled = pixmap.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                   Qt.TransformationMode.SmoothTransformation)
            label.setPixmap(scaled.copy((scaled.width() - w) // 2, (scaled.height() - h) // 2, w, h))

    cached = covers.cached(game)
    if cached is not None:
        show(cached)
    else:
        run_async(lambda: covers.fetch(game), show, lambda _e: None)


def played(game: WindowsGame) -> str:
    return (f"Last played {format_date(game.last_played)} · {format_playtime(game.minutes)}" if game.last_played
            else "Never played")


class WindowsCard(Tappable):
    clicked = Signal(object)

    def __init__(self, game: WindowsGame, covers=None, parent: QWidget | None = None):
        super().__init__(parent)
        self.game = game
        self.setObjectName("card")
        self.setFixedWidth(COVER_W + 20)  # as big as every game's card
        layout = QVBoxLayout(self)
        card_margins(layout)
        layout.setSpacing(6)
        self.cover = Cover()
        self.cover.setFixedSize(COVER_W, COVER_H)
        load_windows_cover(self.cover, game, covers, COVER_W, COVER_H)
        layout.addWidget(self.cover)
        title = QLabel(game.name)
        title.setObjectName("cardTitle")
        title.setWordWrap(True)
        title.setFixedHeight(58)
        title.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(title)
        self.meta = QLabel(format_playtime(game.minutes))
        self.meta.setObjectName("cardMeta")
        layout.addWidget(self.meta)
        self.tapped.connect(lambda: self.clicked.emit(self.game))


class WindowsLibraryPage(QWidget):
    """Every Windows game, with search - and how to add one."""

    KIND = "windows"
    TITLE = "Windows games"
    EMPTY = ("No Windows games yet. Copy each game as a folder over the network share "
             "(⬆ Add games) - then pick its start file on its page.")

    def __init__(self, tab, games: list[WindowsGame], parent: QWidget | None = None):
        super().__init__(parent)
        self.tab, self.games = tab, games
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 16, 30, 10)
        top = QHBoxLayout()
        top.addWidget(tab.back_button())
        title = QLabel(self.TITLE)
        title.setObjectName("title")
        top.addWidget(title, 1)
        self.add_button = big_button("⬆  Add games")
        self.add_button.clicked.connect(getattr(tab, f"open_{self.KIND}_upload"))
        top.addWidget(self.add_button)
        layout.addLayout(top)
        self.search = QLineEdit()
        self.search.setPlaceholderText(f"🔍  Search {len(games)} games")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh)
        layout.addWidget(self.search)
        self.empty = QLabel(self.EMPTY)
        self.empty.setObjectName("subtitle")
        self.empty.setWordWrap(True)
        self.empty.setVisible(not games)
        layout.addWidget(self.empty)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        enable_touch_scroll(scroll)
        content = QWidget()
        self.grid = FlowLayout(content)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        self.cards: dict[int, WindowsCard] = {}
        for game in games:
            card = WindowsCard(game, covers=getattr(tab, f"{self.KIND}_covers", None))
            card.clicked.connect(getattr(tab, f"open_{self.KIND}_game"))
            self.cards[game.appid] = card
            self.grid.addWidget(card)
        self.shown: list[int] = [g.appid for g in games]

    def refresh(self) -> None:
        words = self.search.text().casefold().split()
        self.shown = []
        for game in self.games:
            visible = all(w in game.name.casefold() for w in words)
            self.cards[game.appid].setVisible(visible)
            if visible:
                self.shown.append(game.appid)
        self.grid.invalidate()


class RemoveWindowsConfirm(QFrame):
    """Really remove it? And its saves (the Wine prefix) too?"""

    removed = Signal(str)
    cancelled = Signal()

    def __init__(self, game: WindowsGame, parent: QWidget | None = None):
        super().__init__(parent)
        self.game = game
        self.setObjectName("card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        self.question = QLabel(f"Really remove {game.name}?\nIts folder is deleted from the drive.")
        self.question.setWordWrap(True)
        layout.addWidget(self.question)
        self.saves_button = big_button("", checkable=True)
        self.saves_button.toggled.connect(self._saves_text)
        self._saves_text(False)
        self.saves_button.setVisible(library.prefix_dir(game).exists())
        layout.addWidget(self.saves_button, alignment=Qt.AlignmentFlag.AlignLeft)
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
        self.saves_button.setText(f"{'☑' if on else '☐'}  Also delete its saves and settings (its Wine prefix)")

    def gamepad_back(self) -> bool:
        self.cancelled.emit()
        return True

    def confirm(self) -> None:
        self.remove_button.setEnabled(False)
        self.cancel_button.setEnabled(False)
        game, with_saves = self.game, self.saves_button.isChecked()

        def done(freed: int) -> None:
            kept = "" if with_saves or not self.saves_button.isVisible() else " - its saves are kept"
            self.removed.emit(f"{game.name} removed, {format_size(freed)} freed{kept}")

        run_async(lambda: library.remove(game, with_saves), done,
                  lambda exc: self.removed.emit(f"Could not remove it: {exc}"), owner=self)


class WindowsGamePage(QWidget):
    """A Windows game: Play; Options - start file, Proton / Wine, remove; favorite."""

    LIB = library  # what finds its start files
    NO_START_FILE = "No .exe file in its folder - copy the whole game folder over the network share"
    NO_RUNNER = "No Proton or Wine found"
    DIDNT_START = "It didn't start - see Options (start file, Proton / Wine)"

    def runs_text(self) -> str:
        return f"Runs with {self.runner_combo.currentText()}"

    def upscale_text(self) -> str:
        return self.upscale.facts()

    def saves_note(self) -> str:
        return (f"Saves and settings: its own Wine prefix on the drive "
                f"(Windows Games/{library.PREFIXES}/{self.game.path.name})")

    def __init__(self, tab, game: WindowsGame, parent: QWidget | None = None):
        super().__init__(parent)
        self.tab, self.game = tab, game
        self.confirm: RemoveWindowsConfirm | None = None
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
        load_windows_cover(self.cover, game, getattr(tab, f"{game.KIND}_covers", None), 300, 450)
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
        self.options_panel = QFrame()
        self.options_panel.setObjectName("card")
        options = QVBoxLayout(self.options_panel)
        options.setContentsMargins(22, 18, 22, 18)
        options.setSpacing(12)
        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setColumnStretch(1, 1)
        self.exe_combo = QComboBox()
        self.runner_combo = QComboBox()
        from gamingcrypt.ui.upscale_option import UpscaleOption

        self.upscale = UpscaleOption(tab.profiles, game.appid, lambda: self.screen_size(), lambda: self._show_facts())
        self.upscale_combo, self.upscale_note = self.upscale.combo, self.upscale.note
        for line, (caption, combo) in enumerate((("Start file", self.exe_combo), ("Runs with", self.runner_combo),
                                                 ("Upscaling", self.upscale_combo))):
            label = QLabel(caption)
            label.setObjectName("cardMeta")
            grid.addWidget(label, line, 0)
            grid.addWidget(combo, line, 1)
        options.addLayout(grid)
        options.addWidget(self.upscale_note)
        self.prefix_note = QLabel(self.saves_note())
        self.prefix_note.setObjectName("cardMeta")
        self.prefix_note.setWordWrap(True)
        options.addWidget(self.prefix_note)
        from gamingcrypt.ui.cover_picker import picture_button

        self.picture_button = picture_button(lambda: tab.open_cover_picker(self.game))
        options.addWidget(self.picture_button, alignment=Qt.AlignmentFlag.AlignLeft)
        self.remove_button = big_button("🗑 Remove", "danger")
        self.remove_button.clicked.connect(self.ask_remove)
        options.addWidget(self.remove_button, alignment=Qt.AlignmentFlag.AlignLeft)
        self.options_layout = options
        self.options_panel.hide()
        info.addWidget(self.options_panel)
        self.status = QLabel("")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        self.status.hide()
        info.addWidget(self.status)
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
        self.size = 0
        self.exe_combo.currentIndexChanged.connect(self.exe_chosen)
        self.runner_combo.currentIndexChanged.connect(self.runner_chosen)
        self._fill_runners()
        self._show_facts()
        run_async(lambda: (self.LIB.executables(game), library.folder_size(game.path)), self._scanned,
                  lambda _e: None, owner=self)

    # what's in the folder, what runs it -------------------------------------------------
    def _scanned(self, result) -> None:
        exes, self.size = result
        profile = self.tab.profiles.get(self.game.appid)
        chosen = profile.get("exe")
        self.exe_combo.blockSignals(True)
        self.exe_combo.clear()
        for rel in exes:
            self.exe_combo.addItem(rel, rel)
        if chosen and chosen not in exes:
            self.exe_combo.addItem(f"{chosen} (not there any more)", chosen)
        self.exe_combo.setCurrentIndex(max(0, self.exe_combo.findData(chosen)))
        self.exe_combo.blockSignals(False)
        if not exes:
            self.say(self.NO_START_FILE, error=True)
        elif not chosen:
            self.tab.profiles.set(self.game.appid, "exe", exes[0])  # the likeliest one, until another is picked
        self._show_facts()

    def _fill_runners(self) -> None:
        find = getattr(self.tab, f"{self.game.KIND}_runners", None)
        runners = find() if find is not None else []
        chosen = self.tab.profiles.get(self.game.appid).get("runner")
        self.runner_combo.blockSignals(True)
        self.runner_combo.clear()
        for runner in runners:
            self.runner_combo.addItem(runner.label, runner.id)
        if not runners:
            self.runner_combo.addItem(self.NO_RUNNER, None)
        self.runner_combo.setCurrentIndex(max(0, self.runner_combo.findData(chosen)))
        self.runner_combo.blockSignals(False)

    def screen_size(self) -> tuple[int, int]:
        from gamingcrypt.ui.upscale_option import screen_size_of

        return screen_size_of(self.tab if hasattr(self.tab, "window") else None)

    def _fill_upscaling(self) -> None:
        self.upscale.fill()

    def exe_chosen(self, _index: int) -> None:
        self.tab.profiles.set(self.game.appid, "exe", self.exe_combo.currentData())
        self._show_facts()

    def runner_chosen(self, _index: int) -> None:
        self.tab.profiles.set(self.game.appid, "runner", self.runner_combo.currentData())
        self._show_facts()

    def _show_facts(self) -> None:
        profile = self.tab.profiles.get(self.game.appid)
        game = self.game
        game.last_played = profile.get("last_played") or game.last_played
        game.minutes = profile.get("minutes", game.minutes)
        lines = [f"{game.LABEL} game", f"Starts {profile['exe']}" if profile.get("exe") else "",
                 self.runs_text(), self.upscale_text(), format_size(self.size) if self.size else "",
                 played(game)]
        self.facts.setText("\n".join(line for line in lines if line))

    # actions ----------------------------------------------------------------------------
    def play(self) -> None:
        launcher = getattr(self.tab, f"{self.game.KIND}_launcher", None)
        if launcher is None:
            self.say(f"{self.game.LABEL} games can't be started here", error=True)
            return
        ok, message = launcher(self.game)
        self.say("" if ok else message, error=not ok)

    def _favorite_text(self) -> None:
        self.favorite_button.setText("★ Favorite" if self.favorite_button.isChecked() else "☆ Favorite")

    def toggle_favorite(self, on: bool) -> None:
        self._favorite_text()
        self.tab.profiles.set(self.game.appid, "favorite", True if on else None)
        home = getattr(self.tab, "home", None)
        if home is not None and hasattr(home, "update_favorites"):
            home.update_favorites()  # the Favorites card's count

    def toggle_options(self, visible: bool) -> None:
        self.options_panel.setVisible(visible)
        if visible:
            QTimer.singleShot(0, lambda: self.scroll.ensureWidgetVisible(self.options_panel, 0, 20))
        else:
            self.close_confirm()

    def ask_remove(self) -> None:
        if self.confirm is not None:
            return
        self.confirm = RemoveWindowsConfirm(self.game)
        self.confirm.cancelled.connect(self.close_confirm)
        self.confirm.removed.connect(self.removed)
        self.options_layout.addWidget(self.confirm)
        self.confirm.show()
        self.remove_button.hide()
        self.confirm.cancel_button.setFocus()  # the safe choice first
        QTimer.singleShot(0, lambda: self.confirm is not None and self.scroll.ensureWidgetVisible(self.confirm, 0, 20))

    def close_confirm(self) -> None:
        if self.confirm is not None:
            self.confirm.deleteLater()
            self.confirm = None
            self.remove_button.show()
            self.remove_button.setFocus()

    def removed(self, message: str) -> None:
        self.tab.home.show_notice(message)
        self.tab.back()
        self.tab.reload_roms()

    def say(self, text: str, error: bool = False) -> None:
        set_status(self.status, text, error=error)
        self.status.setVisible(bool(text))

    def game_session_ended(self, appid: int, failed: bool) -> None:
        if appid == self.game.appid:
            self.say(self.DIDNT_START if failed else "", error=failed)
            self._show_facts()


class WindowsUploadPage(MovieUploadPage):
    TITLE = "Add Windows games"
    HINT = ("Copy a game as a whole folder over the network share (from a PC in the same Wi-Fi) into the "
            "Windows Games folder of your encrypted drive - one folder per game. Then open it here and pick "
            "its start file (.exe) and what runs it (a Proton or Wine) in its Options. Both ways work only "
            "while this page is open.")
    FOLDERS = ("Network share: the Windows Games folder - drop the game folders in · Browser: single files "
               "into a game you already have (e.g. a patch)")

    KIND = "windows"

    def __init__(self, root: Path, **kwargs):
        from gamingcrypt.emulation.upload_server import UploadServer

        kwargs.setdefault("server_factory", lambda folder, received: UploadServer(
            None, received, folders=lambda: upload_folders(folder, self.KIND)))
        super().__init__(Path(root), **kwargs)


def upload_folders(root: Path, kind: str = "windows") -> dict[str, tuple[str, Path]]:
    """Every game's folder (the browser can't make new folders: new games come over the share)."""
    games = linux_library.scan(root, sizes=False) if kind == "linux" else library.scan(root, sizes=False)
    return {f"{kind}/{g.path.name}": (f"Game: {g.name}", g.path) for g in games}


def first_card(page) -> None:
    """Library pages open on their first game."""
    if page.shown:
        settle_focus(page, page.cards.get(page.shown[0]))


# --- native Linux games: the same pages, without Proton / Wine ----------------------------------

class LinuxLibraryPage(WindowsLibraryPage):
    KIND = "linux"
    TITLE = "Linux games"
    EMPTY = ("No Linux games yet. Copy each game as a folder over the network share (⬆ Add games) - "
             "unpacked, e.g. from GOG, itch.io or Humble - then pick its start file on its page.")


class LinuxGamePage(WindowsGamePage):
    """A Linux game: Play; Options - start file, directly or in Steam's runtime, remove; favorite."""

    LIB = linux_library
    NO_START_FILE = ("No program or start script in its folder - copy the whole (unpacked) game folder over "
                     "the network share")
    NO_RUNNER = "Directly"
    DIDNT_START = "It didn't start - see Options (start file, Directly / Steam Runtime)"

    def runs_text(self) -> str:
        return "Runs directly" if self.runner_combo.currentData() in (None, "direct") else "Runs in Steam's runtime"

    def saves_note(self) -> str:
        return "Saves and settings: where the game keeps them - usually in your home folder (~/.local/share, ~/.config)"


class LinuxUploadPage(WindowsUploadPage):
    KIND = "linux"
    TITLE = "Add Linux games"
    HINT = ("Copy a game as a whole folder over the network share (from a PC in the same Wi-Fi) into the "
            "Linux Games folder of your encrypted drive - one folder per game, unpacked (GOG installers: "
            "install on a PC first, or unpack them). Then open it here and pick its start file (a program "
            "or .sh script) in its Options. Both ways work only while this page is open.")
    FOLDERS = ("Network share: the Linux Games folder - drop the game folders in · Browser: single files "
               "into a game you already have (e.g. a patch)")
