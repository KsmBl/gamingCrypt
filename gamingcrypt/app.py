"""Application entry point: setup / lock screen -> main shell."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QThreadPool, Signal
from PySide6.QtWidgets import QApplication, QMainWindow, QStackedWidget, QWidget

import logging

from gamingcrypt import config as config_mod
from gamingcrypt.ui import theme
from gamingcrypt.ui.auth_setup import AuthSetupWizard
from gamingcrypt.ui.lock_screen import LockScreen
from gamingcrypt.ui.settings_tab import SettingsTab
from gamingcrypt.ui.shell import Shell
from gamingcrypt.ui.tasks import run_async
from gamingcrypt.unlock.veracrypt import VeraCryptUnlocker


log = logging.getLogger("gamingcrypt.app")


class _KeyBridge(QObject):
    key = Signal(int)


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
        self.game_watcher.phase_text.connect(self.launch_overlay.set_phase)
        # Steam may wait for a click (license agreement …) in a window behind us.
        self.game_watcher.stalled.connect(lambda _appid: self.step_aside())
        self.game_watcher.finished.connect(lambda appid: self.game_over(appid))
        self.game_watcher.failed.connect(lambda appid: self.game_over(appid, failed=True))
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
        elif self._resuming():
            self.show_shell()  # GamingCrypt restarted itself (display settings) while unlocked
        elif not os.path.exists(os.path.expanduser(unlock["volume"])):
            # deleted container / missing drive: set up again instead of a useless lock screen
            log.warning("volume %s not found", unlock["volume"])
            self.show_setup(missing_volume=unlock["volume"])
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

    def start_volume_keys(self):
        """Gaming mode only: on a desktop the compositor already handles the volume buttons."""
        from gamingcrypt.input.volume_keys import VolumeKeys
        from gamingcrypt.session.mode import in_gaming_session
        from gamingcrypt.ui.volume_osd import VolumeController, VolumeOsd

        audio = getattr(self.system, "audio", None)
        if not in_gaming_session() or audio is None:
            return None
        self.volume_osd = VolumeOsd(self)
        self.volume = VolumeController(audio, self.volume_osd, self)
        # volume -> VolumeController, Windows button -> quick menu; keys arrive from a thread
        self.key_bridge = _KeyBridge(self)
        self.key_bridge.key.connect(self.hardware_key)
        keys = VolumeKeys(self.key_bridge.key.emit)
        if not keys.start():
            log.warning("volume buttons not readable: %s - run install.sh --session",
                        "; ".join(keys.errors) or "none found")
            return None
        log.info("volume buttons: %d device(s)", len(keys.devices))
        return keys

    def hardware_key(self, code: int) -> None:
        from gamingcrypt.input import evdev as e

        if code in e.MENU_KEYS:
            self.toggle_quick_menu()
        else:
            self.volume.handle(code)

    # quick menu (Windows button) ------------------------------------------------------
    def toggle_quick_menu(self) -> None:
        menu = getattr(self, "quick_menu", None)
        if menu is not None and menu.isVisible():
            menu.close_menu()
            return
        if menu is None:
            from gamingcrypt.session.mode import in_gaming_session
            from gamingcrypt.ui.quick_menu import QuickMenu

            menu = self.quick_menu = QuickMenu(self, self.system, refresh_available=in_gaming_session())
            menu.closed.connect(self._quick_menu_closed)
            menu.force_quit.connect(self._force_quit)
        watcher = self.game_watcher
        appid = watcher.appid if watcher.active and watcher.phase in ("starting", "playing") else None
        if not self.isVisible() or self.isMinimized():
            self.bring_to_front()  # the game keeps running behind
        menu.open_menu(appid, self.game_name(appid) if appid else "")

    def _quick_menu_closed(self) -> None:
        if self.game_watcher.active and self.game_watcher.phase == "playing":
            self.step_aside()  # back to the game

    def _force_quit(self, appid: int) -> None:
        from gamingcrypt.steam.running import force_quit

        log.info("force quitting app %s", appid)
        run_async(lambda: force_quit(appid))  # the game watcher notices the exit and cleans up

    def big_picture_opened(self) -> None:
        """Make room for Steam's Big Picture and come back when it's closed."""
        from gamingcrypt.ui.big_picture import BigPictureWatcher

        if getattr(self, "big_picture", None) is None:
            self.big_picture = BigPictureWatcher(parent=self)
            self.big_picture.closed.connect(self.bring_to_front)
        self.step_aside()
        self.big_picture.watch()

    def game_launched(self, appid: int) -> None:
        """Stay visible ("Starting …") until the game draws, then step aside."""
        games = self.shell.pages.get("Games") if self.shell else None
        service = getattr(games, "service", None)
        if service is not None and hasattr(service, "install_progress"):
            from gamingcrypt.steam.running import launch_phase

            name = self.game_name(appid)
            self.game_watcher.describe = lambda a: launch_phase(a, None, name, progress=service.install_progress)
        self.launch_overlay.show_for(self.game_name(appid), appid, getattr(games, "service", None))
        self.game_watcher.watch(appid)

    def game_name(self, appid: int) -> str:
        games = getattr(self.shell, "pages", {}).get("Games") if self.shell else None
        game = getattr(games, "games", {}).get(appid) if games is not None else None
        return game.name if game is not None else "your game"

    def game_over(self, appid: int | None = None, failed: bool = False) -> None:
        menu = getattr(self, "quick_menu", None)
        if menu is not None and menu.isVisible():
            menu.hide()  # the game is gone - nothing to go back to
        # Pages showing "Starting <game>…" must not keep saying so after the game.
        if self.shell is not None and appid is not None:
            for page in self.shell.findChildren(QWidget):
                hook = getattr(page, "game_session_ended", None)
                if callable(hook):
                    hook(appid, failed)
        self.launch_overlay.hide()
        self.bring_to_front()

    def stop_watching_game(self) -> None:
        appid = self.game_watcher.appid
        self.game_watcher._stop()
        if appid is not None and self.shell is not None:
            for page in self.shell.findChildren(QWidget):
                hook = getattr(page, "game_session_ended", None)
                if callable(hook):
                    hook(appid, False)
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

    def _resuming(self) -> bool:
        from gamingcrypt.session import mode

        if not mode.in_gaming_session() or not mode.consume_resume_token():
            return False
        try:
            return self.unlocker_factory(self.config["unlock"]).is_mounted()
        except Exception:  # noqa: BLE001 - when in doubt: lock screen
            return False

    def desktop_mode(self) -> None:
        """In the gaming session: switch to the desktop (tileWin); otherwise just quit."""
        from gamingcrypt.session import mode

        if mode.in_gaming_session():
            self.leave_gaming_mode("desktop")
        else:
            self.close()

    def restart_gaming_mode(self) -> None:
        self.leave_gaming_mode("restart")

    def leave_gaming_mode(self, target: str) -> None:
        """Close Steam, then end gamescope: it waits for every program started inside it.

        ``target``: "desktop" (switch to tileWin) or "restart" (gaming mode again, e.g. to
        apply display settings - without the lock screen if we're unlocked).
        """
        from gamingcrypt.session import mode
        from gamingcrypt.steam import library_setup

        if target == "desktop":
            mode.request_desktop_mode()
        else:
            mode.request_restart()
            if self.screen_name == "shell":
                mode.write_resume_token()
        log.info("leaving gaming mode (%s)", target)
        games = self.shell.pages.get("Games") if self.shell is not None else None
        service = getattr(games, "service", None)

        def work() -> bool:
            if service is not None:
                library_setup.close_steam(service.client, timeout=20)
            return mode.end_gamescope()

        run_async(work, lambda ended: None if ended else self.close(), lambda _e: self.close())

    def check_display_change(self) -> None:
        """After a display change: ask, revert by itself after 15 s."""
        from gamingcrypt.session import mode
        from gamingcrypt.ui.display_confirm import DisplayConfirm

        if not mode.in_gaming_session() or not mode.display_pending():
            return
        self.display_confirm = DisplayConfirm(self)
        self.display_confirm.kept.connect(mode.confirm_display)
        self.display_confirm.reverted.connect(self._revert_display)
        args = mode.parse_display(mode.read_args())
        render = f"{args['width']}×{args['height']}" if "width" in args else "native"
        refresh = f"{args['refresh']} Hz" if "refresh" in args else "default"
        actual = mode.actual_mode()
        self.display_confirm.ask(f"Resolution {render}, refresh rate {refresh}"
                                 + (f" (screen: {actual})" if actual else ""))

    def _revert_display(self) -> None:
        from gamingcrypt.session import mode

        mode.revert_display()
        self.restart_gaming_mode()

    def power_action(self, kind: str) -> None:
        log.info("power action: %s", kind)
        if self.input_service is not None:
            self.input_service.stop()  # give the real controller back first
        ok, message = self.power_runner(kind)
        if not ok:
            self.shell.power_menu.show_error(message)
            if self.input_service is not None:
                self.input_service.start()

    @staticmethod
    def power_runner(kind: str):
        from gamingcrypt.system.session import power_action

        return power_action(kind)

    def nav_root(self) -> QWidget:
        """Controller navigation stays inside the loading screen / power menu while shown."""
        confirm = getattr(self, "display_confirm", None)
        if confirm is not None and confirm.isVisible():
            return confirm
        menu = getattr(self, "quick_menu", None)
        if menu is not None and menu.isVisible():
            return menu
        if self.launch_overlay.isVisible():
            return self.launch_overlay
        menu = getattr(self.shell, "power_menu", None) if self.shell is not None else None
        if menu is not None and menu.isVisible():
            return menu
        return self

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

    def show_setup(self, missing_volume: str = "") -> None:
        wizard = AuthSetupWizard(self.config, self.save, self.unlocker_factory, first_start=True,
                                 missing_volume=missing_volume)
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
                                                 input_service=self.input_service,
                                                 restart_gaming=self.restart_gaming_mode))
        service = getattr(games, "service", None)
        if service is not None:
            # Steam windows (store, Steam's own dialogs) would open *behind* the fullscreen launcher.
            service.on_steam_ui = self.minimize_for_steam
            service.on_game_launch = self.game_launched
            service.on_big_picture = self.big_picture_opened
        self.shell = Shell(pages)
        self.shell.exit_requested.connect(self.desktop_mode)
        self.shell.power_requested.connect(self.power_action)
        self._replace(self.shell)
        self.screen_name = "shell"


SOCKET_NAME = f"gamingcrypt-{os.getuid()}"


def acquire_instance_lock(path):
    """Hold an exclusive lock for the whole lifetime of GamingCrypt.

    Atomic (flock): two starts at the same moment can never both win - unlike
    only checking for the running copy's activation socket. Returns the open
    lock file (keep it referenced!) or None if another GamingCrypt runs.
    """
    import fcntl

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+")  # noqa: SIM115 - must stay open
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    handle.seek(0)
    handle.truncate()
    handle.write(f"{os.getpid()}\n")
    handle.flush()
    return handle


def wait_and_activate(name: str = SOCKET_NAME, timeout: float = 5.0, sleep=None) -> bool:
    """The other copy may still be starting up - keep asking it for a moment."""
    import time

    sleep = sleep or time.sleep
    deadline = time.monotonic() + timeout
    while True:
        if activate_running_instance(name):
            return True
        if time.monotonic() >= deadline:
            return False
        sleep(0.2)


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
    parser.add_argument("--gaming-mode", action="store_true",
                        help="from the desktop: go back to gaming mode (ends the desktop session)")
    parser.add_argument("--volume-key-devices", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--diagnose", action="store_true",
                        help="print what GamingCrypt sees of Steam, your library and the volume")
    parser.add_argument("--volume-password", action="store_true",
                        help="print the real VeraCrypt password for your PIN/pattern (recovery)")
    args, qt_args = parser.parse_known_args(argv if argv is not None else sys.argv[1:])

    cfg_path = args.config or config_mod.config_path()
    cfg = config_mod.load_config(cfg_path)
    if args.volume_password:
        return print_volume_password(cfg)
    if args.volume_key_devices:  # used by install.sh for its udev rule
        from gamingcrypt.input.evdev import find_volume_key_devices

        for device in find_volume_key_devices():
            print(device.name)
        return 0
    if args.gaming_mode:
        from gamingcrypt.session import mode

        if mode.leave_desktop():
            return 0
        print("Could not end the desktop session - log out to return to gaming mode")
        return 1
    if args.diagnose:
        from gamingcrypt.steam.service import SteamService

        for line in SteamService(cfg["steam"], config_mod.cache_dir()).diagnose(cfg["unlock"]):
            print(line)
        print(f"Log file: {config_mod.cache_dir() / 'gamingcrypt.log'}")
        return 0

    from gamingcrypt.log import setup as setup_log

    lock = acquire_instance_lock(config_mod.cache_dir() / "instance.lock")
    app = QApplication([sys.argv[0], *qt_args])
    app.setApplicationName("GamingCrypt")
    if lock is None:
        # Never two copies (they'd fight over the controller, Steam and the volume).
        wait_and_activate()
        return 0
    log_path = setup_log(config_mod.cache_dir())
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

    volume_keys = window.start_volume_keys()
    navigator = GamepadNavigator(window, tab_switch=window.switch_tab)
    nav_source = NavSource(input_service, navigator.bridge.event.emit)
    nav_source.start()
    server = listen_for_activation(window.bring_to_front)  # noqa: F841 - keep alive
    window.check_display_change()
    if cfg.get("fullscreen", True) and not args.windowed:
        window.showFullScreen()
    else:
        window.resize(1280, 800)
        window.show()
    code = app.exec()
    nav_source.stop()
    if volume_keys is not None:
        volume_keys.stop()
    # Let background work finish cleanly, e.g. a cancelled container creation
    # still has to delete its unfinished file.
    QThreadPool.globalInstance().waitForDone(30_000)
    return code


if __name__ == "__main__":
    sys.exit(main())
