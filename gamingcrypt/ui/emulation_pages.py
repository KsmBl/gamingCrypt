"""Games tab: one library per emulated system, and the page of an emulated game."""

from __future__ import annotations

import shiboken6
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QScrollArea, QVBoxLayout,
                               QWidget)

from gamingcrypt.emulation.library import RomGame
from gamingcrypt.emulation.systems import System
from gamingcrypt.ui.game_widgets import COVER_H, COVER_W, format_size, placeholder_cover
from gamingcrypt.ui.widgets import FlowLayout, big_button, enable_touch_scroll, set_status

def load_rom_cover(label: QLabel, game: RomGame, covers, w: int, h: int) -> None:
    """Placeholder first; the box art from the drive's cache or libretro-thumbnails when it comes."""
    from PySide6.QtCore import Qt as _Qt
    from PySide6.QtGui import QPixmap

    from gamingcrypt.ui.tasks import run_async

    label.setPixmap(placeholder_cover(game.name, w, h))
    if covers is None:
        return

    def show(path) -> None:
        if path is None or not shiboken6.isValid(label):
            return
        pixmap = QPixmap(str(path))
        if not pixmap.isNull():
            label.setPixmap(pixmap.scaled(w, h, _Qt.AspectRatioMode.KeepAspectRatio,
                                          _Qt.TransformationMode.SmoothTransformation))

    cached = covers.cached(game)
    if cached is not None:
        show(cached)
    else:
        run_async(lambda: covers.fetch(game), show, lambda _e: None)


class RomCard(QFrame):
    clicked = Signal(object)

    def __init__(self, game: RomGame, parent: QWidget | None = None, covers=None):
        super().__init__(parent)
        self.game = game
        self.setObjectName("card")
        self.setFocusPolicy(Qt.FocusPolicy.TabFocus)
        self.setFixedWidth(COVER_W + 20)  # the same size as a Steam game's card
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 12)
        layout.setSpacing(6)
        self.cover = QLabel()
        self.cover.setFixedSize(COVER_W, COVER_H)
        self.cover.setAlignment(Qt.AlignmentFlag.AlignCenter)
        load_rom_cover(self.cover, game, covers, COVER_W, COVER_H)
        layout.addWidget(self.cover)
        title = QLabel(game.name)
        title.setObjectName("cardTitle")
        title.setWordWrap(True)
        title.setFixedHeight(58)
        title.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        layout.addWidget(title)
        self.meta = QLabel(format_size(game.size))
        self.meta.setObjectName("cardMeta")
        layout.addWidget(self.meta)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt API
        self.clicked.emit(self.game)
        super().mouseReleaseEvent(event)

    def gamepad_activate(self) -> bool:
        self.clicked.emit(self.game)
        return True


class SystemPage(QWidget):
    """All games of one system, with search."""

    def __init__(self, tab, system: System, games: list[RomGame], parent: QWidget | None = None):
        super().__init__(parent)
        self.tab, self.system, self.games = tab, system, games
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 16, 30, 10)
        top = QHBoxLayout()
        top.addWidget(tab.back_button())
        title = QLabel(system.name)
        title.setObjectName("title")
        top.addWidget(title, 1)
        self.controls_button = big_button("🕹  Controls")
        self.controls_button.clicked.connect(lambda: tab.open_controls(system.id))
        self.controls_button.setVisible(getattr(tab, "layout_store", None) is not None
                                        and system.emulator == "retroarch")  # Eden has its own
        top.addWidget(self.controls_button)
        self.add_button = big_button("⬆  Add ROMs")
        self.add_button.clicked.connect(tab.open_upload)
        top.addWidget(self.add_button)
        layout.addLayout(top)
        self.bios_note = QLabel("")
        self.bios_note.setObjectName("status")
        self.bios_note.setWordWrap(True)
        self.bios_note.hide()
        layout.addWidget(self.bios_note)
        if getattr(tab, "emulation", None) is not None:
            from gamingcrypt.emulation import bios

            status = bios.check(tab.emulation, system.id)
            if status is not None and status.state != "ok":
                set_status(self.bios_note, f"BIOS {status.describe()} - add it under bios (⬆ Add ROMs)",
                           error=status.problem)
                self.bios_note.show()
        self.search = QLineEdit()
        self.search.setPlaceholderText(f"🔍  Search {len(games)} games")
        self.search.textChanged.connect(self.refresh)
        layout.addWidget(self.search)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        enable_touch_scroll(scroll)
        content = QWidget()
        self.grid = FlowLayout(content)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        self.cards: dict[int, RomCard] = {}
        for game in games:
            card = RomCard(game, covers=getattr(tab, "covers", None))
            card.clicked.connect(tab.open_rom)
            self.cards[game.appid] = card
            self.grid.addWidget(card)
        self.shown: list[int] = [g.appid for g in games]

    def refresh(self) -> None:
        words = self.search.text().lower().split()
        self.shown = []
        for game in self.games:
            visible = all(w in game.name.lower() for w in words)
            self.cards[game.appid].setVisible(visible)
            if visible:
                self.shown.append(game.appid)
        self.grid.invalidate()


