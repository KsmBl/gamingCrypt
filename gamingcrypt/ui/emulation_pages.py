"""Games tab: one library per emulated system, and the page of an emulated game."""

from __future__ import annotations

import shiboken6
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QLineEdit, QScrollArea, QVBoxLayout, QWidget

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
        self.facts = QLabel(f"{game.system.name}\n{game.path.name}\n{format_size(game.size)}\n{played}")
        self.facts.setObjectName("detailMeta")
        info.addWidget(self.facts)
        if game.system.emulator == "retroarch":
            info.addLayout(self._speed_options())
        info.addStretch()
        actions = QHBoxLayout()
        self.main_button = big_button("▶  Play", "primary")
        self.main_button.setMinimumWidth(260)
        self.main_button.clicked.connect(self.play)
        actions.addWidget(self.main_button)
        self.favorite_button = big_button("", checkable=True)
        self.favorite_button.setChecked(tab.profiles.is_favorite(game.appid))
        self._favorite_text()
        self.favorite_button.toggled.connect(self.toggle_favorite)
        actions.addWidget(self.favorite_button)
        actions.addStretch()
        info.addLayout(actions)
        self.status = QLabel("")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        info.addWidget(self.status)
        body.addLayout(info, 1)
        layout.addLayout(body, 1)

    def _speed_options(self) -> QHBoxLayout:
        """How fast "Fast" and how slow "Slow" are in the quick menu (from the next start)."""
        from PySide6.QtWidgets import QComboBox

        from gamingcrypt.emulation import retroarch

        row = QHBoxLayout()
        caption = QLabel("Quick menu speeds")
        caption.setObjectName("cardMeta")
        row.addWidget(caption)
        profile = self.tab.profiles.get(self.game.appid)
        self.speed_combos = {}
        for key, label, values, default in (("slow_speed", "Slow", retroarch.SLOW_SPEEDS, retroarch.DEFAULT_SLOW),
                                            ("fast_speed", "Fast", retroarch.FAST_SPEEDS, retroarch.DEFAULT_FAST)):
            combo = QComboBox()
            for value in values:
                combo.addItem(f"{label} {value:g}x", value)
            current = profile.get(key) if profile.get(key) in values else default
            combo.setCurrentIndex(values.index(current))
            combo.currentIndexChanged.connect(
                lambda _i, k=key, c=combo, d=default: self.tab.profiles.set(
                    self.game.appid, k, None if c.currentData() == d else c.currentData()))
            row.addWidget(combo)
            self.speed_combos[key] = combo
        row.addStretch()
        return row

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
