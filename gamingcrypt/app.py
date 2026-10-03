"""Application entry point: setup / lock screen -> main shell."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QApplication, QMainWindow, QStackedWidget, QWidget

import logging

from gamingcrypt import config as config_mod
from gamingcrypt.ui import theme
from gamingcrypt.ui.auth_setup import AuthSetupWizard
from gamingcrypt.ui.lock_screen import LockScreen
from gamingcrypt.ui.settings_tab import SettingsTab
from gamingcrypt.ui.shell import Shell
from gamingcrypt.unlock.veracrypt import VeraCryptUnlocker


log = logging.getLogger("gamingcrypt.app")


class MainWindow(QMainWindow):
    def __init__(
        self,
        config: dict,
        save: Callable[[dict], None],
        unlocker_factory=VeraCryptUnlocker.from_config,
        page_factory: Callable[[dict], dict[str, QWidget]] | None = None,
        system=None,
        input_service=None,
    ):
        super().__init__()
        self.input_service = input_service
        self.windowed = False
        from gamingcrypt.ui.game_watcher import GameWatcher

        # While a game runs the launcher steps aside; it comes back when the game ends.
        from gamingcrypt.ui.launch_overlay import LaunchOverlay

        self.game_watcher = GameWatcher(parent=self)
        self.launch_overlay = LaunchOverlay(self)
        self.launch_overlay.cancelled.connect(self.stop_watching_game)
        self.game_watcher.visible.connect(lambda _appid: self.step_aside())
        self.game_watcher.finished.connect(lambda _appid: self.game_over())
        self.game_watcher.failed.connect(lambda _appid: self.game_over())
        # Device controls (display, power, audio); empty in tests unless given.
        from gamingcrypt.system.controls import SystemControls

        self.system = system if system is not None else SystemControls()
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
            self.adopt_existing_container()
        if not unlock.get("method") or not unlock.get("volume"):
            self.show_setup()
        else:
            self.show_lock()

    def adopt_existing_container(self) -> bool:
        """A container (with sidecar) already exists: use it instead of running the setup."""
        from gamingcrypt.unlock import sidecar

        found = sidecar.find_container(self.config["unlock"])
        if not found:
            return False
        self.config["unlock"].update(found)
        self.save(self.config)
        return True

    def step_aside(self) -> None:
        """Make room for a game or a Steam window.

        Hidden, not minimised: on Wayland an app may minimise itself but is not
        allowed to un-minimise itself later - showing a hidden window again
        creates a fresh one, which the compositor puts on top.
        """
        log.info("stepping aside")
        self.hide()

    # Steam windows (store, Steam's own dialogs) would open behind the launcher.
    minimize_for_steam = step_aside

    def game_launched(self, appid: int) -> None:
        """Stay visible ("Starting …") until the game draws, then step aside."""
        games = self.shell.pages.get("Games") if self.shell else None
        self.launch_overlay.show_for(self.game_name(appid), appid, getattr(games, "service", None))
        self.game_watcher.watch(appid)

    def game_name(self, appid: int) -> str:
        games = getattr(self.shell, "pages", {}).get("Games") if self.shell else None
        game = getattr(games, "games", {}).get(appid) if games is not None else None
        return game.name if game is not None else "your game"

    def game_over(self) -> None:
        self.launch_overlay.hide()
        self.bring_to_front()

    def stop_watching_game(self) -> None:
        self.game_watcher._stop()
        self.launch_overlay.hide()

    def bring_to_front(self) -> None:
        """Back after a game, or when `gamingcrypt` / the launcher icon is started again."""
        log.info("coming back to the front")
        if self.isMinimized():
            self.hide()  # see step_aside(): a fresh window instead of un-minimising
        if self.config.get("fullscreen", True) and not self.windowed:
            self.showFullScreen()
        else:
            self.showNormal()
        self.raise_()
        self.activateWindow()

    def nav_root(self) -> QWidget:
        """Controller navigation stays inside the loading screen while it's shown."""
        return self.launch_overlay if self.launch_overlay.isVisible() else self

    def switch_tab(self, delta: int) -> None:
        if self.shell is not None and self.stack.currentWidget() is self.shell:
            self.shell.cycle_tab(delta)

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self.launch_overlay.setGeometry(self.rect())

    def closeEvent(self, event):  # noqa: N802
        current = self.stack.currentWidget()
        if hasattr(current, "abort"):
            current.abort()
        if self.input_service is not None:
            self.input_service.stop()  # give the real controller back
        super().closeEvent(event)

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
        games = pages.get("Games")
        pages.setdefault("Settings", SettingsTab(self.config, self.save, self.unlocker_factory, self.system,
                                                 steam_service=getattr(games, "service", None),
                                                 input_service=self.input_service))
        service = getattr(games, "service", None)
        if service is not None:
            # Steam windows (store, Steam's own dialogs) would open *behind* the fullscreen launcher.
            service.on_steam_ui = self.minimize_for_steam
            service.on_game_launch = self.game_launched
        self.shell = Shell(pages)
        self.shell.exit_requested.connect(self.close)
        self._replace(self.shell)
        self.screen_name = "shell"


SOCKET_NAME = f"gamingcrypt-{os.getuid()}"


