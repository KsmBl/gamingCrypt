"""Games tab: search installed games, enter a source (Steam) and navigate deeper."""

from __future__ import annotations

import shiboken6
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit, QScrollArea, QStackedWidget, QVBoxLayout,
                               QWidget)

from gamingcrypt.steam.models import SteamGame
from gamingcrypt.steam.sorting import filter_games, sort_games
from gamingcrypt.ui.game_widgets import (Cover, GameCard, SourceCard, format_date, format_playtime, load_cover,
                                        placeholder_cover)
from gamingcrypt.ui.tasks import run_async
from gamingcrypt.ui.widgets import (
    FlowLayout,
    FoldingHeader,
    KeyboardFocusFilter,
    OnScreenKeyboard,
    big_button,
    enable_touch_scroll,
    focus_and_reveal,
    set_status,
)


# Libraries on the Games tab: id -> name (Settings -> Games -> Libraries hides them)
LIBRARIES = {"favorites": "Favorites", "steam": "Steam", "recent": "Recently played", "windows": "Windows games"}


def heading(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("section")  # the same headings everywhere
    return label


class ContinueCard(QFrame):
    """The game played last, right at the top: one tap to play on."""

    def __init__(self, tab: "GamesTab"):
        super().__init__()
        self.tab = tab
        self.game: SteamGame | None = None
        self.setObjectName("card")
        row = QHBoxLayout(self)
        row.setContentsMargins(18, 16, 18, 16)
        row.setSpacing(20)
        self.cover = Cover()
        self.cover.setFixedSize(150, 225)
        row.addWidget(self.cover)
        text = QVBoxLayout()
        caption = QLabel("Continue playing")
        caption.setObjectName("cardMeta")
        text.addWidget(caption)
        self.title = QLabel("")
        self.title.setObjectName("sourceTitle")
        self.title.setWordWrap(True)
        text.addWidget(self.title)
        self.meta = QLabel("")
        self.meta.setObjectName("cardMeta")
        text.addWidget(self.meta)
        text.addStretch()
        buttons = QHBoxLayout()
        self.play_button = big_button("▶  Play", "primary")
        self.play_button.setMinimumWidth(220)
        self.play_button.clicked.connect(self.play)
        self.details_button = big_button("Details")
        self.details_button.clicked.connect(self.details)
        buttons.addWidget(self.play_button)
        buttons.addWidget(self.details_button)
        buttons.addStretch()
        text.addLayout(buttons)
        row.addLayout(text, 1)

    @property
    def emulated(self) -> bool:
        from gamingcrypt.emulation.library import RomGame

        return isinstance(self.game, RomGame)

    @property
    def windows(self) -> bool:
        from gamingcrypt.wine.library import WindowsGame

        return isinstance(self.game, WindowsGame)

    def set_game(self, game) -> None:
        """A Steam game or an emulated one (RomGame)."""
        self.game = game
        self.setVisible(game is not None)
        if game is None:
            return
        self.title.setText(game.name)
        if self.windows:
            from gamingcrypt.ui.wine_pages import load_windows_cover

            self.meta.setText(f"Windows · last played {format_date(game.last_played)} · "
                              f"{format_playtime(game.minutes)}")
            load_windows_cover(self.cover, game, self.tab.windows_covers, 150, 225)
            return
        if self.emulated:
            from gamingcrypt.emulation.systems import short_name
            from gamingcrypt.ui.emulation_pages import load_rom_cover

            self.meta.setText(f"{short_name(game.system.id)} · last played {format_date(game.last_played)} · "
                              f"{format_playtime(game.minutes)}")
            load_rom_cover(self.cover, game, self.tab.covers, 150, 225)
            return
        self.meta.setText(f"Last played {format_date(game.last_played)} · {format_playtime(game.playtime_minutes)}")
        self.cover.setPixmap(placeholder_cover(game.name, 150, 225))
        load_cover(self.tab.service, game.appid, self.cover, 150, 225)

    def play(self) -> None:
        if self.game is None:
            return
        if self.windows:
            launcher = self.tab.windows_launcher
            ok, message = launcher(self.game) if launcher else (False, "Windows games can't be started here")
            if not ok:
                self.tab.home.show_notice(message, error=True)
            return
        if self.emulated:
            launcher = self.tab.rom_launcher
            ok, message = launcher(self.game) if launcher else (False, "RetroArch isn't set up yet")
            if not ok:
                self.tab.home.show_notice(message, error=True)
            return
        ok = self.tab.service.client.play(self.game.appid)
        if not ok:
            self.tab.home.show_notice("Could not reach Steam - is it installed?", error=True)

    def details(self) -> None:
        if self.game is None:
            return
        if self.windows:
            self.tab.open_windows_game(self.game)
        elif self.emulated:
            self.tab.open_rom(self.game)
        else:
            self.tab.open_game(self.game.appid)


COMPACT_FROM = 9  # more library cards than this: the small ones


def last_played(games: list[SteamGame], roms: list | None = None):
    """The game played last: installed Steam games and emulated ones."""
    played = [g for g in games if g.installed and g.last_played] + [r for r in roms or [] if r.last_played]
    return max(played, key=lambda g: g.last_played) if played else None


class GamesHome(QWidget):
    def __init__(self, tab: "GamesTab"):
        super().__init__()
        self.tab = tab
        self.installed: list[SteamGame] = []
        self.cards: dict[int, GameCard] = {}
        self.selected_appid: int | None = None
        self.result_appids: list[int] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 20, 30, 10)

        self.header = QWidget()
        header = QVBoxLayout(self.header)
        header.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.header)
        self.search = QLineEdit()
        self.search.setPlaceholderText("🔍  Search installed games")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self.refresh_results)
        header.addWidget(self.search)
        self.notice = QLabel("")
        self.notice.setObjectName("status")
        self.notice.setWordWrap(True)
        self.notice.hide()
        header.addWidget(self.notice)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        enable_touch_scroll(scroll)
        content = QWidget()
        self.content_layout = QVBoxLayout(content)
        self.content_layout.setContentsMargins(0, 10, 0, 10)

        self.continue_card = ContinueCard(tab)
        self.continue_card.hide()
        self.content_layout.addWidget(self.continue_card)
        self.sources_heading = heading("Libraries")
        self.content_layout.addWidget(self.sources_heading)
        self.sources = QWidget()
        sources = FlowLayout(self.sources, stretch=True)  # wraps: one card per emulated system can be many
        from gamingcrypt.ui import library_icons as icons

        self.favorites_card = SourceCard("Favorites", "Your starred games", icon=lambda w, h: icons.star(h))
        self.favorites_card.tapped.connect(tab.open_favorites)
        sources.addWidget(self.favorites_card)
        self.steam_card = SourceCard("Steam", "Your Steam library", icon=lambda w, h: icons.steam(h))
        self.steam_card.tapped.connect(tab.open_steam)
        sources.addWidget(self.steam_card)
        self.recent_card = SourceCard("Recently played", "Your last 10 games", icon=lambda w, h: icons.clock(h))
        self.recent_card.tapped.connect(tab.open_recent)
        sources.addWidget(self.recent_card)
        self.windows_card = SourceCard("Windows games", "Proton / Wine", icon=lambda w, h: icons.window(w, h))
        self.windows_card.tapped.connect(tab.open_windows_library)
        sources.addWidget(self.windows_card)
        self.add_card = SourceCard("⬆ Add ROMs", "Emulator games, cores, BIOS · over Wi-Fi")
        self.add_card.tapped.connect(tab.open_upload)
        self.add_card.setVisible(tab.emulation is not None)
        sources.addWidget(self.add_card)
        self.sources_row = sources
        self.system_cards: dict[str, SourceCard] = {}  # emulated systems with games
        self.content_layout.addWidget(self.sources)

        self.results_heading = heading("Installed games")
        self.content_layout.addWidget(self.results_heading)
        self.grid_widget = QWidget()
        self.grid = FlowLayout(self.grid_widget)
        self.content_layout.addWidget(self.grid_widget)
        self.empty_label = QLabel("")
        self.empty_label.setObjectName("subtitle")
        self.content_layout.addWidget(self.empty_label)
        self.content_layout.addStretch()
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        self.folding = FoldingHeader(scroll, self.header)

        self.keyboard = OnScreenKeyboard(self.search)
        self.keyboard.submitted.connect(self.keyboard.hide)
        self.keyboard.hide()
        self.keyboard.dismissable = True
        self._focus_filter = KeyboardFocusFilter(self.keyboard, self)
        self._focus_filter.watch(self.search)
        layout.addWidget(self.keyboard)

    def retheme(self) -> None:
        """Dark / light: the cards (covers without artwork are drawn) and icons again."""
        for card in self.cards.values():
            card.deleteLater()
        self.cards.clear()
        for card in self.library_cards().values():
            card._paint_icon()
        self.add_card._paint_icon()
        self.update_continue()
        self.refresh_results()

    def update_continue(self) -> None:
        roms = [game for games in self.tab.roms.values() for game in games] + list(self.tab.windows_games)
        self.continue_card.set_game(last_played(self.installed, roms))

    def library_cards(self) -> dict:
        cards = {"favorites": self.favorites_card, "steam": self.steam_card, "recent": self.recent_card}
        cards.update({f"emu:{sid}": card for sid, card in self.system_cards.items()})
        if self.tab.windows_root is not None:
            cards["windows"] = self.windows_card
        return cards

    def set_systems(self, found: dict) -> None:
        """One card per emulated system that has games (Emulation/roms/<system> on the drive)."""
        from gamingcrypt.emulation.systems import short_name

        for sid in list(self.system_cards):
            if sid not in found:
                self.system_cards.pop(sid).deleteLater()
        for sid, games in found.items():
            card = self.system_cards.get(sid)
            if card is None:
                from gamingcrypt.ui import library_icons as icons

                card = SourceCard(short_name(sid), "", icon=lambda w, h, s=sid: icons.console(s, w, h))
                card.tapped.connect(lambda s=sid: self.tab.open_system(s))
                self.system_cards[sid] = card
            card.subtitle.setText(f"{len(games)} game{'s' if len(games) != 1 else ''}")
        # order: Favorites, Steam, Recently played, the systems (as in SYSTEMS), Add ROMs last
        from gamingcrypt.emulation.systems import SYSTEMS

        self.sources_row.take_all()
        for card in [self.favorites_card, self.steam_card, self.recent_card, self.windows_card,
                     *(self.system_cards[s.id] for s in SYSTEMS if s.id in self.system_cards), self.add_card]:
            self.sources_row.addWidget(card)
        self.apply_libraries()

    def apply_libraries(self) -> None:
        """Only the libraries chosen in Settings; no heading when none is left."""
        hidden = set(self.tab.library_settings.get("hidden", []))
        self.windows_card.setVisible(False)  # (shown below when the drive has the folder)
        count = len(self.tab.windows_games)
        self.windows_card.subtitle.setText(f"{count} game{'s' if count != 1 else ''}" if count else "Proton / Wine")
        for key, card in self.library_cards().items():
            card.setVisible(key not in hidden)
        any_shown = any(key not in hidden for key in self.library_cards()) or self.add_card.isVisibleTo(self)
        shown = sum(key not in hidden for key in self.library_cards()) + (not self.add_card.isHidden())
        for card in [*self.library_cards().values(), self.add_card]:
            card.set_compact(shown > COMPACT_FROM)  # many libraries: smaller cards, five per row
        searching = bool(self.search.text().strip())
        self.sources.setVisible(any_shown and not searching)
        self.sources_heading.setVisible(any_shown and not searching)
        self.sources_row.invalidate()  # cards shown / hidden: new height

    def update_favorites(self) -> None:
        count = len(self.tab.profiles.favorites())
        self.favorites_card.subtitle.setText(f"{count} game{'s' if count != 1 else ''}" if count
                                             else "Your starred games")

    def remember_selection(self, appid: int) -> None:
        self.selected_appid = appid

    def show_notice(self, text: str, error: bool = False) -> None:
        set_status(self.notice, text, error=error)
        self.notice.setVisible(bool(text))

    def set_installed(self, games: list[SteamGame]) -> None:
        self.installed = sort_games([g for g in games if g.installed], "name")
        self.update_continue()
        self.update_favorites()
        self.refresh_results()

    def _card(self, game):
        """GameCard for an installed Steam game, RomCard (with its system) for an emulated one."""
        from gamingcrypt.emulation.library import RomGame

        from gamingcrypt.wine.library import WindowsGame

        if isinstance(game, WindowsGame):
            from gamingcrypt.ui.wine_pages import WindowsCard

            card = WindowsCard(game, covers=self.tab.windows_covers)
            card.meta.setText(f"Windows · {card.meta.text()}")
            card.clicked.connect(self.tab.open_windows_game)
            return card
        if isinstance(game, RomGame):
            from gamingcrypt.emulation.systems import short_name
            from gamingcrypt.ui.emulation_pages import RomCard

            card = RomCard(game, covers=self.tab.covers)
            card.meta.setText(f"{short_name(game.system.id)} · {card.meta.text()}")
            card.clicked.connect(self.tab.open_rom)
            return card
        card = GameCard(game, self.tab.service)
        card.clicked.connect(self.tab.open_game)
        return card

    def refresh_results(self) -> None:
        query = self.search.text()
        searching = bool(query.strip())
        self.apply_libraries()
        self.continue_card.setVisible(not searching and self.continue_card.game is not None)
        self.results_heading.setText(f'Results for "{query.strip()}"' if searching else "Installed games")
        words = query.casefold().split()
        roms = [g for games in [*self.tab.roms.values(), self.tab.windows_games] for g in games
                if all(w in g.name.casefold() for w in words)]
        # Steam games and emulated ones together, by name
        matches = sorted(filter_games(self.installed, query, installed_only=True) + roms,
                         key=lambda g: g.name.casefold())
        from gamingcrypt.ui.emulation_pages import RomCard
        from gamingcrypt.ui.wine_pages import WindowsCard

        focused = self.window().focusWidget() if self.window() else None
        if isinstance(focused, (GameCard, RomCard, WindowsCard)):
            self.selected_appid = focused.game.appid
        # cards are made once and only re-ordered: typing must stay fast
        for card in self.grid.take_all():
            card.hide()
        for game in matches:
            card = self.cards.get(game.appid)
            if card is None or card.game is not game:
                if card is not None:
                    card.deleteLater()
                card = self._card(game)
                self.cards[game.appid] = card
            self.grid.addWidget(card)
            card.show()
        self.grid.invalidate()
        self.result_appids = [g.appid for g in matches]
        card = self.cards.get(self.selected_appid) if self.selected_appid is not None else None
        if card is not None and card.isVisible() and isinstance(focused, (GameCard, RomCard, WindowsCard)):
            focus_and_reveal(card)  # hiding/re-adding cards must not lose the selection
        if matches:
            self.empty_label.setText("")
        elif searching:
            self.empty_label.setText("No installed game matches your search")
        else:
            self.empty_label.setText("No installed games found")


