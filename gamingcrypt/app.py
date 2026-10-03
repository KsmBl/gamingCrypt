"""Application entry point: setup / lock screen -> main shell."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Callable

from PySide6.QtWidgets import QApplication, QMainWindow, QStackedWidget, QWidget

from gamingcrypt import config as config_mod
from gamingcrypt.ui import theme
from gamingcrypt.ui.auth_setup import AuthSetupWizard
from gamingcrypt.ui.lock_screen import LockScreen
from gamingcrypt.ui.settings_tab import SettingsTab
from gamingcrypt.ui.shell import Shell
from gamingcrypt.unlock.veracrypt import VeraCryptUnlocker


class MainWindow(QMainWindow):
    def __init__(
        self,
        config: dict,
        save: Callable[[dict], None],
        unlocker_factory=VeraCryptUnlocker.from_config,
        page_factory: Callable[[dict], dict[str, QWidget]] | None = None,
    ):
        super().__init__()
        self.setWindowTitle("GamingCrypt")
        self.config = config
        self.save = save
        self.unlocker_factory = unlocker_factory
        self.page_factory = page_factory
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)
        self.shell: Shell | None = None
        unlock = config["unlock"]
        if not unlock.get("method") or not unlock.get("volume"):
            self.show_setup()
        else:
            self.show_lock()

    def _replace(self, widget: QWidget) -> None:
        old = self.stack.currentWidget()
        self.stack.addWidget(widget)
        self.stack.setCurrentWidget(widget)
        if old is not None:
            self.stack.removeWidget(old)
            old.deleteLater()

    def show_setup(self) -> None:
        wizard = AuthSetupWizard(self.config, self.save, self.unlocker_factory, first_start=True)
        wizard.completed.connect(self.show_lock)
        wizard.cancelled.connect(self.show_shell)
        self._replace(wizard)
        self.screen_name = "setup"

    def show_lock(self) -> None:
        lock = LockScreen(self.unlocker_factory(self.config["unlock"]), self.config["unlock"]["method"])
        lock.unlocked.connect(self.show_shell)
        self._replace(lock)
        self.screen_name = "lock"

    def show_shell(self) -> None:
        pages = self.page_factory(self.config) if self.page_factory else {}
        pages.setdefault("Settings", SettingsTab(self.config, self.save, self.unlocker_factory))
        self.shell = Shell(pages)
        self.shell.exit_requested.connect(self.close)
        self._replace(self.shell)
        self.screen_name = "shell"


def default_pages(config: dict) -> dict[str, QWidget]:
    from gamingcrypt.steam.service import SteamService
    from gamingcrypt.ui.games_tab import GamesTab

    service = SteamService(config["steam"], config_mod.cache_dir())
    return {"Games": GamesTab(service)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gamingcrypt", description=__doc__)
    parser.add_argument("--windowed", action="store_true", help="don't start in fullscreen")
    parser.add_argument("--config", type=Path, help="path to config.json")
    args, qt_args = parser.parse_known_args(argv if argv is not None else sys.argv[1:])

    cfg_path = args.config or config_mod.config_path()
    cfg = config_mod.load_config(cfg_path)

    app = QApplication([sys.argv[0], *qt_args])
    app.setApplicationName("GamingCrypt")
    app.setStyleSheet(theme.STYLESHEET)
    window = MainWindow(cfg, lambda c: config_mod.save_config(c, cfg_path), page_factory=default_pages)
    if cfg.get("fullscreen", True) and not args.windowed:
        window.showFullScreen()
    else:
        window.resize(1280, 800)
        window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
