"""Settings -> Storage: what takes how much space, and freeing it with a tap."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QProgressBar, QVBoxLayout, QWidget

from gamingcrypt.steam import running, storage
from gamingcrypt.ui.game_widgets import format_size
from gamingcrypt.ui.tasks import run_async
from gamingcrypt.ui.widgets import big_button, set_status


class StoragePage(QWidget):
    roms_changed = Signal()  # an emulated game was removed: the Games tab rescans
    drives_changed = Signal()  # a stick was formatted: looked for again

    def __init__(self, service_fn: Callable[[], object], games_running: Callable[[], set] = running.running_appids,
                 parent: QWidget | None = None, emulation_fn: Callable[[], object] | None = None,
                 can_delete: Callable[[], bool] | None = None):
        super().__init__(parent)
        self.can_delete = can_delete or (lambda: True)  # deleting games is the admin's
        self.service_fn = service_fn
        self.emulation_fn = emulation_fn or (lambda: None)
        self.games_running = games_running
        self.report: storage.Report | None = None
        self.library_fn: Callable[[], object] = lambda: None  # set by the app: the Games tab (roots, drives)
        self.drives: list = []  # USB sticks, USB drives, SD cards that are in
        self.mover = None  # the Move question that's open
        self.formatter = None  # the Format question that's open
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        # USB sticks, USB drives, SD cards: how full, and formatting them
        self.drives_heading = QLabel("External drives")
        self.drives_heading.setObjectName("section")
        self.drives_heading.hide()
        layout.addWidget(self.drives_heading)
        self.drive_grid = QGridLayout()
        self.drive_grid.setColumnStretch(0, 1)
        layout.addLayout(self.drive_grid)
        self.drive_rows: dict = {}
        self.libraries = QVBoxLayout()
        layout.addLayout(self.libraries)
        row = QHBoxLayout()
        self.shaders_button = big_button("")
        self.shaders_button.clicked.connect(self.clear_all_shaders)
        self.leftovers_button = big_button("")
        self.leftovers_button.clicked.connect(self.clear_leftovers)
        self.rescan_button = big_button("↻")
        self.rescan_button.clicked.connect(self.refresh)
        for button in (self.shaders_button, self.leftovers_button):
            button.hide()
            row.addWidget(button)
        row.addStretch()
        row.addWidget(self.rescan_button)
        layout.addLayout(row)
        hint = QLabel("Shader caches are rebuilt when a game starts (it may stutter a little at first). "
                      "Save games are never deleted here.")
        hint.setObjectName("cardMeta")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.status = QLabel("")
        self.status.setObjectName("status")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.grid = QGridLayout()
        self.grid.setColumnStretch(0, 1)
        layout.addLayout(self.grid)
        self.rows: dict[int, list[QWidget]] = {}
        # emulated games (on the encrypted drive), removed after asking
        self.roms_heading = QLabel("Emulator games")
        self.roms_heading.setObjectName("section")
        self.roms_heading.hide()
        layout.addWidget(self.roms_heading)
        self.rom_grid = QGridLayout()
        self.rom_grid.setColumnStretch(0, 1)
        layout.addLayout(self.rom_grid)
        self.rom_rows: dict[int, list[QWidget]] = {}
        # Windows and Linux games (outside Steam): moved onto a stick and back
        self.pc_heading = QLabel("Windows and Linux games")
        self.pc_heading.setObjectName("section")
        self.pc_heading.hide()
        layout.addWidget(self.pc_heading)
        self.pc_grid = QGridLayout()
        self.pc_grid.setColumnStretch(0, 1)
        layout.addLayout(self.pc_grid)
        self.pc_rows: dict[int, list[QWidget]] = {}
        self.confirm = None
        self.busy = False
        self.message = ""  # result of the last action, shown after the rescan

    # scanning -----------------------------------------------------------------------------
    def refresh(self) -> None:
        if self.busy:
            return
        self.show_drives()
        self.refresh_roms()
        self.refresh_pc()
        service = self.service_fn()
        if service is None:
            set_status(self.status, "Steam wasn't found", error=True)
            return
        self.busy = True
        set_status(self.status, "Measuring…")
        run_async(lambda: storage.scan(service.root), self.show_report,
                  lambda exc: self._failed(str(exc)), owner=self)

    def show_report(self, report: storage.Report) -> None:
        self.busy = False
        self.report = report
        set_status(self.status, self.message or ("" if report.libraries else "No Steam library found"))
        self.message = ""
        _clear(self.libraries)
        for lib in report.libraries:
            line = QHBoxLayout()
            label = QLabel(f"{lib.path}  ·  {format_size(lib.free)} free of {format_size(lib.total)}")
            label.setObjectName("detailMeta")
            bar = QProgressBar()
            bar.setRange(0, 1000)
            bar.setValue(round(1000 * (lib.total - lib.free) / lib.total) if lib.total else 0)
            bar.setTextVisible(False)
            line.addWidget(label, 1)
            line.addWidget(bar, 1)
            self.libraries.addLayout(line)
        self.shaders_button.setText(f"Clear all shader caches ({format_size(report.shader_bytes)})")
        self.shaders_button.setVisible(report.shader_bytes > 0)
        self.leftovers_button.setText(f"Delete cancelled downloads ({format_size(report.leftover_bytes)})")
        self.leftovers_button.setVisible(bool(report.leftovers))
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.rows = {}
        for row, game in enumerate(report.games):
            text = QLabel(f"{game.name}\n{format_size(game.game_bytes)}"
                          + (f"  ·  shaders {format_size(game.shader_bytes)}" if game.shader_bytes else ""))
            shaders = big_button("Clear shaders")
            shaders.setVisible(game.shader_bytes > 0)
            shaders.clicked.connect(lambda _c=False, g=game: self.clear_shaders(g))
            remove = big_button("🗑 Uninstall", "danger")
            remove.clicked.connect(lambda _c=False, g=game: self.uninstall(g))
            self.grid.addWidget(text, row, 0)
            self.grid.addWidget(shaders, row, 1)
            self.grid.addWidget(remove, row, 2)
            if not self.can_delete():
                remove.hide()  # deleting games is the admin's
            self.rows[game.appid] = [text, shaders, remove]

    # emulated games ---------------------------------------------------------------------------
    def refresh_roms(self) -> None:
        paths = self.emulation_fn()
        if paths is None:
            return
        drives = tuple(self.drives)

        def work():
            from gamingcrypt.emulation import removal
            from gamingcrypt.emulation.library import scan_all

            games = [g for found in scan_all(paths, drives).values() for g in found]
            return [(g, removal.plan(paths, g)) for g in sorted(games, key=lambda g: -g.size)]

        run_async(work, self.show_roms, lambda _e: None, owner=self)

    def show_roms(self, games: list) -> None:
        from gamingcrypt.emulation.systems import short_name

        self.close_confirm()
        while self.rom_grid.count():
            item = self.rom_grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.rom_rows = {}
        self.roms_heading.setVisible(bool(games))
        for row, (game, plan) in enumerate(games):
            saves = f"  ·  saves {format_size(plan.saves_size)}" if plan.saves else ""
            text = QLabel(f"{game.name}\n{short_name(game.system.id)}  ·  {format_size(plan.files_size)}{saves}"
                          f"{self.where(game)}")
            move = self.move_button(game)
            remove = big_button("🗑 Remove", "danger")
            remove.clicked.connect(lambda _c=False, g=game, r=row: self.ask_remove(g, r))
            self.rom_grid.addWidget(text, row * 2, 0)
            self.rom_grid.addWidget(move, row * 2, 1)
            self.rom_grid.addWidget(remove, row * 2, 2)
            if not self.can_delete():
                remove.hide()
            self.rom_rows[game.appid] = [text, remove, move]

    def ask_remove(self, game, row: int) -> None:
        """The same question as on the game's page: really? and the saves too?"""
        from gamingcrypt.ui.remove_rom import RemoveConfirm

        if not self.can_delete():
            return
        if game.appid in self.games_running():
            set_status(self.status, "Close the game first", error=True)
            return
        self.close_confirm()
        self.confirm = RemoveConfirm(self.emulation_fn(), game)
        self.confirm.cancelled.connect(self.close_confirm)
        self.confirm.removed.connect(self._rom_removed)
        self.rom_grid.addWidget(self.confirm, row * 2 + 1, 0, 1, 3)  # right below its line
        self.confirm.show()
        self.confirm.cancel_button.setFocus()

    def close_confirm(self) -> None:
        if self.confirm is not None:
            self.confirm.deleteLater()
            self.confirm = None

    def _rom_removed(self, message: str) -> None:
        set_status(self.status, message)
        self.close_confirm()
        self.roms_changed.emit()
        self.refresh_roms()

    # where a game is ---------------------------------------------------------------------------
    def where(self, game) -> str:
        """"  ·  on GAMES" for a game on a stick."""
        from gamingcrypt import moving

        drive = next((d for d in self.drives if moving.is_on(game, d)), None) if game.removable else None
        return f"  ·  on {drive.name}" if drive is not None else ""

    def move_button(self, game) -> QWidget:
        from gamingcrypt import moving

        button = big_button("⇄ Move to…")
        button.clicked.connect(lambda _c=False, g=game: self.ask_move(g))
        button.setVisible(self.can_delete() and bool(moving.places(game, self.drives, self.emulation_fn())))
        return button

    def ask_move(self, game) -> None:
        from gamingcrypt import moving
        from gamingcrypt.ui.modal import show_modal
        from gamingcrypt.ui.move_game import MoveGame

        if self.mover is not None or not self.can_delete():
            return
        emulation = self.emulation_fn()
        self.mover = MoveGame(game, moving.places(game, self.drives, emulation), emulation)
        self.mover.cancelled.connect(self.close_move)
        self.mover.moved.connect(self._moved)
        self.mover.failed.connect(lambda message: (self.close_move(), set_status(self.status, message, error=True)))
        self.mover_modal = show_modal(self, self.mover, self.close_move)
        self.mover.focus_first()

    def close_move(self) -> None:
        if self.mover is None:
            return
        if self.mover.moving:
            self.mover.cancel()
            return
        self.mover = None
        self.mover_modal.close_modal()

    def _moved(self, message: str) -> None:
        self.close_move()
        set_status(self.status, message)
        self.roms_changed.emit()  # (the Games tab looks again: every library)
        self.refresh_roms()
        self.refresh_pc()
        self.show_drives()

    # Windows and Linux games ------------------------------------------------------------------
    def refresh_pc(self) -> None:
        tab = self.library_fn()
        roots = [(getattr(tab, "windows_root", None), "windows"), (getattr(tab, "linux_root", None), "linux")]
        if not any(root for root, _kind in roots):
            return
        drives = tuple(self.drives)

        def work():
            from gamingcrypt.linux import library as linux
            from gamingcrypt.wine import library as wine

            games = []
            for root, kind in roots:
                if root is not None:
                    games += (linux.scan(root, drives=drives) if kind == "linux" else wine.scan(root, drives=drives))
            return sorted(games, key=lambda g: -g.size)

        run_async(work, self.show_pc, lambda _e: None, owner=self)

    def show_pc(self, games: list) -> None:
        _clear(self.pc_grid)
        self.pc_rows = {}
        self.pc_heading.setVisible(bool(games))
        for row, game in enumerate(games):
            text = QLabel(f"{game.name}\n{game.LABEL}  ·  {format_size(game.size)}{self.where(game)}")
            move = self.move_button(game)
            self.pc_grid.addWidget(text, row, 0)
            self.pc_grid.addWidget(move, row, 1)
            self.pc_rows[game.appid] = [text, move]

    # USB sticks, USB drives, SD cards ----------------------------------------------------------
    def set_drives(self, drives: list) -> None:
        """Put in / taken out (the app looks every few seconds): shown, and the games on them."""
        if list(drives) == self.drives:
            return
        self.drives = list(drives)
        self.show_drives()
        if self.isVisible():
            self.refresh_roms()
            self.refresh_pc()

    def show_drives(self) -> None:
        import shutil

        from gamingcrypt.system.removable import LABELS

        _clear(self.drive_grid)
        self.drive_rows = {}
        self.drives_heading.setVisible(bool(self.drives))
        for row, drive in enumerate(self.drives):
            try:
                usage = shutil.disk_usage(drive.mount)
                space = f"{format_size(usage.free)} free of {format_size(usage.total)}"
                used = round(1000 * (usage.total - usage.free) / usage.total) if usage.total else 0
            except OSError:
                space, used = "", 0
            what = "  ·  ".join(x for x in (LABELS[drive.kind], drive.fstype, space) if x)
            text = QLabel(f"{drive.name}\n{what}")
            bar = QProgressBar()
            bar.setRange(0, 1000)
            bar.setValue(used)
            bar.setTextVisible(False)
            button = big_button("⚠ Format…", "danger")
            button.clicked.connect(lambda _c=False, d=drive: self.ask_format(d))
            button.setVisible(self.can_delete())  # deleting everything on it: the admin's
            self.drive_grid.addWidget(text, row, 0)
            self.drive_grid.addWidget(bar, row, 1)
            self.drive_grid.addWidget(button, row, 2)
            self.drive_rows[drive] = [text, bar, button]

    def ask_format(self, drive) -> None:
        from gamingcrypt.ui.format_drive import FormatConfirm
        from gamingcrypt.ui.modal import show_modal

        if self.formatter is not None or not self.can_delete():
            return
        self.formatter = FormatConfirm(drive)
        self.formatter.cancelled.connect(self.close_format)
        self.formatter.formatted.connect(self._formatted)
        self.formatter.failed.connect(lambda message: (self.close_format(), set_status(self.status, message,
                                                                                       error=True)))
        self.formatter_modal = show_modal(self, self.formatter, self.close_format)
        self.formatter.focus_first()

    def close_format(self) -> None:
        if self.formatter is None or self.formatter.working:
            return  # (formatting can't be stopped half way)
        self.formatter = None
        self.formatter_modal.close_modal()

    def _formatted(self, message: str) -> None:
        self.close_format()
        set_status(self.status, message)
        self.drives_changed.emit()
        self.roms_changed.emit()

    # freeing space --------------------------------------------------------------------------
    def _game_running(self) -> bool:
        if self.games_running():
            set_status(self.status, "Close your game first", error=True)
            return True
        return False

    def clear_shaders(self, game: storage.GameSpace) -> None:
        if self._game_running():
            return
        self._work(lambda: storage.clear_shader_cache(game), lambda freed: f"Freed {format_size(freed)}")

    def clear_all_shaders(self) -> None:
        if self.report is None or self._game_running():
            return
        games = list(self.report.games)
        self._work(lambda: sum(storage.clear_shader_cache(g) for g in games), lambda f: f"Freed {format_size(f)}")

    def clear_leftovers(self) -> None:
        if self.report is None or self._game_running():
            return
        report = self.report
        self._work(lambda: storage.clear_leftovers(report), lambda f: f"Freed {format_size(f)}")

    def uninstall(self, game: storage.GameSpace) -> None:
        if not self.can_delete():
            return
        from gamingcrypt.ui.modal import ask

        ask(self.window(), f"Uninstall {game.name}?\nIts game files are deleted from the drive "
                           f"({format_size(game.game_bytes)}). Save games in its Proton folder stay.",
            "🗑  Uninstall", lambda: self.uninstall_now(game))

    def uninstall_now(self, game: storage.GameSpace) -> None:
        if self._game_running():
            return
        service = self.service_fn()
        self._work(lambda: service.uninstall_game(game.appid),
                   lambda r: (f"{game.name} uninstalled" if r.ok else r.message))

    def _work(self, action, describe) -> None:
        self.busy = True
        set_status(self.status, "Working…")
        run_async(action, lambda result: self._done(describe(result)), lambda exc: self._failed(str(exc)),
                  owner=self)

    def _done(self, message: str) -> None:
        self.busy = False
        self.message = message
        self.refresh()

    def _failed(self, message: str) -> None:
        self.busy = False
        set_status(self.status, message, error=True)


def _clear(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        if item.widget():
            item.widget().deleteLater()
        elif item.layout():
            _clear(item.layout())