class GamesTab(QStackedWidget):
    """Navigation stack: home -> Steam library -> game details / store."""

    def __init__(self, service, library_path: str = "", parent: QWidget | None = None,
                 library_settings: dict | None = None, emulation_root: str = "", windows_root: str = ""):
        super().__init__(parent)
        self.service = service
        # shared with the config: Settings changes it, apply_libraries() shows it
        self.library_settings = library_settings if library_settings is not None else {"hidden": []}
        from gamingcrypt.emulation.library import EmulationPaths

        self.emulation = EmulationPaths(emulation_root) if emulation_root else None
        from gamingcrypt.emulation.covers import Covers

        self.covers = Covers(self.emulation) if self.emulation is not None else None  # box art
        from gamingcrypt.emulation.playtime import PlayLog

        self.play_log = PlayLog(self.emulation) if self.emulation is not None else None
        self.roms: dict = {}  # system id -> games
        # Windows games (Proton / Wine): a folder each in <drive>/Windows Games
        from pathlib import Path as _Path

        self.windows_root = _Path(windows_root) if windows_root else None
        self.windows_games: list = []
        self.windows_launcher = None  # set by the app: WindowsGame -> (ok, message)
        self._runners = None
        if self.windows_root is not None:
            from gamingcrypt.wine.covers import Covers as WindowsCovers

            self.windows_covers = WindowsCovers(self.windows_root)
        else:
            self.windows_covers = None
        self.rom_launcher = None  # set by the app: RomGame -> (ok, message)
        self.core_fetcher = None  # (paths, system, wanted) -> core path: downloads missing RetroArch cores
        self._fetching_cores = False
        self.upload_page_factory = None  # tests: a stand-in upload page
        self.layout_store = None  # set by the app: emulator controls (emulation/layouts.Store)
        self.games: dict[int, SteamGame] = {}
        self._came_from: list = []
        from gamingcrypt.game_profiles import GameProfiles

        self.profiles = GameProfiles()  # favorites, per-game power / FPS limit
        self.home = GamesHome(self)
        self.addWidget(self.home)
        self.reload_installed()
        if library_path:
            self.home.show_notice("Setting up your encrypted drive as Steam library…")
            run_async(lambda: self.service.ensure_library(library_path), self._library_checked,
                      lambda exc: self.home.show_notice(f"Could not set up the Steam library: {exc}", error=True),
                      owner=self)

    def _library_checked(self, result) -> None:
        if result.status == "added":
            self.home.show_notice("✓ " + result.message)
            self.reload_installed()
        elif result.status in ("failed", "no_steam"):
            self.home.show_notice(result.message, error=True)
        else:
            self.home.show_notice("")

    # navigation -------------------------------------------------------------
    def push(self, page: QWidget) -> None:
        # remember what was selected, so "back" can select it again
        self._came_from.append(self.window().focusWidget() if self.window() else None)
        self.addWidget(page)
        self.setCurrentWidget(page)

    def back(self) -> None:
        page = self.currentWidget()
        if page is self.home:
            return
        self.removeWidget(page)
        page.deleteLater()
        self.setCurrentIndex(self.count() - 1)
        current = self.currentWidget()
        previous = self._came_from.pop() if self._came_from else None
        if previous is not None and shiboken6.isValid(previous) and current.isAncestorOf(previous):
            if isinstance(previous, GameCard) and current is self.home:
                self.home.remember_selection(previous.game.appid)
            if previous.isVisible():
                focus_and_reveal(previous)
                # once more after the page's layout settled (it was hidden meanwhile)
                QTimer.singleShot(0, lambda w=previous: shiboken6.isValid(w) and w.isVisible()
                                  and focus_and_reveal(w))
        if hasattr(current, "on_return"):
            current.on_return()
        if current is self.home:
            self.reload_installed()

    def gamepad_back(self) -> bool:
        if self.currentWidget() is self.home:
            return False
        self.back()
        return True

    def back_button(self) -> QWidget:
        button = big_button("‹ Back")
        button.setProperty("back", True)  # not where a page should start (settle_focus)
        button.clicked.connect(self.back)
        return button

    # data -------------------------------------------------------------------
    def reload_installed(self) -> None:
        run_async(self.service.installed_games, self._installed_loaded, owner=self)
        self.reload_roms()

    def reload_roms(self) -> None:
        self.reload_windows()
        if self.emulation is None:
            return
        paths = self.emulation

        def work():
            import os

            from gamingcrypt.emulation.library import scan_all

            if os.path.ismount(paths.root.parent) and not paths.roms.exists():
                paths.ensure()  # first time on an unlocked drive: the folders to put things in
            return scan_all(paths)

        run_async(work, self._roms_loaded, lambda _e: None, owner=self)

    def _roms_loaded(self, found: dict) -> None:
        self.roms = found
        for games in found.values():
            if self.play_log is not None:
                self.play_log.apply(games)
            for game in games:
                self.rom_games[game.appid] = game
        self.home.set_systems(found)
        self.home.update_continue()
        self.home.refresh_results()  # emulated games are in "Installed games" too
        self.fetch_missing_cores(found)

    # Windows games -------------------------------------------------------------------------
    def reload_windows(self) -> None:
        root = self.windows_root
        if root is None:
            return

        def work():
            import os

            from gamingcrypt.wine.library import scan

            if not root.exists() and os.path.ismount(root.parent):
                root.mkdir(exist_ok=True)  # an unlocked drive: the folder to copy games into
            return scan(root, sizes=False)

        run_async(work, self._windows_loaded, lambda _e: None, owner=self)

    def _windows_loaded(self, games: list) -> None:
        for game in games:
            profile = self.profiles.get(game.appid)
            game.last_played, game.minutes = profile.get("last_played"), profile.get("minutes", 0)
        self.windows_games = games
        from gamingcrypt.ui.wine_pages import WindowsLibraryPage

        page = self.currentWidget()
        if isinstance(page, WindowsLibraryPage) and [g.appid for g in page.games] != [g.appid for g in games]:
            self.back()  # open again with what's there now
            self.open_windows_library()
        self.home.apply_libraries()
        self.home.update_continue()
        self.home.refresh_results()

    def windows_by_appid(self, appid: int):
        return next((g for g in self.windows_games if g.appid == appid), None)

    def windows_runners(self) -> list:
        """Every Proton and Wine (looked for once)."""
        if self._runners is None:
            from gamingcrypt.wine import runners

            self._runners = runners.available()
        return self._runners

    def open_windows_library(self) -> None:
        from gamingcrypt.ui.wine_pages import WindowsLibraryPage, first_card

        page = WindowsLibraryPage(self, self.windows_games)
        self.push(page)
        first_card(page)

    def open_windows_game(self, game) -> None:
        from gamingcrypt.ui.wine_pages import WindowsGamePage

        page = WindowsGamePage(self, game)
        self.push(page)
        page.main_button.setFocus()

    def open_windows_upload(self) -> None:
        from gamingcrypt.ui.wine_pages import WindowsUploadPage

        if self.windows_root is None:
            return
        page = (self.upload_page_factory or WindowsUploadPage)(self.windows_root)
        page.closed.connect(self._windows_upload_closed)
        self.push(page)

    def _windows_upload_closed(self) -> None:
        self.back()
        self.reload_windows()  # the library page below shows what was copied in (_windows_loaded)

    def fetch_missing_cores(self, found: dict) -> None:
        """Systems with games get their RetroArch core in the background (see emulation/cores)."""
        fetch, paths = self.core_fetcher, self.emulation
        if fetch is None or paths is None or self._fetching_cores:
            return  # (the next reload catches what a running fetch didn't know about)
        self._fetching_cores = True
        from gamingcrypt.emulation.systems import BY_ID

        systems = [BY_ID[sid] for sid, games in found.items()
                   if games and sid in BY_ID and BY_ID[sid].emulator == "retroarch"]  # Eden: when played

        def work():
            from gamingcrypt.emulation import cores

            return [s.id for s in cores.missing(paths, systems) if fetch(paths, s, None) is not None]

        run_async(work, self._cores_fetched, lambda _e: self._cores_fetched([]), owner=self)

    def _cores_fetched(self, system_ids: list) -> None:
        self._fetching_cores = False
        if system_ids:
            from gamingcrypt.emulation.systems import short_name

            self.home.show_notice("RetroArch cores downloaded for " + ", ".join(short_name(i) for i in system_ids))

    @property
    def rom_games(self) -> dict:
        if not hasattr(self, "_rom_games"):
            self._rom_games = {}
        return self._rom_games

    def open_system(self, system_id: str) -> None:
        from gamingcrypt.emulation.systems import BY_ID
        from gamingcrypt.ui.emulation_pages import SystemPage

        page = SystemPage(self, BY_ID[system_id], self.roms.get(system_id, []))
        self.push(page)
        from gamingcrypt.ui.widgets import settle_focus

        first = page.cards.get(page.shown[0]) if page.shown else None
        settle_focus(page, first or page.search)  # the first game, not "‹ Back"

    def open_upload(self) -> None:
        from gamingcrypt.ui.upload_page import UploadPage

        if self.emulation is None:
            return
        page = (self.upload_page_factory or UploadPage)(self.emulation)
        page.closed.connect(self._upload_closed)
        self.push(page)

    def open_controls(self, system_id: str) -> None:
        from gamingcrypt.ui.controls_page import ControlsPage

        if self.layout_store is None:
            return
        page = ControlsPage(self.layout_store, system_id)
        page.closed.connect(self.back)
        self.push(page)

    def _upload_closed(self) -> None:
        self.back()
        self.reload_roms()  # new games show up right away

    def open_rom(self, game) -> None:
        from gamingcrypt.ui.emulation_pages import RomGamePage

        page = RomGamePage(self, game)
        self.push(page)
        page.main_button.setFocus()

    def _installed_loaded(self, games: list[SteamGame]) -> None:
        for game in games:
            self.games[game.appid] = game
        self.home.set_installed(games)

    # entry points -----------------------------------------------------------
    def open_steam(self) -> None:
        from gamingcrypt.ui.steam_page import SteamLibraryPage

        self.push(SteamLibraryPage(self))

    def open_game(self, appid: int) -> None:
        from gamingcrypt.ui.game_detail import GameDetailPage

        game = self.games.get(appid)
        if game is not None:
            page = GameDetailPage(self, game)
            self.push(page)
            page.main_button.setFocus()  # Play / Download is the obvious next step

    def open_favorites(self) -> None:
        from gamingcrypt.ui.recent_page import FavoritesPage

        self.push(FavoritesPage(self))

    def open_recent(self) -> None:
        from gamingcrypt.ui.recent_page import RecentPage

        self.push(RecentPage(self))

    def open_store(self) -> None:
        from gamingcrypt.ui.store_page import StorePage

        page = StorePage(self)
        self.push(page)
        page.search.setFocus()  # ready to search: A opens the keyboard (it isn't up by itself)