def activate_running_instance(name: str = SOCKET_NAME) -> bool:
    """True if GamingCrypt already runs; it is asked to come to the front."""
    from PySide6.QtNetwork import QLocalSocket

    socket = QLocalSocket()
    socket.connectToServer(name)
    if not socket.waitForConnected(500):
        return False
    socket.write(b"raise\n")
    socket.waitForBytesWritten(500)
    socket.disconnectFromServer()
    return True


def listen_for_activation(callback: Callable[[], None], name: str = SOCKET_NAME):
    from PySide6.QtNetwork import QLocalServer

    QLocalServer.removeServer(name)  # stale socket after a crash
    server = QLocalServer()
    server.listen(name)

    def on_connection() -> None:
        conn = server.nextPendingConnection()
        if conn is not None:
            conn.disconnected.connect(conn.deleteLater)
            callback()

    server.newConnection.connect(on_connection)
    return server


def default_pages(config: dict) -> dict[str, QWidget]:
    from gamingcrypt.steam.service import SteamService
    from gamingcrypt.ui.games_tab import GamesTab

    service = SteamService(config["steam"], config_mod.cache_dir())
    mount_point = os.path.expanduser(config["unlock"].get("mount_point", "") or "")
    service.install_library = mount_point
    library_path = mount_point if config["steam"].get("auto_library", True) else ""
    from gamingcrypt.ui.downloads_tab import DownloadsTab

    return {"Games": GamesTab(service, library_path=library_path), "Downloads": DownloadsTab(service)}


SECRET_FORMAT_HINT = {
    "pin": "your PIN digits, e.g. 482916",
    "password": "your password",
    "pattern": "the swipe dots 1-9 row by row, e.g. 14789",
    "grid5": "the tapped dots 1-25 row by row joined with '-', e.g. 1-7-13-25",
}


def print_volume_password(cfg: dict, read_secret=None, out=print) -> int:
    """Recovery: show the password to type into plain VeraCrypt."""
    import getpass

    from gamingcrypt.unlock import kdf

    unlock = cfg["unlock"]
    hint = SECRET_FORMAT_HINT.get(unlock.get("method", ""), "your secret")
    read_secret = read_secret or (lambda: getpass.getpass(f"Enter {hint}: "))
    try:
        password = kdf.derive_password(read_secret(), unlock.get("kdf"))
    except kdf.KDFError as exc:
        out(f"error: {exc}")
        return 1
    out(password)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gamingcrypt", description=__doc__)
    parser.add_argument("--windowed", action="store_true", help="don't start in fullscreen")
    parser.add_argument("--config", type=Path, help="path to config.json")
    parser.add_argument("--diagnose", action="store_true",
                        help="print what GamingCrypt sees of Steam, your library and the volume")
    parser.add_argument("--volume-password", action="store_true",
                        help="print the real VeraCrypt password for your PIN/pattern (recovery)")
    args, qt_args = parser.parse_known_args(argv if argv is not None else sys.argv[1:])

    cfg_path = args.config or config_mod.config_path()
    cfg = config_mod.load_config(cfg_path)
    if args.volume_password:
        return print_volume_password(cfg)
    if args.diagnose:
        from gamingcrypt.steam.service import SteamService

        for line in SteamService(cfg["steam"], config_mod.cache_dir()).diagnose(cfg["unlock"]):
            print(line)
        print(f"Log file: {config_mod.cache_dir() / 'gamingcrypt.log'}")
        return 0

    from gamingcrypt.log import setup as setup_log

    log_path = setup_log(config_mod.cache_dir())
    app = QApplication([sys.argv[0], *qt_args])
    app.setApplicationName("GamingCrypt")
    if activate_running_instance():
        return 0  # the running GamingCrypt came to the front
    app.setStyleSheet(theme.STYLESHEET)
    from gamingcrypt.system.controls import SystemControls
    from gamingcrypt.ui.tasks import run_async

    system = SystemControls.detect()
    # Resolution and power limit reset on reboot -> restore what the user chose.
    run_async(lambda: system.apply_saved(cfg["system"]))
    from gamingcrypt.input.service import InputService

    save = lambda c: config_mod.save_config(c, cfg_path)  # noqa: E731
    input_service = InputService(cfg, save)
    input_service.start()  # virtual controller with the user's mapping, if enabled
    window = MainWindow(cfg, save, page_factory=default_pages, system=system, input_service=input_service)
    window.windowed = args.windowed
    from gamingcrypt.input.nav_source import NavSource
    from gamingcrypt.ui.navigator import GamepadNavigator

    navigator = GamepadNavigator(window, tab_switch=window.switch_tab)
    nav_source = NavSource(input_service, navigator.bridge.event.emit)
    nav_source.start()
    server = listen_for_activation(window.bring_to_front)  # noqa: F841 - keep alive
    if cfg.get("fullscreen", True) and not args.windowed:
        window.showFullScreen()
    else:
        window.resize(1280, 800)
        window.show()
    code = app.exec()
    nav_source.stop()
    # Let background work finish cleanly, e.g. a cancelled container creation
    # still has to delete its unfinished file.
    QThreadPool.globalInstance().waitForDone(30_000)
    return code


if __name__ == "__main__":
    sys.exit(main())