class RomGamePage(QWidget):
    """An emulated game: Play (RetroArch), favorite."""

    def __init__(self, tab, game: RomGame, parent: QWidget | None = None):
        super().__init__(parent)
        self.tab, self.game = tab, game
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 16, 30, 20)
        top = QHBoxLayout()
        top.addWidget(tab.back_button())
        top.addStretch()
        layout.addLayout(top)
        body = QHBoxLayout()
        body.setSpacing(36)
        self.cover = QLabel()
        self.cover.setFixedSize(300, 400)
        self.cover.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignHCenter)
        load_rom_cover(self.cover, game, getattr(tab, "covers", None), 300, 400)
        body.addWidget(self.cover, alignment=Qt.AlignmentFlag.AlignTop)
        info = QVBoxLayout()
        self.title = QLabel(game.name)
        self.title.setObjectName("detailTitle")
        self.title.setWordWrap(True)
        info.addWidget(self.title)
        from gamingcrypt.ui.game_widgets import format_date, format_playtime

        played = (f"Last played {format_date(game.last_played)} · {format_playtime(game.minutes)}"
                  if game.last_played else "Never played")
        files = f"{len(game.discs)} discs" if game.discs else game.path.name
        self.facts = QLabel(f"{game.system.name}\n{files}\n{format_size(game.size)}\n{played}")
        self.facts.setObjectName("detailMeta")
        info.addWidget(self.facts)
        info.addStretch()
        actions = QHBoxLayout()
        self.main_button = big_button("▶  Play", "primary")
        self.main_button.setMinimumWidth(260)
        self.main_button.clicked.connect(self.play)
        actions.addWidget(self.main_button)
        self.options_button = big_button("⚙ Options", checkable=True)  # as on a Steam game's page
        self.options_button.toggled.connect(self.toggle_options)
        actions.addWidget(self.options_button)
        self.favorite_button = big_button("", checkable=True)
        self.favorite_button.setChecked(tab.profiles.is_favorite(game.appid))
        self._favorite_text()
        self.favorite_button.toggled.connect(self.toggle_favorite)
        actions.addWidget(self.favorite_button)
        actions.addStretch()
        info.addLayout(actions)
        self.options_panel = QFrame()
        self.options_panel.setObjectName("card")
        options = QVBoxLayout(self.options_panel)
        options.setContentsMargins(22, 18, 22, 18)
        options.setSpacing(12)
        if game.system.emulator == "retroarch":
            options.addLayout(self._options())
        self.remove_button = big_button("🗑 Remove", "danger")
        self.remove_button.clicked.connect(self.ask_remove)
        options.addWidget(self.remove_button, alignment=Qt.AlignmentFlag.AlignLeft)
        self.options_layout = options
        self.confirm = None  # the "really remove?" question
        self.options_panel.hide()
        info.addWidget(self.options_panel)
        self.status = QLabel("")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        info.addWidget(self.status)
        body.addLayout(info, 1)
        # scrolls when the options don't fit (800 px high screens)
        content = QWidget()
        content.setLayout(body)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setWidget(content)
        enable_touch_scroll(self.scroll)
        layout.addWidget(self.scroll, 1)

    def toggle_options(self, visible: bool) -> None:
        self.options_panel.setVisible(visible)
        if visible:
            from PySide6.QtCore import QTimer

            QTimer.singleShot(0, lambda: self.scroll.ensureWidgetVisible(self.options_panel, 0, 20))
        else:
            self.close_confirm()

    def ask_remove(self) -> None:
        """Ask again - and whether the save states and memory card go too."""
        from gamingcrypt.ui.remove_rom import RemoveConfirm

        if self.confirm is not None or self.tab.emulation is None:
            return
        self.confirm = RemoveConfirm(self.tab.emulation, self.game)
        self.confirm.cancelled.connect(self.close_confirm)
        self.confirm.removed.connect(self.removed)
        self.options_layout.addWidget(self.confirm)
        self.confirm.show()
        self.remove_button.hide()
        self.confirm.cancel_button.setFocus()  # the safe choice first
        from PySide6.QtCore import QTimer

        QTimer.singleShot(0, lambda: self.scroll.ensureWidgetVisible(self.confirm, 0, 20))

    def close_confirm(self) -> None:
        if self.confirm is not None:
            self.confirm.deleteLater()
            self.confirm = None
            self.remove_button.show()
            self.remove_button.setFocus()

    def removed(self, message: str) -> None:
        self.tab.home.show_notice(message)
        self.tab.reload_roms()
        self.tab.back()  # the game is gone

    def _options(self) -> QGridLayout:
        """Core, memory card, and how slow / fast the quick menu's speeds are (from the next start)."""
        from PySide6.QtWidgets import QComboBox

        from gamingcrypt.emulation import layouts, retroarch

        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        profile = self.tab.profiles.get(self.game.appid)
        appid = self.game.appid

        def row(caption: str, combo: QComboBox) -> QLabel:
            label = QLabel(caption)
            label.setObjectName("cardMeta")
            line = grid.rowCount()
            grid.addWidget(label, line, 0)
            grid.addWidget(combo, line, 1, 1, 2)
            return label

        self.core_combo = QComboBox()
        cores = self.game.system.cores
        self.core_combo.addItem(f"Automatic ({layouts.CORE_NAMES.get(cores[0], cores[0])})", None)
        for core in cores:
            self.core_combo.addItem(layouts.CORE_NAMES.get(core, core), core)
        index = self.core_combo.findData(profile.get("core")) if profile.get("core") in cores else 0
        self.core_combo.setCurrentIndex(max(index, 0))
        row("Core", self.core_combo)
        self.card_combo = QComboBox()
        self.card_combo.addItem("Own card for this game", None)
        self.card_combo.addItem("One card for all games", "shared")
        self.card_combo.setCurrentIndex(1 if profile.get("memory_card") == "shared" else 0)
        self.card_caption = row("Memory card", self.card_combo)
        self.card_combo.currentIndexChanged.connect(
            lambda _i: self.tab.profiles.set(appid, "memory_card", self.card_combo.currentData()))

        def core_chosen(_index: int = 0) -> None:
            chosen = self.core_combo.currentData()
            self.tab.profiles.set(appid, "core", chosen)
            has_cards = (chosen or cores[0]) in retroarch.MEMORY_CARDS
            self.card_combo.setVisible(has_cards)
            self.card_caption.setVisible(has_cards)

        self.screen_combo = QComboBox()
        self.screen_combo.addItem("4:3 (as the console)", None)
        self.screen_combo.addItem("Widescreen 16:9 - set it in the game too", "16:9")
        self.screen_combo.setCurrentIndex(1 if profile.get("widescreen") == "16:9" else 0)
        self.screen_caption = row("Screen", self.screen_combo)
        self.screen_combo.currentIndexChanged.connect(
            lambda _i: self.tab.profiles.set(appid, "widescreen", self.screen_combo.currentData()))

        def core_chosen_screen() -> None:
            wide = (self.core_combo.currentData() or cores[0]) in retroarch.WIDESCREEN
            self.screen_combo.setVisible(wide)
            self.screen_caption.setVisible(wide)

        self.core_combo.currentIndexChanged.connect(core_chosen)
        self.core_combo.currentIndexChanged.connect(lambda _i: core_chosen_screen())
        core_chosen()
        core_chosen_screen()
        self.speed_combos = {}
        speeds = QHBoxLayout()
        for key, label, values, default in (("slow_speed", "Slow", retroarch.SLOW_SPEEDS, retroarch.DEFAULT_SLOW),
                                            ("fast_speed", "Fast", retroarch.FAST_SPEEDS, retroarch.DEFAULT_FAST)):
            combo = QComboBox()
            for value in values:
                combo.addItem(f"{label} {value:g}x", value)
            current = profile.get(key) if profile.get(key) in values else default
            combo.setCurrentIndex(values.index(current))
            combo.currentIndexChanged.connect(
                lambda _i, k=key, c=combo, d=default: self.tab.profiles.set(
                    appid, k, None if c.currentData() == d else c.currentData()))
            speeds.addWidget(combo)
            self.speed_combos[key] = combo
        caption = QLabel("Quick menu speeds")
        caption.setObjectName("cardMeta")
        line = grid.rowCount()
        grid.addWidget(caption, line, 0)
        grid.addLayout(speeds, line, 1, 1, 2)
        grid.setColumnStretch(3, 1)
        return grid

    def _favorite_text(self) -> None:
        self.favorite_button.setText("★ Favorite" if self.favorite_button.isChecked() else "☆ Favorite")

    def toggle_favorite(self, on: bool) -> None:
        self._favorite_text()
        self.tab.profiles.set(self.game.appid, "favorite", True if on else None)

    def play(self) -> None:
        launcher = getattr(self.tab, "rom_launcher", None)
        if launcher is None:
            set_status(self.status, "RetroArch isn't set up yet", error=True)
            return
        ok, message = launcher(self.game)
        set_status(self.status, message, error=not ok)

    def game_session_ended(self, appid: int, failed: bool) -> None:
        if appid == self.game.appid:
            set_status(self.status, "It didn't start - see the message above" if failed else "", error=failed)
