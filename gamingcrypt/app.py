"""Application entry point: setup / lock screen -> main shell."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable

import shiboken6
from PySide6.QtCore import QObject, Qt, QThreadPool, QTimer, Signal
from PySide6.QtWidgets import QAbstractButton, QApplication, QMainWindow, QStackedWidget, QWidget

import logging

from gamingcrypt import config as config_mod
from gamingcrypt.ui import theme
from gamingcrypt.ui.auth_setup import AuthSetupWizard
from gamingcrypt.system.battery import read_battery
from gamingcrypt.ui.lock_screen import LockScreen
from gamingcrypt.ui.settings_tab import SettingsTab
from gamingcrypt.ui.shell import Shell
from gamingcrypt.ui.tasks import run_async
from gamingcrypt.unlock.veracrypt import UnlockResult, VeraCryptUnlocker


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
        self.game_watcher.visible.connect(lambda _appid: self.step_aside("game"))
        self.game_watcher.phase_text.connect(self.launch_overlay.set_phase)
        # Steam may wait for a click (license agreement …) in a window behind us.
        self.game_watcher.stalled.connect(lambda _appid: self.step_aside())
        from gamingcrypt.game_profiles import GameProfiles

        self.game_profiles = GameProfiles()
        from gamingcrypt.ui.tasks import serial_pool

        self._power_pool = serial_pool(self)  # game start/end in quick succession: keep the order
        self._pause_pool = serial_pool(self)  # a game paused for the quick menu, then going on: in this order
        self.game_watcher.started.connect(self.game_started)
        self.game_watcher.finished.connect(self.game_ended)
        self.game_watcher.failed.connect(self.game_ended)
        self.game_watcher.finished.connect(lambda appid: self.game_over(appid))
        self.game_watcher.failed.connect(lambda appid: self.game_over(appid, failed=True))
        from PySide6.QtCore import QTimer as Clock  # (QTimer is imported further down in here too)

        self.play_clock = Clock(self)  # an emulated game's play time, kept every minute while it runs
        self.play_clock.timeout.connect(self.keep_play_time)
        self.play_clock.start(self.PLAY_TICK_MS)
        # Gaming mode: games started elsewhere (Big Picture, a self-restart we missed) must be
        # taken in too - otherwise gamescope's focus order would keep them hidden.
        from PySide6.QtCore import QTimer

        from gamingcrypt.session.mode import in_gaming_session

        # sleep: notice the wake-up (re-apply the power limit, maybe lock again)
        from gamingcrypt.session.mode import runtime_dir
        from gamingcrypt.system.sleep import SleepClock
        from gamingcrypt.unlock import verifier

        self.verifier_path = runtime_dir() / "verifier"
        self.verifier = verifier.load(self.verifier_path)
        self.sleep_clock = SleepClock()
        self.wake_timer = QTimer(self)
        self.wake_timer.timeout.connect(self.check_wake)
        self.wake_timer.start(2000)
        self.sleep_lock = None
        # notifications + low battery (everywhere: lock screen, menus, in-game)
        from gamingcrypt.ui.battery_warning import BatteryMonitor, BatteryWarning
        from gamingcrypt.ui.toast import Toasts

        self.toasts = Toasts(self)
        self.battery_warning = BatteryWarning(self)
        self.battery_warning.sleep_now.connect(self.go_to_sleep)
        self.battery_warning.dismissed.connect(self._back_to_game)
        self.battery_monitor = BatteryMonitor(self.battery_reader, self)
        self.battery_monitor.notice.connect(self.battery_low)  # 15 %: the red border
        self.battery_monitor.critical.connect(self.battery_low)  # 5 %: again
        from gamingcrypt.ui.battery_edge import BatteryEdge

        self.battery_edge = BatteryEdge(self)  # (over GamingCrypt; over a game: game_battery_edge)
        self.game_battery_edge = None
        self.battery_monitor.warning.connect(self.warn_battery)
        self.download_notifier = None
        self.adopt_timer = QTimer(self)
        self.adopt_timer.timeout.connect(self.adopt_running_game)
        if in_gaming_session():
            self.adopt_timer.start(3000)
        # Device controls (display, power, audio); empty in tests unless given.
        from gamingcrypt.system.controls import SystemControls

        self.system = system if system is not None else SystemControls()
        self.setWindowTitle("GamingCrypt")
        self.config = config
        from gamingcrypt import users

        # written without what's only for now (who is logged in), a user's Steam settings with the user
        self.save = lambda cfg: save(users.persistable(cfg))
        self.unlocker_factory = unlocker_factory
        self.page_factory = page_factory
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)
        self.check_failed_sleep()
        self.reload_hotkeys()
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
        from gamingcrypt import users

        users.adopt(self.config, found)  # (its users too, where there are some)
        self.save(self.config)
        return True

    def step_aside(self, front: str = "steam") -> None:
        """Make room for a game or a Steam window.

        ``front`` tells gamescope what to show instead: "game" (the running game),
        "big_picture" (opened on purpose) or "steam" (a Steam window - let gamescope pick).

        Hidden, not minimised: on Wayland an app may minimise itself but is not
        allowed to un-minimise itself later - showing a hidden window again
        creates a fresh one, which the compositor puts on top.
        """
        log.info("stepping aside (%s)", front)
        self.hide()
        self.gamescope_focus(front)

    # Steam windows (store, Steam's own dialogs) would open behind the launcher.
    def minimize_for_steam(self) -> None:
        self.step_aside("steam")

    def showEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().showEvent(event)
        self.gamescope_focus("launcher")
        QTimer.singleShot(400, self.toasts.flush)  # what came in while a game was in front

    def gamescope_focus(self, front: str) -> None:
        """Gaming mode: tell gamescope what belongs on screen (see gamescope_ctl)."""
        from gamingcrypt.session.mode import in_gaming_session
        from gamingcrypt.system import gamescope_ctl as gs

        if not in_gaming_session():
            return
        watcher = self.game_watcher
        game = watcher.appid if watcher.active else None
        from gamingcrypt.movies.library import is_movie_appid

        # the performance overlay: games only (not over GamingCrypt, not over a movie)
        gs.apply_overlay(front == "game" and game is not None and not is_movie_appid(game))
        # touches: real ones for GamingCrypt, clicks for the movie player (its touch controls)
        clicks = front == "game" and is_movie_appid(game)
        if clicks or getattr(self, "_touch_clicks", False):
            self._touch_clicks = clicks
            gs.set_touch_mode(gs.TOUCH_LEFT_CLICK if clicks else gs.TOUCH_PASSTHROUGH)
        # Every list ends with all candidates: in gamescope's Steam mode an order that
        # matches no open window would leave the screen black.
        launcher, steam = gs.LAUNCHER_APPID, gs.BIG_PICTURE_APPID
        order = {"launcher": [launcher, game, steam],
                 "game": [game, launcher, steam]}.get(front, [steam, game, launcher])
        log.info("gamescope focus: %s %s", front, order)
        # right away (a few ms): a hide + show in quick succession must not swap the order
        if front == "launcher" and not gs.set_window_appid(int(self.winId())):
            log.warning("could not give the window its gamescope app id (xprop missing?)")
        if not gs.set_focus_order(order):
            log.warning("could not set gamescope's focus order (xprop missing?)")

    def start_volume_keys(self):
        """Gaming mode only: on a desktop the compositor already handles the volume buttons."""
        from gamingcrypt.input.volume_keys import VolumeKeys
        from gamingcrypt.session.mode import in_gaming_session
        from gamingcrypt.ui.volume_osd import VolumeController, VolumeOsd

        audio = getattr(self.system, "audio", None)
        if not in_gaming_session() or audio is None:
            return None
        self.volume_osd = VolumeOsd(self)
        from gamingcrypt.ui.volume_osd import GameOverlay

        self.game_volume_osd = GameOverlay()
        self.volume = VolumeController(audio, self.volume_osd, self,
                                       step=lambda: self.config["system"].get("volume_step", 5),
                                       game_osd=self.game_volume_osd, use_game_osd=self.emulated_game_in_front)
        # volume -> VolumeController, Windows button -> quick menu; keys arrive from a thread
        self.key_bridge = _KeyBridge(self)
        self.key_bridge.key.connect(self.hardware_key)
        keys = VolumeKeys(self.key_bridge.key.emit, finder=self.key_devices, bindings=self.hotkeys)
        self.volume_keys = keys
        if not keys.start():
            log.warning("volume buttons not readable: %s - run install.sh --session",
                        "; ".join(keys.errors) or "none found")
            return None
        log.info("volume buttons: %d device(s)", len(keys.devices))
        return keys

    def key_devices(self):
        """Volume / power buttons plus the devices of recorded device buttons."""
        from gamingcrypt.input import evdev as e

        names = {b.device for b in self.hotkeys.values() if b.source == "key" and b.device}
        found = e.find_volume_key_devices()
        known = {d.path for d in found}
        return found + [d for d in e.list_devices() if d.name in names and d.path not in known]

    def reload_hotkeys(self) -> None:
        """Settings -> Controller -> Device buttons changed."""
        from gamingcrypt.input import hotkeys

        self.hotkeys = hotkeys.load(self.config)
        self.controller_hotkeys = hotkeys.load_external(self.config)  # (a connected controller's own)
        self.pad_tracker = hotkeys.Tracker(self.hotkeys, hotkeys.PAD, also=self.controller_hotkeys)
        keys = getattr(self, "volume_keys", None)
        if keys is not None:
            keys.tracker.bindings = self.hotkeys
        shell = getattr(self, "shell", None)
        if shell is not None:
            shell.hint_bar.set_quick_menu(self.hotkeys["quick_menu"])

    def pad_hotkey(self, ev_type: int, code: int, value: int) -> bool:
        """Controller buttons bound as device buttons (e.g. Guide = quick menu); also in a game."""
        from gamingcrypt.input import evdev as e
        from gamingcrypt.input import hotkeys

        consumed = False
        if ev_type == e.EV_KEY and value != 2:
            actions, consumed = self.pad_tracker.feed(code, value == 1)
            for action in actions:
                self.hardware_key(hotkeys.ACTION_CODES[action])
        if not consumed and self.movie_in_front():
            self.movie_remote(ev_type, code, value)
            return True  # the controller steers the movie
        return consumed

    def movie_in_front(self) -> bool:
        return not self.isVisible() and self.running_movie() is not None

    def movie_remote(self, ev_type: int, code: int, value: int) -> None:
        """mpv can't read the controller (GamingCrypt holds the physical one): its buttons are
        sent to the player as commands."""
        from gamingcrypt.movies import player

        command = player.remote_command(ev_type, code, value)
        if command is not None:
            sock = player.socket_path()
            run_async(lambda: player.send(sock, command), owner=self)

    def hardware_key(self, code: int) -> None:
        from gamingcrypt.input import evdev as e
        from gamingcrypt.input import hotkeys

        if code == hotkeys.ACTION_CODES["lock"]:
            self.panic_lock()
        elif code == hotkeys.ACTION_CODES["quick_menu"]:
            self.toggle_quick_menu()
        elif code == hotkeys.ACTION_CODES["keyboard"]:
            self.toggle_keyboard()
        elif code == e.KEY_POWER:
            self.power_button()
        else:
            self.volume.handle(code)

    # on-screen keyboard (its device button) ----------------------------------------------
    def toggle_keyboard(self) -> None:
        """For the highlighted text field (or the page's first one): its own keyboard when it has
        one, else the keyboard docked at the bottom of the window."""
        from gamingcrypt.ui import keyboard_overlay
        from gamingcrypt.ui.widgets import focus_and_reveal

        overlay = getattr(self, "keyboard_overlay", None)
        if overlay is not None and overlay.isVisible():
            overlay.close_keyboard()
            return
        over_game = getattr(self, "game_keyboard", None)
        if over_game is not None and over_game.is_open():
            over_game.close_keyboard()
            return
        if not self.isVisible() or self.isMinimized():
            if self.game_watcher.active and self.game_watcher.phase == "playing":
                self.open_game_keyboard()
            return
        edit = keyboard_overlay.text_field(self.nav_root())
        if edit is None:
            self.notify("No text field here to type into", "⌨")
            return
        own = keyboard_overlay.page_keyboard(edit)
        if own is not None:
            keys = [k for k in own.findChildren(QAbstractButton) if k.isVisible()]
            if keys:
                focus_and_reveal(keys[0])
            return
        if overlay is None:
            overlay = self.keyboard_overlay = keyboard_overlay.KeyboardOverlay(self)
        overlay.open_for(edit)

    def open_game_keyboard(self) -> None:
        """Over the game: what's typed reaches it as key presses (see ui/game_keyboard)."""
        keyboard = getattr(self, "game_keyboard", None)
        if keyboard is None:
            from gamingcrypt.ui.game_keyboard import GameKeyboard

            keyboard = self.game_keyboard = GameKeyboard(hotkeys=self.pad_hotkey, divert=self.divert_controller)
        keyboard.open_over_game()

    def divert_controller(self, target) -> None:
        if self.input_service is not None:
            self.input_service.divert(target)

    # sleep -----------------------------------------------------------------------------
    def start_power_key(self):
        """Gaming mode: the power button suspends instead of shutting down (logind's default)."""
        from gamingcrypt.session.mode import in_gaming_session
        from gamingcrypt.system import sleep

        if not in_gaming_session():
            return None
        inhibitor = sleep.inhibit_power_key()
        if inhibitor is None:
            log.warning("could not take over the power button (systemd-inhibit missing?)")
        return inhibitor

    POWER_DEBOUNCE_S = 2.0

    def power_button(self) -> None:
        import time

        slept = self.sleep_clock.slept()
        if slept:
            self.woke_up(slept)  # the press that woke the device - don't fall asleep again
            return
        # Both ACPI "Power Button" devices report the same press: one press, one sleep.
        now = time.monotonic()
        if now - getattr(self, "_last_power_press", -1e9) < self.POWER_DEBOUNCE_S:
            return
        self._last_power_press = now
        if self.sleep_allowed() and self.config["system"].get("power_button") == "sleep":
            self.go_to_sleep()
            return
        # default: the power menu (sleep, shut down, restart, Windows, desktop mode)
        if not self.isVisible():
            self.bring_to_front()
        if self.screen_name == "shell" and self.shell is not None:
            self.shell.open_power_menu()

    def sleep_allowed(self) -> bool:
        return not self.config.setdefault("system", {}).get("sleep_broken")

    def sleep_marker(self):
        from gamingcrypt.session.mode import state_dir

        return state_dir() / "sleeping"

    def check_failed_sleep(self) -> bool:
        """Start-up: a marker left from going to sleep means the device never woke up
        (it had to be switched off hard). Sleep is switched off then."""
        marker = self.sleep_marker()
        if not marker.exists():
            return False
        try:
            marker.unlink()
        except OSError:
            pass
        log.warning("the device didn't wake up from sleep last time - sleep switched off")
        self.config["system"]["sleep_broken"] = True
        self.config["system"]["power_button"] = "menu"
        self.save(self.config)
        self.notify("The device didn't wake up from sleep last time, so sleep is now off "
                    "(Settings → Device to try again).", "☾")
        return True

    def go_to_sleep(self) -> None:
        from gamingcrypt.system import sleep

        if not self.sleep_allowed():
            self.notify("Sleep is off - this device didn't wake up from it last time.", "☾")
            return
        log.info("going to sleep")
        try:
            marker = self.sleep_marker()
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text("1\n")  # gone after waking up - see check_failed_sleep
        except OSError:
            pass
        run_async(sleep.suspend, lambda r: None if r[0] else log.warning("suspend failed: %s", r[1]),
                  lambda _e: None, owner=self)

    def check_wake(self) -> None:
        slept = self.sleep_clock.slept()
        if slept:
            self.woke_up(slept)

    def woke_up(self, seconds: float) -> None:
        from gamingcrypt.session.mode import in_gaming_session

        log.info("woke up after %.0f s", seconds)
        try:
            self.sleep_marker().unlink()
        except OSError:
            pass
        self.apply_power_profile()  # the CPU forgets its power limit while asleep
        minutes = self.config.get("system", {}).get("lock_after_sleep_min")
        if (minutes is not None and seconds >= minutes * 60 and in_gaming_session()
                and self.screen_name == "shell" and self.verifier is not None):
            self.lock_after_sleep()

    def lock_after_sleep(self) -> None:
        from gamingcrypt.ui.lock_screen import LockScreen
        from gamingcrypt.unlock.verifier import VerifyUnlocker

        if self.sleep_lock is not None:
            return
        log.info("locking after sleep")
        from gamingcrypt import users

        # whoever is logged in: their code
        lock = self.sleep_lock = LockScreen(VerifyUnlocker(self.verifier), users.current(self.config).method, self)
        lock.setAutoFillBackground(True)
        lock.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        lock.unlocked.connect(self._sleep_unlocked)
        lock.power_requested.connect(self.power_action)
        self.load_other_systems(lock)
        lock.setGeometry(self.rect())
        lock.raise_()
        lock.show()
        if not self.isVisible():
            self.bring_to_front()  # in front of the game

    battery_reader = staticmethod(read_battery)

    def panic_lock(self) -> None:
        """Lock now: end the game, close Steam, unmount the drive, show the lock screen -
        the lock screen first, so nothing stays visible meanwhile."""
        from gamingcrypt.steam import library_setup, running
        from gamingcrypt.ui.widgets import set_status

        if self.screen_name != "shell":
            return
        log.warning("panic lock")
        games = self.shell.pages.get("Games") if self.shell is not None else None
        service = getattr(games, "service", None)
        unlocker = self.unlocker_factory(self.config["unlock"])
        for overlay in (getattr(self, "quick_menu", None), getattr(self, "controls_overlay", None), self.sleep_lock,
                        self.battery_warning, getattr(self, "keyboard_overlay", None)):
            if overlay is not None:
                overlay.hide()
        keyboard = getattr(self, "game_keyboard", None)
        if keyboard is not None:
            keyboard.close_keyboard()
        self.sleep_lock = None
        self.game_watcher._stop()
        self.launch_overlay.hide()
        self.verifier = None
        self.show_lock()
        lock = self.stack.currentWidget()
        set_status(lock.status, "Locking…")
        if not self.isVisible():
            self.bring_to_front()

        def work():
            from gamingcrypt.emulation.sharing import DriveShare, drive_share_password

            for appid in running.running_appids():
                running.force_quit(appid)
            if service is not None:
                library_setup.close_steam(service.client, timeout=20)
            if drive_share_password():
                DriveShare().stop(force=True)  # its connections would keep the drive busy
            return unlocker.dismount()

        def done(result) -> None:
            if shiboken6.isValid(lock):
                set_status(lock.status, "Locked" if result.success else f"Could not lock the drive: {result.message}",
                           error=not result.success)

        run_async(work, done, lambda exc: done(UnlockResult(False, str(exc))), owner=self)

    def battery_low(self, percent: int) -> None:
        """A red border around the screen and a message, 10 s - in gaming mode drawn by gamescope
        over everything (also a game); otherwise over GamingCrypt's window."""
        from gamingcrypt.session.mode import in_gaming_session

        log.warning("battery at %s %%", percent)
        if in_gaming_session():
            if self.game_battery_edge is None:
                from gamingcrypt.ui.battery_edge import GameBatteryEdge

                self.game_battery_edge = GameBatteryEdge()
            self.game_battery_edge.alert(percent)
        else:
            self.battery_edge.alert(percent)

    def warn_battery(self, percent: int) -> None:
        log.warning("battery at %s %%", percent)
        self.battery_warning.open(percent)
        if not self.isVisible():
            self.bring_to_front()  # in front of the game

    def _back_to_game(self) -> None:
        if self.game_watcher.active and self.game_watcher.phase == "playing":
            self.step_aside("game")

    def notify(self, text: str, icon: str = "ℹ") -> None:
        log.info("notice: %s", text)
        self.toasts.notify(text, icon)

    def _sleep_unlocked(self) -> None:
        lock, self.sleep_lock = self.sleep_lock, None
        if lock is not None:
            lock.hide()
            lock.deleteLater()
        if self.game_watcher.active and self.game_watcher.phase == "playing":
            self.step_aside("game")  # back to the game

    def logged_in(self, user, secret: str) -> None:
        """The lock screen took this user's code: the device is theirs until it's locked."""
        from gamingcrypt import users

        user = users.enter(self.config, user.id if user is not None else None)
        log.info("unlocked by %s", "the admin" if user.admin else "a user")
        from gamingcrypt import game_profiles

        self.game_profiles = game_profiles.for_user(user)  # per-game settings: their own
        self.apply_own_settings(login=True)
        if self.config.get("last_user") != user.id and len(users.all_users(self.config)) > 1:
            self.config["last_user"] = user.id  # chosen on the lock screen the next time
            self.save(self.config)
        self.remember_code(secret)

    def apply_own_settings(self, login: bool = False) -> None:
        """With more users, each has settings of their own (users.OWN): the look, the performance
        overlay, the screen's refresh rate and resolution, the power limit. They're put in place
        when somebody logs in - and the admin's again at the lock screen. One user: nothing to do."""
        from PySide6.QtWidgets import QApplication

        from gamingcrypt import users
        from gamingcrypt.session import mode

        if len(users.all_users(self.config)) < 2:
            return
        look, size = theme.from_config(self.config), theme.size_from_config(self.config)
        if (look, size) != (theme.current, theme.text_size):
            theme.apply(look, QApplication.instance(), size)
        if not mode.in_gaming_session() or not login:
            return
        from gamingcrypt.system import gamescope_ctl, overlay_bar

        bar = overlay_bar.mangohud_config(overlay_bar.settings_of(self.config))
        hz = self.default_refresh()
        rates = self.refresh_rates()

        def work() -> None:
            gamescope_ctl.set_bar(bar)
            if rates:
                gamescope_ctl.set_dynamic_refresh(hz)

        run_async(work, owner=self, pool=self._power_pool)
        self.apply_power_profile()
        if self.own_resolution_differs():
            QTimer.singleShot(0, self.restart_gaming_mode)  # (after the shell is up: it resumes as this user)

    def own_resolution_differs(self) -> bool:
        """The resolution is one of gamescope's options: another one than the last user's means
        gaming mode starts again (a few seconds). True: the options are written, restart now."""
        from gamingcrypt import users
        from gamingcrypt.session import mode

        native = mode.panel_size() or (1280, 800)
        current = mode.parse_display(mode.read_args())
        now = f"{current.get('width', native[0])}x{current.get('height', native[1])}"
        wanted = self.config["system"].get("gaming_resolution")
        kept = self.config.get(users.KEPT, {}).get("system")
        if isinstance(kept, dict) and not kept.get("gaming_resolution"):
            kept["gaming_resolution"] = now  # what the admin has: theirs again at their next login
            self.save(self.config)
        sizes = {f"{w}x{h}": (w, h) for w, h in mode.render_sizes(native)}
        if not wanted or wanted == now or wanted not in sizes or mode.display_pending():
            return False
        w, h = sizes[wanted]
        mode.apply_display(*((None, None) if (w, h) == native else (w, h)), None)
        mode.confirm_display()  # one of the sizes Settings offers: nothing to ask
        log.info("gaming mode restarts at %s for who logged in", wanted)
        return True

    def use_own_steam_account(self, service) -> None:
        """More users, each with a Steam account of their own (chosen in Settings -> Games): Steam
        is switched to the one of who just logged in."""
        from gamingcrypt import users

        wanted = self.config["steam"].get("account")
        if not wanted or service is None or not hasattr(service, "accounts") \
                or len(users.all_users(self.config)) < 2:
            return

        def work():
            account = next((a for a in service.accounts() if a.steam_id == wanted), None)
            if account is None or account.most_recent:
                return None  # already theirs (or not on this device any more)
            ok, message = service.switch_account(account)
            return f"Steam: {account.persona}" if ok else message

        run_async(work, lambda text: self.notify(text, "ℹ") if text else None, lambda _e: None, owner=self)

    def is_admin_code(self, secret: str) -> bool:
        """Is that the code the admin unlocked with (this session)? For the first user that's added:
        nothing else says whether the admin's code is right."""
        from gamingcrypt.unlock import verifier

        return bool(self.verifier) and self.verifier.get("user", "admin") == "admin" \
            and verifier.check(self.verifier, secret)

    def remember_code(self, secret: str) -> None:
        from gamingcrypt import users
        from gamingcrypt.unlock import verifier

        self.verifier = verifier.make(secret)
        self.verifier["user"] = users.current(self.config).id  # (a restart of GamingCrypt keeps who it is)
        try:
            verifier.save(self.verifier, self.verifier_path)
        except OSError as exc:
            log.warning("could not keep the code check: %s", exc)

    def desired_power_w(self) -> int | None:
        """The running game's own power limit, otherwise the one from Settings."""
        watcher = self.game_watcher
        if watcher.active:
            watts = self.game_profiles.get(watcher.appid).get("power_w")
            if watts:
                return int(watts)
        return self.config.get("system", {}).get("power_limit_w") or getattr(self, "_power_before_game", None)

    # per-game profile (Options on the game page) --------------------------------------------
    def own_steam_history(self, appid: int | None) -> bool:
        """A Steam game played by a user who isn't the admin: when and how long is kept with the
        user (Steam only knows it per Steam account) - for their Continue playing / Recently played."""
        from gamingcrypt import users
        from gamingcrypt.emulation.library import EMU_APPID_BASE
        from gamingcrypt.linux.library import is_linux_appid
        from gamingcrypt.minecraft.library import is_minecraft_appid
        from gamingcrypt.movies.library import is_movie_appid
        from gamingcrypt.wine.library import is_wine_appid

        return (appid is not None and appid < EMU_APPID_BASE and not is_wine_appid(appid)
                and not is_linux_appid(appid) and not is_minecraft_appid(appid) and not is_movie_appid(appid)
                and not users.current(self.config).admin)

    def game_started(self, appid: int) -> None:
        import time

        if self.own_steam_history(appid):
            if not hasattr(self, "_steam_started"):
                self._steam_started = {}
            self._steam_started[appid] = time.time()
            self.game_profiles.set(appid, "last_played", int(time.time()))
        profile = self.game_profiles.get(appid)
        power = getattr(self.system, "power", None)
        if profile.get("power_w") and power is not None and not self.config.get("system", {}).get("power_limit_w"):
            # no limit chosen in Settings: remember the current one to go back to it
            limit = power.read()
            self._power_before_game = limit.current_w if limit else None
        if profile.get("power_w"):
            log.info("app %s: own power limit %s W", appid, profile["power_w"])
            self.apply_power_profile()
        self.apply_fps_limit(profile.get("fps", 0))

    PLAY_TICK_MS = 60_000

    def keep_play_time(self) -> None:
        from gamingcrypt.emulation.library import EMU_APPID_BASE

        appid = self.game_watcher.appid if self.game_watcher.active else None
        games = self.shell.pages.get("Games") if self.shell is not None else None
        play_log = getattr(games, "play_log", None)
        if appid is not None and appid >= EMU_APPID_BASE and play_log is not None:
            try:
                play_log.tick(appid)
            except OSError as exc:  # (the drive)
                log.warning("play time of %s not kept: %s", appid, exc)

    def game_ended(self, appid: int | None = None) -> None:
        from gamingcrypt.emulation.library import EMU_APPID_BASE

        self.end_game_refresh()  # the screen's own refresh rate again
        self.stop_upscaling()
        self.windows_game_ended(appid)
        started = getattr(self, "_steam_started", {}).pop(appid, None) if appid is not None else None
        if started is not None:  # a user's own play time of a Steam game
            import time

            minutes = int(self.game_profiles.get(appid).get("minutes", 0)) + max(0, round((time.time() - started) / 60))
            self.game_profiles.set(appid, "minutes", minutes)
            self.game_profiles.set(appid, "last_played", int(time.time()))
            tab = self.shell.pages.get("Games") if self.shell is not None else None
            if hasattr(tab, "reload_installed"):
                tab.reload_installed()  # Continue playing, Recently played
        for tab in self.video_tabs():
            if appid is not None:
                tab.movie_ended(appid)  # watched? where it was stopped

        games = self.shell.pages.get("Games") if self.shell is not None else None
        play_log = getattr(games, "play_log", None)
        if appid is not None and appid >= EMU_APPID_BASE and play_log is not None:
            play_log.finish(appid)  # play time of an emulated game
            games.reload_roms()  # Continue playing / Recently played
        if appid is not None and self.game_profiles.get(appid).get("power_w"):
            self.apply_power_profile()  # the watcher is idle again: the Settings value
        self._power_before_game = None
        self.apply_fps_limit(0)

    def apply_fps_limit(self, fps: int) -> None:
        from gamingcrypt.session.mode import in_gaming_session
        from gamingcrypt.system import gamescope_ctl

        if in_gaming_session() and (fps or getattr(self, "_fps_set", False)):
            self._fps_set = bool(fps)
            run_async(lambda: gamescope_ctl.set_fps_limit(fps), owner=self, pool=self._power_pool)

    def apply_power_profile(self) -> None:
        watts = self.desired_power_w()
        power = getattr(self.system, "power", None)
        if not watts or power is None:
            return
        run_async(lambda: power.set(watts), lambda r: log.info("power limit %s W: %s", watts, r[1]),
                  lambda _e: None, owner=self, pool=self._power_pool)

    # quick menu (Windows button) ------------------------------------------------------
    def toggle_quick_menu(self) -> None:
        keyboard = getattr(self, "game_keyboard", None)
        if keyboard is not None and keyboard.is_open():
            keyboard.close_keyboard()  # (the menu comes to the front instead)
        menu = getattr(self, "quick_menu", None)
        if menu is not None and menu.isVisible():
            menu.close_menu()
            return
        if menu is None:
            from gamingcrypt.session.mode import in_gaming_session
            from gamingcrypt.ui.quick_menu import QuickMenu

            menu = self.quick_menu = QuickMenu(self, self.system, refresh_available=self.refresh_rates(),
                                               refresh_get=self.menu_refresh, refresh_set=self.set_menu_refresh)
            menu.closed.connect(self._quick_menu_closed)
            menu.force_quit.connect(self._force_quit)
            menu.lock_now.connect(self.panic_lock)
            menu.power_chosen.connect(self.quick_power)
            menu.fps_chosen.connect(self.quick_fps)
            menu.screenshot.connect(self.take_screenshot)
            menu.states_requested.connect(self.open_states)
            menu.controls_requested.connect(self.open_running_controls)
            menu.bluetooth_requested.connect(self.open_bluetooth)
            menu.speed_chosen.connect(self.choose_speed)
            menu.in_step_chosen.connect(self.choose_in_step)
            menu.pad_chosen.connect(self.choose_pad)
            menu.disc_chosen.connect(self.set_disc)
        watcher = self.game_watcher
        appid = watcher.appid if watcher.active and watcher.phase in ("starting", "playing") else None
        if not self.isVisible() or self.isMinimized():
            self.bring_to_front()  # the game keeps running behind
        from gamingcrypt.emulation.library import EMU_APPID_BASE

        menu.set_performance(**self.performance_state(appid))
        rom = self.running_rom() if appid is not None and appid >= EMU_APPID_BASE else None
        retroarch_game = rom is not None and rom.system.emulator == "retroarch"
        speed = getattr(self, "_chosen_speed", None) or getattr(self, "speed", 1.0)  # (chosen, not applied yet)
        menu.set_emulated(retroarch_game, speed if retroarch_game else None,
                          states=bool(retroarch_game and rom.system.save_states))
        in_step = bool(retroarch_game and self.game_profiles.get(rom.appid).get("in_step"))
        chosen = getattr(self, "_chosen_in_step", None)
        menu.set_in_step(bool(retroarch_game) and (in_step or self.running_at_50_hz()),
                         in_step if chosen is None else chosen)
        from gamingcrypt.emulation import retroarch

        # the controller the game runs with - and the one it gets (chosen, or for its next start)
        pad = self.game_profiles.get(rom.appid).get("pad") if retroarch_game else None
        menu.set_pads(retroarch.pad_choices(rom.system.id) if retroarch_game else [],
                      getattr(self, "running_pad", pad), getattr(self, "_chosen_pad", None) or (pad,))
        menu.set_speed_busy(getattr(self, "_speed_changing", False))
        menu.set_discs(len(rom.discs) if retroarch_game else 0, getattr(self, "disc_index", 0))
        menu.set_lock_shortcut(self.hotkeys["lock"], self.controller_hotkeys["lock"])
        menu.open_menu(appid, self.game_name(appid) if appid else "")
        if rom is not None and watcher.phase == "playing":
            self.pause_game(rom)  # an emulated game stands still while the menu is open

    def refresh_rates(self) -> bool:
        """Gaming mode on a screen with other refresh rates than its own."""
        from gamingcrypt.session import mode

        return mode.in_gaming_session() and mode.refresh_rates_available()

    def default_refresh(self) -> int:
        """The screen's refresh rate from Settings (0: the panel's own - also where it has no other)."""
        return int(self.config["system"].get("gaming_refresh") or 0) if self.refresh_rates() else 0

    def menu_refresh(self) -> int:
        """What the quick menu shows: 0 ("Default") while it's the rate from Settings."""
        from gamingcrypt.system import gamescope_ctl

        hz = gamescope_ctl.dynamic_refresh()
        return 0 if hz == self.default_refresh() else hz

    def set_menu_refresh(self, hz: int) -> bool:
        from gamingcrypt.system import gamescope_ctl

        return gamescope_ctl.set_dynamic_refresh(hz or self.default_refresh())

    def performance_state(self, appid: int | None) -> dict:
        from gamingcrypt.session.mode import in_gaming_session
        from gamingcrypt.system import gamescope_ctl

        power = getattr(self.system, "power", None)
        try:
            limit = power.read() if power is not None else None
        except Exception:  # noqa: BLE001 - the menu must open anyway
            limit = None
        from gamingcrypt.movies.library import is_movie_appid

        overlay = None  # no switch: there's no overlay over a movie or a show (see gamescope_focus)
        if in_gaming_session() and gamescope_ctl.overlay_available() and not is_movie_appid(appid):
            overlay = gamescope_ctl.overlay_wanted()
        profile = self.game_profiles.get(appid) if appid else {}
        return {"limit": limit, "watts": self.desired_power_w(), "fps": profile.get("fps", 0), "overlay": overlay,
                "in_game": appid is not None}

    def quick_power(self, watts: int) -> None:
        """Quick menu: in a game it's that game's limit, otherwise the one from Settings."""
        if self.game_watcher.active:
            self.game_profiles.set(self.game_watcher.appid, "power_w", watts)
        else:
            self.config["system"]["power_limit_w"] = watts
            self.save(self.config)
        self.apply_power_profile()

    def quick_fps(self, fps: int) -> None:
        if self.game_watcher.active:
            self.game_profiles.set(self.game_watcher.appid, "fps", fps)
            self.apply_fps_limit(fps)

    def take_screenshot(self) -> None:
        """The quick menu closed and the game is in front again: let gamescope capture it."""
        import re
        import shutil
        import time
        from datetime import datetime
        from pathlib import Path

        from gamingcrypt.system import gamescope_ctl

        appid = self.game_watcher.appid
        name = re.sub(r"[^\w.-]+", "_", self.game_name(appid) if appid else "screen").strip("_") or "screen"
        target = Path.home() / "Pictures" / "GamingCrypt" / f"{name}_{datetime.now():%Y-%m-%d_%H-%M-%S}.png"

        def work():
            time.sleep(0.8)  # the game back in front
            source = Path(gamescope_ctl.SCREENSHOT_FILE)
            before = source.stat().st_mtime if source.exists() else 0
            if not gamescope_ctl.request_screenshot():
                return None
            deadline = time.monotonic() + 6
            while time.monotonic() < deadline:
                time.sleep(0.2)
                if not gamescope_ctl.screenshot_pending() and source.exists() and source.stat().st_mtime > before:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
                    return target
            return None

        def done(path) -> None:
            if path is None:
                self.notify("The screenshot didn't work", "📷")
            else:
                self.notify(f"Screenshot saved: {path.name}", "📷")

        run_async(work, done, lambda _e: done(None), owner=self)

    def _quick_menu_closed(self) -> None:
        """Back to the game (also from a page of the menu): it goes on - at the speed chosen."""
        self.resume_game()
        self.apply_menu_choices()
        if self.game_watcher.active and self.game_watcher.phase == "playing":
            self.step_aside("game")  # back to the game

    # an emulated game paused while the quick menu is open ------------------------------------
    def pause_game(self, rom) -> None:
        if getattr(self, "_paused", None) is not None or getattr(self, "_speed_changing", False):
            return
        from gamingcrypt.emulation import retroarch
        from gamingcrypt.steam import running

        core = self.game_profiles.get(rom.appid).get("core") or (rom.system.cores or ("",))[0]
        paused = self._paused = {"appid": rom.appid, "retroarch": rom.system.emulator == "retroarch", "done": False,
                                 "ask": retroarch.asks_status(core)}  # (Cemu: asking crashes RetroArch)

        def pause() -> None:
            if paused["retroarch"]:
                paused["done"] = retroarch.pause(ask=paused["ask"])  # (not one it was paused in already)
            else:  # an emulator without such a command (Eden): its processes stop
                paused["done"] = running.pause_game(rom.appid, True) > 0

        run_async(pause, lambda _r: None, lambda _e: None, pool=self._pause_pool)

    def resume_game(self) -> None:
        paused, self._paused = getattr(self, "_paused", None), None
        if paused is None:
            return
        from gamingcrypt.emulation import retroarch
        from gamingcrypt.steam import running

        def resume() -> None:
            if not paused["done"]:
                return
            if paused["retroarch"]:
                retroarch.resume(ask=paused["ask"])
            else:
                running.pause_game(paused["appid"], False)

        run_async(resume, lambda _r: None, lambda _e: None, pool=self._pause_pool)

    def choose_speed(self, speed: float) -> None:
        """Quick menu: the speed - applied when it's closed."""
        self._chosen_speed = speed

    def choose_in_step(self, on: bool) -> None:
        """Quick menu: a 50 Hz game at 60 FPS or not - applied when it's closed."""
        self._chosen_in_step = on

    def choose_pad(self, pad: str | None) -> None:
        """Quick menu: the console's controller the game is played with - applied when it's closed."""
        self._chosen_pad = (pad,)

    def apply_menu_choices(self) -> None:
        speed, self._chosen_speed = getattr(self, "_chosen_speed", None), None
        in_step, self._chosen_in_step = getattr(self, "_chosen_in_step", None), None
        pad, self._chosen_pad = getattr(self, "_chosen_pad", None), None
        rom = self.running_rom()
        if rom is None or getattr(self, "_speed_changing", False):
            return
        if pad is not None and pad[0] != self.game_profiles.get(rom.appid).get("pad"):
            self.set_pad(rom, pad[0], speed, in_step)
            return
        if in_step is not None and in_step != bool(self.game_profiles.get(rom.appid).get("in_step")):
            if speed is not None and speed != getattr(self, "speed", 1.0):
                self._remember_speed(rom, speed)
            self.set_in_step(in_step, speed)  # one restart for both
        elif speed is not None:
            self.set_speed(speed)

    def _force_quit(self, appid: int) -> None:
        from gamingcrypt.steam.running import force_quit

        log.info("force quitting app %s", appid)
        watcher = self.game_watcher
        if watcher.appid == appid:
            watcher.expect_exit()  # no waiting "in case it restarts itself"
        # the game watcher cleans up - asked right away, not at its next look
        run_async(lambda: force_quit(appid), lambda _n: watcher.poll() if watcher.appid == appid else None, owner=self)

    def big_picture_opened(self) -> None:
        """Make room for Steam's Big Picture and come back when it's closed."""
        from gamingcrypt.ui.big_picture import BigPictureWatcher

        if getattr(self, "big_picture", None) is None:
            self.big_picture = BigPictureWatcher(parent=self)
            self.big_picture.closed.connect(self._big_picture_closed)
        self.step_aside("big_picture")
        self.big_picture.watch()

    def _big_picture_closed(self) -> None:
        if self.game_watcher.active and self.game_watcher.phase == "playing":
            return  # a game started from Big Picture is running - it comes back after that
        self.bring_to_front()

    def game_launched(self, appid: int) -> None:
        """Stay visible ("Starting …") until the game draws, then step aside."""
        from gamingcrypt.emulation.library import EMU_APPID_BASE

        from gamingcrypt.linux.library import is_linux_appid
        from gamingcrypt.minecraft.library import is_minecraft_appid
        from gamingcrypt.movies.library import is_movie_appid
        from gamingcrypt.wine.library import is_wine_appid

        games = self.shell.pages.get("Games") if self.shell else None
        if is_wine_appid(appid) or is_linux_appid(appid) or is_minecraft_appid(appid):  # Steam's patience
            name = self.game_name(appid)
            self.game_watcher.describe = lambda a: f"Starting {name}…"
            self.launch_overlay.show_for(name, appid, None, self.cover_loader(appid))
            self.launch_overlay.set_phase(f"Starting {name}…")
            self.game_watcher.watch(appid)
            return
        if is_movie_appid(appid):  # a movie (mpv): up in a moment, gone when it's gone
            from gamingcrypt.ui.game_watcher import QUICK

            self.game_watcher.describe = lambda a: "Starting the movie…"
            self.launch_overlay.show_for(self.game_name(appid), appid, None, self.cover_loader(appid))
            self.launch_overlay.set_phase("Starting the movie…")
            self.game_watcher.watch(appid, QUICK)
            return
        if appid >= EMU_APPID_BASE:  # an emulated game (RetroArch)
            self.game_watcher.describe = self._retroarch_starting
            self.launch_overlay.show_for(self.game_name(appid), appid, None, self.cover_loader(appid))
            self.launch_overlay.set_phase("Starting RetroArch…")
            self.game_watcher.watch(appid)
            return
        service = getattr(games, "service", None)
        if service is not None and hasattr(service, "install_progress"):
            from gamingcrypt.steam.running import launch_phase

            name = self.game_name(appid)
            self.game_watcher.describe = lambda a: launch_phase(a, None, name, progress=service.install_progress)
        self.launch_overlay.show_for(self.game_name(appid), appid, getattr(games, "service", None))
        self.game_watcher.watch(appid)

    def _retroarch_starting(self, appid: int) -> str:
        """While RetroArch starts: did it fail to load the game? It stays open, empty, then - the
        loading screen never ended (Final Fantasy VIII without its LibCrypt .sbi files)."""
        from gamingcrypt.emulation import retroarch

        problem = retroarch.start_problem(config_mod.cache_dir() / "logs" / retroarch.LOG_NAME)
        if problem is None:
            return "Starting RetroArch…"
        QTimer.singleShot(0, lambda: self._retroarch_failed(appid, problem))
        return "The game didn't load"

    def _retroarch_failed(self, appid: int, problem: str) -> None:
        """RetroArch ended (nothing to wait for), the reason said - on the game's page and as a notice."""
        watcher = self.game_watcher
        if watcher.appid != appid:
            return  # handled already
        log.warning("app %s didn't load: %s", appid, problem)
        from gamingcrypt.steam.running import force_quit

        watcher._stop()
        run_async(lambda: force_quit(appid), lambda _n: None, lambda _e: None, owner=self)
        if self.shell is not None:
            for page in self.shell.findChildren(QWidget):
                hook = getattr(page, "start_failed", None)
                if callable(hook):
                    hook(appid, problem)
        self.notify(problem, "⚠")
        self.game_over(appid, failed=True)

    def adopt_running_game(self) -> None:
        watcher = self.game_watcher
        if watcher.active:
            return

        def adopt(appid: int | None) -> None:
            if appid is None or watcher.active:
                return
            log.info("app %s is running (not started here) - following it", appid)
            watcher.watch(appid)

        run_async(watcher.drawing_game, adopt, lambda _e: None, owner=self)

    def cover_loader(self, appid: int, game=None):
        """How the loading screen gets the picture of a game that isn't Steam's - the same
        cover its card shows: box art (emulated), Steam's picture (Windows / Linux), the
        movie's cover. None: Steam's own (or nothing found)."""
        games = self.shell.pages.get("Games") if self.shell else None
        if games is not None and game is None:
            game = getattr(games, "rom_games", {}).get(appid)
            if game is None and hasattr(games, "windows_by_appid"):
                game = games.windows_by_appid(appid)
        from gamingcrypt.emulation.library import RomGame
        from gamingcrypt.wine.library import WindowsGame

        if isinstance(game, RomGame):
            from gamingcrypt.ui.emulation_pages import load_rom_cover

            covers = getattr(games, "covers", None)
            return lambda label, w, h: load_rom_cover(label, game, covers, w, h)
        if isinstance(game, WindowsGame):  # Linux games too
            from gamingcrypt.ui.wine_pages import load_windows_cover

            covers = getattr(games, f"{game.KIND}_covers", None)
            return lambda label, w, h: load_windows_cover(label, game, covers, w, h)
        movie = self.running_movie(appid)
        path = getattr(movie, "cover_path", None)
        if path is not None:
            def draw(label, w, h) -> None:
                from PySide6.QtGui import QPixmap

                pixmap = QPixmap(str(path)) if path.exists() else QPixmap()
                if not pixmap.isNull():
                    scaled = pixmap.scaled(w, h, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                                           Qt.TransformationMode.SmoothTransformation)
                    label.setPixmap(scaled.copy((scaled.width() - w) // 2, (scaled.height() - h) // 2, w, h))
            return draw
        return None

    def game_name(self, appid: int) -> str:
        games = getattr(self.shell, "pages", {}).get("Games") if self.shell else None
        game = getattr(games, "games", {}).get(appid) if games is not None else None
        if game is None and games is not None:
            game = getattr(games, "rom_games", {}).get(appid)  # emulated
        if game is None and games is not None and hasattr(games, "windows_by_appid"):
            game = games.windows_by_appid(appid)  # Windows (Proton / Wine)
        movie = self.running_movie(appid)
        if movie is not None:
            return movie.title
        return game.name if game is not None else "your game"

    def launch_rom(self, game) -> tuple[bool, str]:
        """Play on an emulated game: RetroArch through the "reaper" script (see emulation/retroarch)."""
        from gamingcrypt.emulation import retroarch

        games = self.shell.pages.get("Games") if self.shell else None
        paths = getattr(games, "emulation", None)
        if paths is None:
            return False, "The games drive isn't unlocked"
        if game.system.emulator == "eden":
            ok, message = self.launch_switch(game, paths, games)
            if ok is None:
                return True, message  # downloading Eden first
            return self._rom_started(game, games, ok, message, "Eden")
        core = self.game_profiles.get(game.appid).get("core")
        fetch = getattr(games, "core_fetcher", None)
        if fetch is not None and retroarch.available() and retroarch.find_core(paths, game.system, core) is None:
            return self.download_core_then_launch(game, paths, core, fetch)
        from gamingcrypt.emulation import cores

        found = retroarch.find_core(paths, game.system, core)
        if fetch is not None and found is not None and cores.needs_system_files(paths, found):
            # e.g. Dolphin's Sys folder (GameCube, Wii)
            return self.download_then_launch(
                game, lambda: cores.download_system_files(paths, found), f"the system files for {game.system.name}",
                f"Couldn't download the system files for {game.system.name} - no network?")
        ok, message = self.start_retroarch(game, paths)
        if ok:
            self.start_state_clock(0)  # started without a state: played from now
        return self._rom_started(game, games, ok, message, "RetroArch")

    def start_state_clock(self, played: int) -> None:
        """Play time of save states: so much was played up to here (a state just loaded: its
        own time; a fresh start: nothing), the rest is counted from now."""
        import time

        self.state_clock = (int(played), time.monotonic())

    def state_played(self) -> int:
        """Seconds played up to now - what a state saved now gets."""
        import time

        played, since = getattr(self, "state_clock", (0, time.monotonic()))
        return played + max(0, int(time.monotonic() - since))

    def start_retroarch(self, game, paths) -> tuple[bool, str]:
        """RetroArch with the game and everything chosen for it (also again, for another speed)."""
        from gamingcrypt.emulation import languages, layouts, retroarch, upscaling
        from gamingcrypt.emulation import shaders as shader_choice
        from gamingcrypt.ui.tour import data_dir

        profile = self.game_profiles.get(game.appid)
        core = profile.get("core")
        scaler, resolution = upscaling.for_game(self.config, profile, game.system.id)  # its own, else its system's
        rates = self.speed_rates(game)
        ok, message = retroarch.launch(game, paths, data_dir(), config_mod.cache_dir() / "logs", core,
                                       layout=layouts.load(self.config, game.system.id), **dict(zip(
                                           ("fast", "slow"), rates)),
                                       memory_card=profile.get("memory_card"),
                                       widescreen=profile.get("widescreen"),
                                       input_lag=profile.get("input_lag"), renderer=profile.get("renderer"),
                                       resolution=resolution,
                                       shaders=shader_choice.for_game(self.config, profile, game.system.id),
                                       scaler=scaler, in_step=bool(profile.get("in_step")),
                                       language=languages.for_system(self.config, game.system),
                                       pad=profile.get("pad"))
        if ok:
            self.follow_game_refresh(config_mod.cache_dir() / "logs" / retroarch.LOG_NAME)
            self.speed_mode, self.speed = "normal", 1.0  # RetroArch starts at normal speed
            self.running_rates = rates  # what "fast" and "slow" mean until it's started again
            self.running_pad = profile.get("pad")
            self.disc_index = retroarch.current_disc(paths, game, retroarch.find_core(paths, game.system, core))
        return ok, message

    # running speed of RetroArch games ----------------------------------------------------------
    def emulated_game_in_front(self) -> bool:
        """Steam shows its own volume indicator over its games - over emulators, movies and Windows /
        Linux games (and Minecraft) started here nobody does."""
        from gamingcrypt.linux.library import is_linux_appid
        from gamingcrypt.minecraft.library import is_minecraft_appid
        from gamingcrypt.wine.library import is_wine_appid

        appid = self.game_watcher.appid
        windows = self.game_watcher.active and (is_wine_appid(appid) or is_linux_appid(appid)
                                                or is_minecraft_appid(appid))
        return not self.isVisible() and (self.running_rom() is not None or self.running_movie() is not None
                                         or windows)

    # Windows games (Proton / Wine) ---------------------------------------------------------------
    def launch_windows(self, game) -> tuple[bool, str]:
        """Its start file with the chosen Proton / Wine (the newest Proton when nothing was chosen)."""
        import time

        from gamingcrypt.ui.tour import data_dir
        from gamingcrypt.wine import library as wine
        from gamingcrypt.wine import runners

        games = self.shell.pages.get("Games") if self.shell else None
        profile = self.game_profiles.get(game.appid)
        exe = profile.get("exe") or next(iter(wine.executables(game)), None)
        if exe is None:
            return False, "There's no .exe in its folder - copy the whole game folder over the network share"
        found = games.windows_runners() if hasattr(games, "windows_runners") else runners.available()
        runner = runners.pick(found, profile.get("runner"))
        if runner is None:
            return False, ("No Proton or Wine on this device - install a Proton in Steam (any game: Properties → "
                           "Compatibility) or Wine")
        if runner.kind == "proton" and runners.is_32bit(game.path / exe) and not runners.vulkan_32bit():
            return False, runners.VULKAN_32.format(game=game.name)  # it would quit after 2 s without a word
        pads = self.input_service.game_env() if self.input_service is not None else {}
        ok, message = runners.launch(game, exe, runner, data_dir(), config_mod.cache_dir() / "logs",
                                     more_env={**pads, **self.start_upscaling(profile)})
        self.upscaling_started(ok)
        if ok:
            log.info("starting Windows game %s: %s with %s", game.name, exe, runner.label)
            self._windows_started = getattr(self, "_windows_started", {})
            self._windows_started[game.appid] = time.time()
            self.game_launched(game.appid)
        else:
            log.warning("Windows game %s: %s", game.name, message)
        return ok, message

    # Linux games: as the Windows ones, without Proton / Wine -------------------------------------
    def launch_linux(self, game) -> tuple[bool, str]:
        """Its start file - directly, or in Steam's runtime when that was chosen."""
        import time

        from gamingcrypt.linux import library as linux
        from gamingcrypt.linux import runners
        from gamingcrypt.ui.tour import data_dir

        games = self.shell.pages.get("Games") if self.shell else None
        profile = self.game_profiles.get(game.appid)
        exe = profile.get("exe") or next(iter(linux.executables(game)), None)
        if exe is None:
            return False, ("There's no program or start script in its folder - copy the whole (unpacked) game "
                           "folder over the network share")
        found = games.linux_runners() if hasattr(games, "linux_runners") else runners.available()
        runner = runners.pick(found, profile.get("runner"))
        pads = self.input_service.game_env() if self.input_service is not None else {}  # SDL games too
        ok, message = runners.launch(game, exe, runner, data_dir(), config_mod.cache_dir() / "logs",
                                     more_env={**pads, **self.start_upscaling(profile)})
        self.upscaling_started(ok)
        if ok:
            log.info("starting Linux game %s: %s (%s)", game.name, exe, runner.label)
            self._windows_started = getattr(self, "_windows_started", {})
            self._windows_started[game.appid] = time.time()
            self.game_launched(game.appid)
        else:
            log.warning("Linux game %s: %s", game.name, message)
        return ok, message

    def screen_size(self) -> tuple[int, int]:
        screen = self.screen()
        size = screen.size() if screen is not None else None
        return (size.width(), size.height()) if size is not None and size.width() > 0 else (1280, 800)

    def start_upscaling(self, profile: dict) -> dict[str, str]:
        """The game's Upscaling choice: gamescope's second X server at the smaller size, FSR on -
        the game's environment ({} when off, or outside the gaming session)."""
        from gamingcrypt.session.mode import in_gaming_session
        from gamingcrypt.system import upscaling

        if not profile.get("upscale") or not in_gaming_session():
            return {}
        env = upscaling.start(profile.get("upscale"), self.screen_size())
        self._upscaled = bool(env)
        return env

    def upscaling_started(self, ok: bool) -> None:
        if not ok:
            self.stop_upscaling()  # it didn't start: nothing to scale

    def stop_upscaling(self) -> None:
        """The second X server at full size again, the usual scaling."""
        if getattr(self, "_upscaled", False):
            from gamingcrypt.system import upscaling

            self._upscaled = False
            screen = self.screen_size()
            run_async(lambda: upscaling.stop(screen), owner=self, pool=self._power_pool)

    # Minecraft: an instance, started by portablemc --------------------------------------------------
    def launch_minecraft(self, instance) -> tuple[bool, str]:
        """An installed instance (its page installs it first), with the signed-in account."""
        import time

        from gamingcrypt.emulation.retroarch import reaper
        from gamingcrypt.minecraft import portable
        from gamingcrypt.ui.tour import data_dir

        games = self.shell.pages.get("Games") if self.shell else None
        if not portable.available():
            return False, "Minecraft's launcher isn't set up yet - open the Minecraft library while online"
        if not instance.installed:
            return False, f"{instance.name} isn't installed yet - press Play on its page"
        account = games.minecraft_account() if hasattr(games, "minecraft_account") else None
        if account is None:
            return False, "Sign in with your Microsoft account first (Minecraft library)"
        args = portable.launch_command(games.minecraft_paths(), instance, account)
        log_dir = config_mod.cache_dir() / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        try:
            with open(log_dir / "minecraft.log", "wb") as out:
                subprocess.Popen([str(reaper(data_dir())), "SteamLaunch", f"AppId={instance.appid}", "--", *args],
                                 cwd=str(instance.path), stdin=subprocess.DEVNULL, stdout=out,
                                 stderr=subprocess.STDOUT, start_new_session=True)
        except OSError as exc:
            return False, f"It didn't start: {exc}"
        log.info("starting Minecraft %s (%s) as %s", instance.name, instance.installed, account.username)
        self._windows_started = getattr(self, "_windows_started", {})
        self._windows_started[instance.appid] = time.time()
        self.game_launched(instance.appid)
        return True, f"Starting {instance.name}…"

    def minecraft_problem(self) -> str:
        """Why Minecraft didn't start, from portablemc's output - "" when it doesn't say."""
        from gamingcrypt.minecraft import portable

        try:
            lines = (config_mod.cache_dir() / "logs" / "minecraft.log").read_text(errors="replace").splitlines()
        except OSError:
            return ""
        for line in lines:
            kind, values = portable.parse(line)
            if kind.startswith("error_"):
                return portable.error_text(kind, values)
        return ""

    def windows_game_ended(self, appid: int | None) -> None:
        """Play time and "last played" of a Windows or Linux game (Steam keeps its own games')."""
        import time

        started = getattr(self, "_windows_started", {}).pop(appid, None) if appid is not None else None
        if started is None:
            return
        profile = self.game_profiles.get(appid)
        self.game_profiles.set(appid, "minutes", int(profile.get("minutes", 0)) + max(0, round((time.time() - started) / 60)))
        self.game_profiles.set(appid, "last_played", int(time.time()))
        games = self.shell.pages.get("Games") if self.shell else None
        if hasattr(games, "reload_windows"):
            games.reload_windows()  # Continue playing, Recently played
        if hasattr(games, "reload_linux"):
            games.reload_linux()
        if hasattr(games, "reload_minecraft"):
            games.reload_minecraft()

    def video_tabs(self) -> list:
        """Movies and Shows: what the player plays."""
        pages = self.shell.pages if self.shell is not None else {}
        return [pages[n] for n in ("Movies", "Shows") if hasattr(pages.get(n), "movie_ended")]

    def running_movie(self, appid: int | None = None):
        """The movie or episode playing (or with that app id)."""
        if appid is None:
            appid = self.game_watcher.appid if self.game_watcher.active else None
        if appid is None:
            return None
        return next((found for tab in self.video_tabs() for found in [tab.by_appid(appid)] if found), None)

    def launch_movie(self, movie, start: float = 0) -> tuple[bool, str]:
        """A movie: mpv full screen, like a game (quick menu, volume, Force quit)."""
        from gamingcrypt.movies import player
        from gamingcrypt.ui.tour import data_dir

        movies = self.shell.pages.get("Movies") if self.shell else None
        ok, message = player.launch(movie, data_dir(), config_mod.cache_dir() / "logs", start,
                                    languages=getattr(movies, "languages", ("en", "de")))
        if ok:
            log.info("playing movie %s from %.0f s", movie.key, start)
            self.game_launched(movie.appid)
        else:
            log.warning("movie player: %s", message)
        return ok, message

    def running_rom(self):
        games = self.shell.pages.get("Games") if self.shell else None
        appid = self.game_watcher.appid if self.game_watcher.active else None
        return getattr(games, "rom_games", {}).get(appid) if appid is not None else None

    def speed_rates(self, game) -> tuple[float, float]:
        """(fast, slow) RetroArch is started with: what the quick menu's slider was on last."""
        from gamingcrypt.emulation import retroarch

        profile = self.game_profiles.get(game.appid) if game is not None else {}
        fast, slow = profile.get("fast_speed"), profile.get("slow_speed")
        return (fast if fast in retroarch.FAST_SPEEDS else retroarch.DEFAULT_FAST,
                slow if slow in retroarch.SLOW_SPEEDS else retroarch.DEFAULT_SLOW)

    def follow_game_refresh(self, log) -> None:
        """Gaming mode: the screen at the game's own rate (50 Hz PAL games on a 60 Hz screen
        stutter). Needs a panel gamescope knows refresh rates for (install.sh adds some)."""
        from gamingcrypt.session.mode import in_gaming_session

        if not in_gaming_session() or not self.config["system"].get("follow_game_refresh") \
                or not self.refresh_rates():
            return
        timer = getattr(self, "_refresh_timer", None)
        if timer is None:
            timer = self._refresh_timer = QTimer(self)
            timer.timeout.connect(self._check_game_refresh)
        self._refresh_log, self._refresh_set = log, 0
        timer.start(1000)

    def _check_game_refresh(self) -> None:
        from gamingcrypt.emulation import retroarch
        from gamingcrypt.system import gamescope_ctl

        if not self.game_watcher.active:
            return
        game_log, current = self._refresh_log, self._refresh_set

        def work():
            if current and gamescope_ctl.dynamic_refresh() != current:
                return None  # changed in the quick menu: that wins
            return retroarch.refresh_for(retroarch.content_fps(game_log))

        def done(hz) -> None:
            if hz is None:
                self._refresh_timer.stop()
            elif hz != self._refresh_set:
                log.info("screen at %s Hz for the game", hz or "the default")
                self._refresh_set = hz
                run_async(lambda: gamescope_ctl.set_dynamic_refresh(hz or self.default_refresh()), owner=self)

        run_async(work, done, owner=self)

    def end_game_refresh(self) -> None:
        from gamingcrypt.system import gamescope_ctl

        timer = getattr(self, "_refresh_timer", None)
        if timer is not None:
            timer.stop()
        if getattr(self, "_refresh_set", 0):
            self._refresh_set = 0
            run_async(lambda: gamescope_ctl.set_dynamic_refresh(self.default_refresh()), owner=self)

    def set_disc(self, index: int) -> None:
        """Quick menu: change discs - open the tray, step to the disc, close it."""
        import time

        from gamingcrypt.emulation import retroarch

        commands = retroarch.disc_commands(getattr(self, "disc_index", 0), index)
        self.disc_index = index

        def work() -> None:
            for command in commands:
                retroarch.send(command)
                time.sleep(0.2)  # RetroArch takes one per frame; the tray needs a moment

        run_async(work, owner=self)
        if commands:
            self.notify(f"Disc {index + 1} is in", "💿")

    def set_speed(self, speed: float) -> None:
        """Quick menu: how fast the game runs. Normal speed and the rates RetroArch was started
        with are its own toggles (instant); it reads other rates only at its start - so the game
        is saved, RetroArch started again with the rate, and the game put back where it was."""
        from gamingcrypt.emulation import retroarch

        rom = self.running_rom()
        if rom is None or getattr(self, "_speed_changing", False) or speed == getattr(self, "speed", 1.0):
            return
        mode = retroarch.mode_of(speed)
        fast, slow = getattr(self, "running_rates", self.speed_rates(rom))
        self._remember_speed(rom, speed)
        if mode == "normal" or speed == (fast if mode == "fast" else slow):
            for command in retroarch.mode_commands(getattr(self, "speed_mode", "normal"), mode):
                retroarch.send(command)
            self.speed_mode, self.speed = mode, speed
            return
        self.restart_at_speed(rom, speed)

    def _remember_speed(self, rom, speed: float) -> None:
        """The next start has it right away."""
        from gamingcrypt.emulation import retroarch

        mode = retroarch.mode_of(speed)
        if mode != "normal":
            default = retroarch.DEFAULT_FAST if mode == "fast" else retroarch.DEFAULT_SLOW
            self.game_profiles.set(rom.appid, f"{mode}_speed", None if speed == default else speed)

    def running_at_50_hz(self) -> bool:
        """The running emulated game is a 50 Hz (PAL) one - RetroArch's log says so."""
        from gamingcrypt.emulation import retroarch

        return retroarch.is_50_hz(retroarch.content_fps(config_mod.cache_dir() / "logs" / retroarch.LOG_NAME))

    def set_in_step(self, on: bool, speed: float | None = None) -> None:
        """Quick menu: a 50 Hz game at the screen's 60 FPS (a fifth faster) - or as it was made.
        One of RetroArch's settings, read at its start: the game is saved, started again, put back
        (at ``speed`` when another one was chosen too)."""
        rom = self.running_rom()
        if rom is None or getattr(self, "_speed_changing", False):
            return
        self.game_profiles.set(rom.appid, "in_step", True if on else None)
        self.restart_at_speed(rom, speed if speed is not None else getattr(self, "speed", 1.0),
                              text="Changing to 60 FPS…" if on else "Changing back to 50 FPS…",
                              unsaved=("60 FPS" if on else "50 FPS") + " from the next start - this game can't be "
                                                                         "saved while it runs")

    def set_pad(self, rom, pad: str | None, speed: float | None = None, in_step: bool | None = None) -> None:
        """Quick menu: the console's controller (Wii U: Pro Controller or GamePad) - the core gets it
        when RetroArch starts: the game is saved, started again, put back (with the speed / 60 FPS
        chosen too); a game that can't be saved gets it from its next start."""
        from gamingcrypt.emulation import retroarch

        self.game_profiles.set(rom.appid, "pad", pad)
        name = dict(retroarch.pad_choices(rom.system.id)).get(pad, "").split(" - ")[0]
        if in_step is not None:
            self.game_profiles.set(rom.appid, "in_step", True if in_step else None)
        speed = speed if speed is not None else getattr(self, "speed", 1.0)
        if speed != getattr(self, "speed", 1.0):
            self._remember_speed(rom, speed)
        self.restart_at_speed(rom, speed, text=f"Changing to the {name}…",
                              unsaved=f"The {name} from the next start - this game can't be saved while it runs")

    def restart_at_speed(self, rom, speed: float, text: str = "", unsaved: str = "") -> None:
        import time

        from gamingcrypt.emulation import retroarch, savestates
        from gamingcrypt.steam.running import force_quit

        games = self.shell.pages.get("Games") if self.shell else None
        paths = getattr(games, "emulation", None)
        if paths is None:
            return
        mode, appid = retroarch.mode_of(speed), rom.appid

        def busy(on: bool, text: str = "") -> None:
            self._speed_changing = on
            menu = getattr(self, "quick_menu", None)
            if menu is not None:
                menu.set_speed_busy(on, text)
                menu.show_speed(speed if on else getattr(self, "speed", 1.0))

        def save_and_stop() -> bool:
            if not rom.system.save_states or not savestates.capture(paths, rom, savestates.SPARE, retroarch.send):
                return False
            force_quit(appid)
            return True

        def stopped(saved: bool) -> None:
            if not saved:  # a core without save states: nothing to come back to
                busy(False)
                self.notify(unsaved or f"{speed:g}x from the next start - this game can't be saved while it runs",
                            "ℹ")
                return
            if getattr(self.running_rom(), "appid", None) != appid:
                busy(False)
                return  # ended meanwhile
            ok, message = self.start_retroarch(rom, paths)  # within the watcher's patience: "it restarted itself"
            if not ok:
                busy(False)
                self.notify(message, "⚠")
                return
            run_async(resume, resumed, lambda _e: resumed(False), owner=self)

        def resume() -> bool:
            deadline = time.monotonic() + 40
            while not retroarch.playing():
                if time.monotonic() > deadline:
                    return False
                time.sleep(0.25)
            time.sleep(0.5)  # the first frames
            retroarch.send(savestates.load_command(savestates.SPARE))
            time.sleep(0.5)  # one command a frame; the state first
            for command in retroarch.mode_commands("normal", mode):
                retroarch.send(command)
            return True

        def resumed(ok: bool) -> None:
            if ok:
                self.speed_mode, self.speed = mode, speed
            busy(False)
            if not ok:
                slot = savestates.rescue(paths, rom)
                self.notify("The game didn't come back by itself" + (
                    f" - where you were is in slot {slot + 1} of Load state" if slot is not None else ""), "⚠")

        busy(True, text or f"Changing the speed to {speed:g}x…")
        run_async(save_and_stop, stopped, lambda _e: stopped(False), owner=self)

    def launch_switch(self, game, paths, games) -> tuple[bool | None, str]:
        """Switch games: Eden - downloaded first when it isn't there yet (ok None: downloading)."""
        from gamingcrypt.emulation import eden
        from gamingcrypt.ui.tour import data_dir

        if not eden.available():
            installer = getattr(games, "eden_installer", None)
            if installer is None:
                return False, "The Switch emulator (Eden) isn't installed"
            _ok, message = self.download_then_launch(
                game, installer, "the Switch emulator (Eden)",
                "Couldn't download the Switch emulator (Eden) - no network?")
            return None, message
        from gamingcrypt.emulation import languages

        return eden.launch(game, paths, data_dir(), config_mod.cache_dir() / "logs",
                           language=languages.for_system(self.config, game.system))

    def _rom_started(self, game, games, ok: bool, message: str, emulator: str) -> tuple[bool, str]:
        if ok:
            log.info("starting %s (%s) with %s", game.name, game.system.id, emulator)
            if getattr(games, "play_log", None) is not None:
                games.play_log.start(game)  # Continue / Recently played, play time
            self.game_launched(game.appid)
        else:
            log.warning("%s: %s", emulator, message)
        return ok, message

    def download_core_then_launch(self, game, paths, core, fetch) -> tuple[bool, str]:
        """No core for the system yet: download it (libretro buildbot), then start the game."""
        from gamingcrypt.emulation.systems import short_name

        system = short_name(game.system.id)
        return self.download_then_launch(
            game, lambda: fetch(paths, game.system, core), f"the RetroArch core for {system}",
            f"Couldn't download a RetroArch core for {system} - no network? You can also add one with "
            "⬆ Add ROMs (cores folder)")

    def download_then_launch(self, game, work, what: str, failed: str) -> tuple[bool, str]:
        """Download what the game needs (core, emulator) behind the loading screen, then start it."""
        self.launch_overlay.show_for(game.name, game.appid, None, self.cover_loader(game.appid, game))
        self.launch_overlay.set_phase(f"Downloading {what}…")

        def done(path) -> None:
            if not self.launch_overlay.isVisible():
                return  # cancelled meanwhile
            if path is None:
                self.launch_overlay.hide()
                self.notify(failed, "⚠")
                return
            log.info("downloaded %s: %s", what, path)
            ok, message = self.launch_rom(game)
            if not ok:
                self.launch_overlay.hide()
                self.notify(message, "⚠")

        run_async(work, done, lambda _e: done(None), owner=self)
        return True, f"Downloading {what}…"

    def open_running_controls(self) -> None:
        """Quick menu: the running emulated game's button layout, over the game."""
        from gamingcrypt.emulation import layouts
        from gamingcrypt.ui import theme
        from gamingcrypt.ui.controls_page import ControlsPage

        games = self.shell.pages.get("Games") if self.shell else None
        appid = self.game_watcher.appid if self.game_watcher.active else None
        game = getattr(games, "rom_games", {}).get(appid) if appid is not None else None
        if game is None:
            self._quick_menu_closed()
            return
        old = getattr(self, "controls_overlay", None)
        if old is not None:
            old.deleteLater()
        page = self.controls_overlay = ControlsPage(
            layouts.Store(self.config, self.save), game.system.id, parent=self,
            note=f"Changes apply the next time {game.name} starts - save your state, quit and start it again.")
        page.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        page.closed.connect(self._running_controls_closed)
        page.setGeometry(self.rect())
        page.raise_()
        page.show()

    def _running_controls_closed(self) -> None:
        page, self.controls_overlay = getattr(self, "controls_overlay", None), None
        if page is not None:
            page.hide()
            page.deleteLater()
        self._quick_menu_closed()  # back to the game

    def open_states(self, mode: str) -> None:
        """Quick menu: the running emulated game's nine save states - "save" into one or "load" one."""
        from gamingcrypt.emulation import savestates
        from gamingcrypt.ui.save_states import SaveStatesPage

        games = self.shell.pages.get("Games") if self.shell else None
        rom, paths = self.running_rom(), getattr(games, "emulation", None)
        if rom is None or paths is None:
            self._quick_menu_closed()
            return
        page = SaveStatesPage(savestates.slots(paths, rom), mode, rom.name, parent=self)
        page.chosen.connect(lambda slot: self.state_chosen(rom, paths, mode, slot))
        self.show_menu_page(page)

    def state_chosen(self, rom, paths, mode: str, slot: int) -> None:
        from gamingcrypt.emulation import retroarch, savestates

        self.close_menu_page(reopen=False)
        self._quick_menu_closed()  # back into the game; RetroArch saves / loads right away
        if mode == "load":
            if retroarch.send(savestates.load_command(slot)):
                self.start_state_clock(savestates.read_played(savestates.state_file(paths, rom, slot)) or 0)
                self.notify("State loaded", "💾")
            return
        played = self.state_played()
        run_async(lambda: savestates.capture(paths, rom, slot, retroarch.send, played=played),
                  lambda ok: self.notify(*(("State saved", "💾") if ok else
                                           ("Couldn't save the state - this game can't be saved right now", "⚠"))),
                  lambda _e: self.notify("Couldn't save the state", "⚠"), owner=self,
                  pool=self._pause_pool)  # once the game goes on again

    def open_bluetooth(self) -> None:
        """Quick menu: pair / connect a controller or headphones while the game keeps running."""
        from gamingcrypt.ui.network_page import BluetoothPage

        settings = self.shell.pages.get("Settings") if self.shell else None
        section = getattr(settings, "bluetooth_section", None)
        self.show_menu_page(BluetoothPage(getattr(section, "bt", None), parent=self))

    def show_menu_page(self, page) -> None:
        """A page opened from the quick menu, over the game; leaving it goes back to the menu."""
        self.close_menu_page(reopen=False)
        self.menu_page = page
        page.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        page.closed.connect(self.close_menu_page)
        page.setGeometry(self.rect())
        page.raise_()
        page.show()

    def close_menu_page(self, reopen: bool = True) -> None:
        page, self.menu_page = getattr(self, "menu_page", None), None
        if page is None:
            return
        page.hide()
        page.deleteLater()
        if reopen:
            self.toggle_quick_menu()  # e.g. the headphones just connected: now in its outputs

    def game_over(self, appid: int | None = None, failed: bool = False) -> None:
        overlay = getattr(self, "game_volume_osd", None)
        if overlay is not None:
            overlay.dismiss()  # gamescope would keep drawing it over GamingCrypt
        keyboard = getattr(self, "game_keyboard", None)
        if keyboard is not None:
            keyboard.close_keyboard()  # (and the controller back)
        menu = getattr(self, "quick_menu", None)
        if menu is not None and menu.isVisible():
            menu.hide()  # the game is gone - nothing to go back to
        from gamingcrypt.ui.save_states import SaveStatesPage

        if isinstance(getattr(self, "menu_page", None), SaveStatesPage):
            self.close_menu_page(reopen=False)  # its game is gone
        self._speed_changing = False
        self._paused = self._chosen_speed = self._chosen_in_step = self._chosen_pad = None  # its game is gone
        # Pages showing "Starting <game>…" must not keep saying so after the game.
        if self.shell is not None and appid is not None:
            for page in self.shell.findChildren(QWidget):
                hook = getattr(page, "game_session_ended", None)
                if callable(hook):
                    hook(appid, failed)
        self.launch_overlay.hide()
        self.bring_to_front()
        from gamingcrypt.minecraft.library import is_minecraft_appid

        if is_minecraft_appid(appid):
            problem = self.minecraft_problem()  # (portablemc says why - e.g. signed out meanwhile)
            if problem:
                self.notify(problem, "⚠")

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
            mounted = self.unlocker_factory(self.config["unlock"]).is_mounted()
        except Exception:  # noqa: BLE001 - when in doubt: lock screen
            return False
        if mounted:
            from gamingcrypt import users

            from gamingcrypt import game_profiles

            user = users.enter(self.config, (self.verifier or {}).get("user"))  # who was logged in
            self.game_profiles = game_profiles.for_user(user)
        return mounted

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
        self.display_confirm.kept.connect(self.keep_display)
        self.display_confirm.reverted.connect(self._revert_display)
        args = mode.parse_display(mode.read_args())
        render = f"{args['width']}×{args['height']}" if "width" in args else "native"
        refresh = f"{args['refresh']} Hz" if "refresh" in args else "default"
        actual = mode.actual_mode()
        self.display_confirm.ask(f"Resolution {render}, refresh rate {refresh}"
                                 + (f" (screen: {actual})" if actual else ""))

    def keep_display(self) -> None:
        """Kept: from now on the resolution of whoever is logged in (set again at their login).
        Only now - one that was reverted (here, or by the session when gamescope couldn't start
        with it) used to come back at the next login."""
        from gamingcrypt.session import mode

        mode.confirm_display()
        native = mode.panel_size() or (1280, 800)
        current = mode.parse_display(mode.read_args())
        self.config["system"]["gaming_resolution"] = f"{current.get('width', native[0])}x{current.get('height', native[1])}"
        self.save(self.config)

    def _revert_display(self) -> None:
        from gamingcrypt.session import mode

        mode.revert_display()
        self.restart_gaming_mode()

    def power_action(self, kind: str) -> None:
        log.info("power action: %s", kind)
        if kind == "lock":
            self.panic_lock()
            return
        if kind == "sleep":
            if self.shell is not None:
                self.shell.power_menu.close_menu()
            self.go_to_sleep()
            return
        if self.input_service is not None:
            self.input_service.stop()  # give the real controller back first
        ok, message = self.power_runner(kind)
        if not ok:
            log.warning("power action %s failed: %s", kind, message)
            screen = self.stack.currentWidget()
            if isinstance(screen, LockScreen):
                screen.show_error(message)
            elif self.shell is not None:
                self.shell.power_menu.show_error(message)
            if self.input_service is not None:
                self.input_service.start()

    def load_other_systems(self, target) -> None:
        """Windows & co. for "Restart into …" (efibootmgr, once - the boot menu doesn't change)."""
        from gamingcrypt.system import boot

        cached = getattr(self, "_other_systems", None)
        if cached is not None:
            target.set_systems(cached)
            return

        def done(entries) -> None:
            self._other_systems = entries
            if shiboken6.isValid(target):
                target.set_systems(entries)

        choice = self.config.get("system", {}).get("other_os")  # asked by install.sh
        lister = self.systems_lister or boot.other_systems
        run_async(lambda: boot.chosen_systems(choice, lister), done, lambda _e: None, owner=self)

    systems_lister = None  # tests: a function returning the entries

    @staticmethod
    def power_runner(kind: str):
        from gamingcrypt.system.session import power_action

        return power_action(kind)

    def nav_root(self) -> QWidget:
        """Controller navigation stays inside the loading screen / power menu while shown."""
        from gamingcrypt.ui.modal import open_modal

        keyboard = getattr(self, "keyboard_overlay", None)
        if keyboard is not None and keyboard.isVisible():
            return keyboard  # (over everything)
        modal = open_modal(self)
        if modal is not None:
            return modal  # a question: answer it first
        if self.sleep_lock is not None and self.sleep_lock.isVisible():
            return self.sleep_lock
        if self.battery_warning.isVisible():
            return self.battery_warning
        for name in ("tour", "whats_new"):
            overlay = getattr(self, name, None)
            if overlay is not None and overlay.isVisible():
                return overlay
        confirm = getattr(self, "display_confirm", None)
        if confirm is not None and confirm.isVisible():
            return confirm
        menu = getattr(self, "quick_menu", None)
        if menu is not None and menu.isVisible():
            return menu
        for name in ("controls_overlay", "menu_page"):  # pages opened from the quick menu
            page = getattr(self, name, None)
            if page is not None and page.isVisible():
                return page
        if self.launch_overlay.isVisible():
            return self.launch_overlay
        menu = getattr(self.shell, "power_menu", None) if self.shell is not None else None
        if menu is not None and shiboken6.isValid(menu) and menu.isVisible():
            return menu
        from gamingcrypt.ui.options_popup import OptionsPopup

        options = next((p for p in self.findChildren(OptionsPopup) if p.isVisible()), None)
        if options is not None:
            return options  # a page's ⚙ Options
        return self

    def switch_tab(self, delta: int) -> None:
        if self.shell is not None and self.stack.currentWidget() is self.shell:
            self.shell.cycle_tab(delta)

    def resizeEvent(self, event):  # noqa: N802
        super().resizeEvent(event)
        self.launch_overlay.setGeometry(self.rect())
        if self.sleep_lock is not None:
            self.sleep_lock.setGeometry(self.rect())
        if self.battery_warning.isVisible():
            self.battery_warning.setGeometry(self.rect())
        if self.battery_edge.isVisible():
            self.battery_edge.setGeometry(self.rect())
        for name in ("tour", "whats_new"):
            overlay = getattr(self, name, None)
            if overlay is not None and overlay.isVisible():
                overlay.setGeometry(self.rect())

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
            if old is self.shell:
                self.shell = None  # locked: gone (its power menu etc. mustn't be asked any more)

    def show_setup(self, missing_volume: str = "") -> None:
        wizard = AuthSetupWizard(self.config, self.save, self.unlocker_factory, first_start=True,
                                 missing_volume=missing_volume)
        wizard.completed.connect(self.show_lock)
        wizard.cancelled.connect(self.show_shell)
        self._replace(wizard)
        self.screen_name = "setup"

    def show_lock(self) -> None:
        from gamingcrypt import users

        users.leave(self.config)  # locked: nobody's logged in
        self.apply_own_settings()  # (the lock screen looks as the admin has it)
        everyone = users.all_users(self.config)
        lock = LockScreen(self.unlocker_factory(self.config["unlock"]), self.config["unlock"]["method"],
                          users=everyone, user_id=self.config.get("last_user"),
                          unlocker_for=lambda user: users.unlocker_for(self.config, user, self.unlocker_factory))
        lock.unlocked.connect(self.show_shell)
        lock.power_requested.connect(self.power_action)
        lock.accepted.connect(lambda secret: self.logged_in(lock.user, secret))
        self.load_other_systems(lock)
        self._replace(lock)
        self.screen_name = "lock"

    def show_shell(self) -> None:
        pages = self.page_factory(self.config) if self.page_factory else {}
        games = pages.get("Games")
        pages.setdefault("Settings", SettingsTab(self.config, self.save, self.unlocker_factory, self.system,
                                                 steam_service=getattr(games, "service", None),
                                                 input_service=self.input_service,
                                                 restart_gaming=self.restart_gaming_mode,
                                                 admin_check=self.is_admin_code,
                                                 code_changed=self.remember_code))
        service = getattr(games, "service", None)
        if service is not None:
            # Steam windows (store, Steam's own dialogs) would open *behind* the fullscreen launcher.
            service.on_steam_ui = self.minimize_for_steam
            service.on_game_launch = self.game_launched
            service.on_big_picture = self.big_picture_opened
            if hasattr(games, "rom_launcher"):
                games.rom_launcher = self.launch_rom
            if hasattr(games, "windows_launcher"):
                games.windows_launcher = self.launch_windows
            if hasattr(games, "linux_launcher"):
                games.linux_launcher = self.launch_linux
            if hasattr(games, "minecraft_launcher"):
                games.minecraft_launcher = self.launch_minecraft
            if hasattr(games, "layout_store"):
                from gamingcrypt.emulation import layouts

                games.layout_store = layouts.Store(self.config, self.save)  # emulator controls
                games.shader_config = (self.config, self.save)  # emulator shaders per system
            if self.download_notifier is None and hasattr(service, "downloads"):
                from gamingcrypt.ui.download_notifier import DownloadNotifier

                self.download_notifier = DownloadNotifier(
                    service.downloads, lambda appid: any(g.appid == appid for g in service.installed_games()), self)
                self.download_notifier.message.connect(lambda icon, text: self.notify(text, icon))
        from gamingcrypt.session.mode import in_gaming_session

        for name in ("Movies", "Shows"):
            if hasattr(pages.get(name), "player_launcher"):
                pages[name].player_launcher = self.launch_movie
        from gamingcrypt import users

        # (what the admin locked for this user isn't there)
        self.shell = Shell(pages, show_hints=in_gaming_session(), locked=users.current(self.config).locked)
        self.shell.hint_bar.set_quick_menu(self.hotkeys["quick_menu"])
        self.use_own_steam_account(service)
        theme.on_change(self.retheme)
        self.shell.exit_requested.connect(self.desktop_mode)
        self.shell.power_requested.connect(self.power_action)
        settings = pages.get("Settings")
        storage_page = getattr(settings, "storage_page", None)
        if storage_page is not None and hasattr(games, "reload_roms"):
            storage_page.roms_changed.connect(games.reload_roms)  # removed in Settings -> Storage
        if hasattr(settings, "libraries_changed") and hasattr(games, "home"):
            settings.libraries_changed.connect(games.home.apply_libraries)
        if hasattr(settings, "hotkeys_changed"):
            settings.hotkeys_changed.connect(self.reload_hotkeys)
        self.shell.power_menu.sleep_button.setVisible(self.sleep_allowed())
        # The desktop has the whole drive and GamingCrypt's settings in the open: what's locked for
        # a user, their age, deleting games - none of it counts there. So it's the admin's.
        self.shell.power_menu.desktop_button.setVisible(users.current(self.config).admin)
        self.load_other_systems(self.shell.power_menu)
        self._replace(self.shell)
        self.screen_name = "shell"
        if self.welcome_enabled:
            QTimer.singleShot(0, self.show_welcome)
        self.watch_arrivals()
        if self.update_check_enabled and not getattr(self, "_update_checked", False):
            self._update_checked = True
            QTimer.singleShot(60_000, self.check_for_update)  # once per start, after things settled

    ARRIVALS_MS = 10_000  # how often the drive is looked at for new things

    def watch_arrivals(self) -> None:
        """New ROMs, games, movies, shows on the drive (network share, upload, copy): a notice,
        and the tab shows them - while the drive is unlocked."""
        from gamingcrypt.arrivals import Watcher

        mount_point = os.path.expanduser(self.config["unlock"].get("mount_point", "") or "")
        if not mount_point:
            return
        if getattr(self, "arrivals", None) is None or self.arrivals.drive != Path(mount_point):
            self.arrivals = Watcher(mount_point)
        if getattr(self, "arrivals_timer", None) is None:
            self.arrivals_timer = QTimer(self)
            self.arrivals_timer.timeout.connect(self.look_for_arrivals)
        self._looking_for_arrivals = False
        self.arrivals_timer.start(self.ARRIVALS_MS)
        self.look_for_arrivals()  # the first look learns what's there

    def look_for_arrivals(self) -> None:
        if self.screen_name != "shell" or getattr(self, "_looking_for_arrivals", False):
            return  # locked: the drive isn't there
        self._looking_for_arrivals = True
        watcher = self.arrivals

        def done(found) -> None:
            self._looking_for_arrivals = False
            if found:
                self.arrived(found)

        def failed(_exc) -> None:
            self._looking_for_arrivals = False

        run_async(watcher.poll, done, failed, owner=self)

    def arrived(self, found: list) -> None:
        from gamingcrypt.arrivals import describe

        log.info("arrived on the drive: %s", found)
        self.notify(describe(found), "⬇")
        pages = self.shell.pages if self.shell is not None else {}
        kinds = {a.kind for a in found}
        games = pages.get("Games")
        for kind, method in (("rom", "reload_roms"), ("windows", "reload_windows"), ("linux", "reload_linux")):
            if kind in kinds and hasattr(games, method):
                getattr(games, method)()
        for kind, name in (("movie", "Movies"), ("show", "Shows")):
            if kind in kinds and hasattr(pages.get(name), "reload"):
                pages[name].reload()

    def retheme(self) -> None:
        """Dark / light switched: what draws its own pictures draws them again."""
        if self.shell is None:
            return
        for widget in [self.shell, *self.shell.findChildren(QWidget)]:
            hook = getattr(widget, "retheme", None)
            if callable(hook) and widget is not self:
                hook()

    update_check_enabled = True  # tests switch it off

    def check_for_update(self) -> None:
        from gamingcrypt.system.updater import Updater

        def done(info) -> None:
            if info.available and info.behind:
                self.notify(f"Update available ({info.behind} changes) - Settings → System", "⬇")
            elif info.available:  # (pulled, but its install didn't get through)
                self.notify(f"{info.message} - Settings → System", "⬇")

        run_async(Updater().check, done, lambda _e: None, owner=self)

    # first start: tour; after an update: what's new ---------------------------------------
    welcome_enabled = True  # tests switch it off

    def show_welcome(self) -> None:
        from gamingcrypt.ui.tour import Tour, tour

        if self.config.get("tour_done"):
            self.show_news()
            return
        # in the words of this device: its quick menu button, what its power button does
        self.tour = Tour(self, tour(self.hotkeys["quick_menu"], self.config["system"].get("power_button", "menu")))
        self.tour.finished.connect(self._tour_done)
        self.tour.open()

    def _tour_done(self) -> None:
        self.config["tour_done"] = True
        self.save(self.config)
        self.show_news()

    def show_news(self) -> None:
        from gamingcrypt.ui.tour import WhatsNew, mark_news_read, news_file, read_news

        path = news_file()
        lines = read_news(path)
        if not lines:
            return
        self.whats_new = WhatsNew(self)
        self.whats_new.closed.connect(lambda: mark_news_read(path))
        self.whats_new.open_news(lines)


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

    libraries = config.setdefault("libraries", {"hidden": []})
    emulation_root = os.path.join(mount_point, "Emulation") if mount_point else ""
    windows_root = os.path.join(mount_point, "Windows Games") if mount_point else ""
    linux_root = os.path.join(mount_point, "Linux Games") if mount_point else ""
    minecraft_root = os.path.join(mount_point, "Minecraft") if mount_point else ""
    from gamingcrypt import users

    games = GamesTab(service, library_path=library_path, library_settings=libraries, emulation_root=emulation_root,
                     windows_root=windows_root, linux_root=linux_root, minecraft_root=minecraft_root,
                     user=users.current(config),
                     rate_games=users.current(config).admin and any(u.age is not None
                                                                    for u in users.all_users(config)))
    from gamingcrypt.emulation import cores, retroarch

    if retroarch.available():
        games.core_fetcher = cores.ensure  # missing cores come from the libretro buildbot
    from gamingcrypt.emulation import eden

    games.eden_installer = eden.install  # Switch: Eden is downloaded when a game first needs it
    from gamingcrypt.movies.metadata import languages_for
    from gamingcrypt.ui.movies_tab import MoviesTab

    from gamingcrypt.ui.shows_tab import ShowsTab

    languages = languages_for(config)
    pages = {"Games": games, "Downloads": DownloadsTab(service)}
    locked = users.current(config).locked  # by the admin, for this user: not even looked through
    if "Movies" not in locked:
        pages["Movies"] = MoviesTab(os.path.join(mount_point, "Movies") if mount_point else "", languages=languages)
    if "Shows" not in locked:
        pages["Shows"] = ShowsTab(os.path.join(mount_point, "Shows") if mount_point else "", languages=languages)
    return pages


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
    parser.add_argument("--list-boot-entries", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--other-os", metavar="ENTRY|none|auto", help=argparse.SUPPRESS)
    parser.add_argument("--diagnose", action="store_true",
                        help="print what GamingCrypt sees of Steam, your library and the volume")
    parser.add_argument("--volume-password", action="store_true",
                        help="print the real VeraCrypt password for your PIN/pattern (recovery)")
    args, qt_args = parser.parse_known_args(argv if argv is not None else sys.argv[1:])

    cfg_path = args.config or config_mod.config_path()
    cfg = config_mod.load_config(cfg_path)
    if args.volume_password:
        return print_volume_password(cfg)
    if args.list_boot_entries:  # install.sh: "Is there a second operating system?"
        from gamingcrypt.system import boot

        for entry in boot.other_systems():
            print(f"{entry.num}\t{entry.name}")
        return 0
    if args.other_os is not None:  # install.sh saves the answer
        value = args.other_os.strip().lower()
        cfg.setdefault("system", {})["other_os"] = None if value == "auto" else ("none" if value == "none"
                                                                               else value.upper())
        config_mod.save_config(cfg, Path(cfg_path))
        return 0
    if args.volume_key_devices:  # used by install.sh for its udev rule
        from gamingcrypt.input.evdev import find_volume_key_devices

        from gamingcrypt.input import hotkeys

        names = [device.name for device in find_volume_key_devices()]
        names += [b.device for b in hotkeys.load(cfg).values() if b.source == hotkeys.KEY and b.device]
        for name in dict.fromkeys(names):
            print(name)
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
    theme.apply(theme.from_config(cfg), app, theme.size_from_config(cfg))  # dark or light, text size (Settings -> Device)
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
    power_key = window.start_power_key()  # noqa: F841 - holds logind's power button
    navigator = GamepadNavigator(window, tab_switch=window.switch_tab)
    navigator.hotkey_filter = window.pad_hotkey  # e.g. Guide = quick menu, also in a game
    nav_source = NavSource(input_service, navigator.bridge.event.emit)
    nav_source.start()
    server = listen_for_activation(window.bring_to_front)  # noqa: F841 - keep alive
    window.check_display_change()
    hide_cursor_in_gaming_mode(app)
    window_ids = tag_windows_in_gaming_mode(app)  # noqa: F841 - keep alive
    reset_upscaling_in_gaming_mode(window)
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


def reset_upscaling_in_gaming_mode(window) -> None:
    """A game GamingCrypt upscaled may have outlived it (a crash): the second X server back at
    full size, the usual scaling."""
    from gamingcrypt.session.mode import in_gaming_session
    from gamingcrypt.system import upscaling

    if in_gaming_session() and upscaling.available():
        screen = window.screen_size()
        run_async(lambda: upscaling.stop(screen), owner=window, pool=window._power_pool)
    if in_gaming_session():  # the refresh rate from Settings: gamescope starts at the panel's own
        from gamingcrypt.session import mode
        from gamingcrypt.system import gamescope_ctl

        old = mode.take_out_refresh()  # once: it was one of gamescope's options
        if old and window.refresh_rates() and not window.default_refresh():
            window.config["system"]["gaming_refresh"] = old
            window.save(window.config)
        hz = window.default_refresh()
        run_async(lambda: gamescope_ctl.set_dynamic_refresh(hz), owner=window, pool=window._power_pool)


def tag_windows_in_gaming_mode(app):
    """Drop-down lists and other popups are windows of their own - see gamescope_windows."""
    from gamingcrypt.session.mode import in_gaming_session
    from gamingcrypt.ui.gamescope_windows import WindowAppIds

    if not in_gaming_session():
        return None
    return WindowAppIds(parent=app).install(app)


def hide_cursor_in_gaming_mode(app) -> bool:
    """gamescope draws the cursor of the window under a tap - a touch UI needs none."""
    from PySide6.QtCore import Qt

    from gamingcrypt.session.mode import in_gaming_session

    if not in_gaming_session():
        return False
    app.setOverrideCursor(Qt.CursorShape.BlankCursor)
    return True


if __name__ == "__main__":
    sys.exit(main())
