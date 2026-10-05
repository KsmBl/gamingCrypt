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

    def __init__(self, service_fn: Callable[[], object], games_running: Callable[[], set] = running.running_appids,
                 parent: QWidget | None = None, emulation_fn: Callable[[], object] | None = None):
        super().__init__(parent)
        self.service_fn = service_fn
        self.emulation_fn = emulation_fn or (lambda: None)
        self.games_running = games_running
        self.report: storage.Report | None = None
        self.armed: int | None = None  # uninstall needs a second tap
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
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
        self.confirm = None
        self.busy = False
        self.message = ""  # result of the last action, shown after the rescan

    # scanning -----------------------------------------------------------------------------
    def refresh(self) -> None:
        if self.busy:
            return
        self.refresh_roms()
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
        self.armed = None
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
            self.rows[game.appid] = [text, shaders, remove]

    # emulated games ---------------------------------------------------------------------------
    def refresh_roms(self) -> None:
        paths = self.emulation_fn()
        if paths is None:
            return

        def work():
            from gamingcrypt.emulation import removal
            from gamingcrypt.emulation.library import scan_all

            games = [g for found in scan_all(paths).values() for g in found]
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
            text = QLabel(f"{game.name}\n{short_name(game.system.id)}  ·  {format_size(plan.files_size)}{saves}")
            remove = big_button("🗑 Remove", "danger")
            remove.clicked.connect(lambda _c=False, g=game, r=row: self.ask_remove(g, r))
            self.rom_grid.addWidget(text, row * 2, 0)
            self.rom_grid.addWidget(remove, row * 2, 2)
            self.rom_rows[game.appid] = [text, remove]

    def ask_remove(self, game, row: int) -> None:
        """The same question as on the game's page: really? and the saves too?"""
        from gamingcrypt.ui.remove_rom import RemoveConfirm

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
        if self.armed != game.appid:
            self.armed = game.appid
            self.rows[game.appid][2].setText("Tap again to uninstall")
            return
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
