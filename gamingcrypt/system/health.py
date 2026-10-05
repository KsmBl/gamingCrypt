"""Health check: everything GamingCrypt relies on, each with a fix.

Settings -> Health lists these; a red line names what's missing and how to get it
(nearly always: run ./install.sh again). All checks only look, nothing is changed.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

Runner = Callable[..., subprocess.CompletedProcess]
REINSTALL = "Run ./install.sh again"


@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""
    fix: str = ""
    optional: bool = False  # nice to have: shown, but not as an error


def _run(cmd: list[str], runner: Runner) -> subprocess.CompletedProcess | None:
    try:
        return runner(cmd, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None


class Health:
    """Every probe is replaceable (tests)."""

    def __init__(self, runner: Runner = subprocess.run, which: Callable[[str], str | None] = shutil.which,
                 exists: Callable[[str], bool] = os.path.exists, access: Callable[[str, int], bool] = os.access,
                 env: dict | None = None, helper: str | None = None, session_bin: str = "/usr/local/bin/gamingcrypt-session",
                 emulation_root: str | None = None):
        from gamingcrypt.unlock.veracrypt import DEFAULT_HELPER

        self.runner, self.which, self.exists, self.access = runner, which, exists, access
        self.env = os.environ if env is None else env
        self.helper = helper or DEFAULT_HELPER
        self.session_bin = session_bin
        self.emulation_root = emulation_root

    @property
    def gaming(self) -> bool:
        return self.env.get("GAMINGCRYPT_SESSION") == "1"

    # individual checks -------------------------------------------------------------------
    def veracrypt(self) -> Check:
        ok = bool(self.which("veracrypt"))
        return Check("VeraCrypt", ok, "installed" if ok else "not found",
                     "" if ok else "Install VeraCrypt (Arch: veracrypt)")

    def helper_allowed(self) -> Check:
        if not self.exists(self.helper):
            return Check("Unlock helper", False, "not installed", REINSTALL)
        result = _run(["sudo", "-n", "-l", self.helper], self.runner)
        ok = result is not None and result.returncode == 0
        if not ok:
            return Check("Unlock helper", False, "sudo rule missing", REINSTALL)
        from gamingcrypt.system import helper_status

        if helper_status.outdated(self.helper, self.runner, self.exists):
            return Check("Unlock helper", False, "outdated - new features (e.g. the network share) need the new one",
                         "Settings → Updates: finish the update with your password")
        return Check("Unlock helper", True, "allowed without password, up to date")

    def steam(self, root: Callable[[], object] | None = None) -> Check:
        found = root() if root else None
        if found is None and root is None:
            from gamingcrypt.steam.library import find_steam_root

            found = find_steam_root()
        return Check("Steam", found is not None, str(found) if found else "not found",
                     "" if found else "Install Steam and start it once")

    def session(self) -> Check:
        ok = self.exists(self.session_bin)
        return Check("Gaming mode", ok, "installed" if ok else "not installed",
                     "" if ok else "Run ./install.sh --session", optional=True)

    def steam_mode(self, cmdline: Callable[[], str | None] | None = None) -> Check:
        if not self.gaming:
            return Check("gamescope Steam mode", True, "only in gaming mode", optional=True)
        text = (cmdline or _gamescope_cmdline)() or ""
        args = text.split()
        ok = "-e" in args or "--steam" in args
        return Check("gamescope Steam mode", ok, "on" if ok else "off - Steam windows can cover GamingCrypt",
                     "" if ok else REINSTALL + " and restart gaming mode")

    def xprop(self) -> Check:
        ok = bool(self.which("xprop"))
        return Check("xprop", ok, "installed" if ok else "missing - windows can't be put in front",
                     "" if ok else "Install xorg-xprop (or run ./install.sh)")

    def emoji_font(self) -> Check:
        result = _run(["fc-list", ":charset=1f50b", "family"], self.runner) if self.which("fc-list") else None
        ok = result is not None and bool(result.stdout.strip())
        return Check("Icon font", ok, "emoji font installed" if ok else "icons show as squares",
                     "" if ok else "Install noto-fonts-emoji (or run ./install.sh)")

    def buttons(self, devices: Callable[[], list] | None = None) -> Check:
        if devices is None:
            from gamingcrypt.input.evdev import find_volume_key_devices as devices
        found = devices()
        if not found:
            return Check("Volume & power buttons", False, "no such buttons found", optional=True)
        readable = [d for d in found if self.access(d.path, os.R_OK)]
        ok = len(readable) == len(found)
        return Check("Volume & power buttons", ok, f"{len(readable)} of {len(found)} readable",
                     "" if ok else "Run ./install.sh --session, then restart")

    def uinput(self) -> Check:
        ok = self.access("/dev/uinput", os.W_OK)
        return Check("Controller mapping", ok, "virtual controller available" if ok else "/dev/uinput not writable",
                     "" if ok else REINSTALL + ", then log in again", optional=True)

    def power_limit(self, reader: Callable[[], object] | None = None) -> Check:
        if reader is None:
            from gamingcrypt.system.power import read_limit as reader
        limit = reader()
        if limit is None:
            return Check("Power limit", False, "not adjustable on this device", optional=True)
        allowed = self.exists(self.helper)
        return Check("Power limit", allowed, f"{limit.min_w}-{limit.max_w} W ({limit.source})",
                     "" if allowed else REINSTALL)

    def sleep(self) -> Check:
        result = _run(["busctl", "call", "org.freedesktop.login1", "/org/freedesktop/login1",
                       "org.freedesktop.login1.Manager", "CanSuspend"], self.runner)
        answer = result.stdout.strip() if result is not None and result.returncode == 0 else ""
        ok = '"yes"' in answer
        return Check("Sleep", ok, "allowed" if ok else (answer or "can't ask logind"),
                     "" if ok else "Your system doesn't allow suspend for this user", optional=True)

    def other_system(self, lister: Callable[[], list] | None = None) -> Check:
        if not self.which("efibootmgr"):
            return Check("Restart into Windows", False, "efibootmgr missing", "Install efibootmgr (or run ./install.sh)",
                         optional=True)
        if lister is None:
            from gamingcrypt.config import load_config
            from gamingcrypt.system.boot import chosen_systems

            choice = load_config().get("system", {}).get("other_os")
            if choice == "none":
                return Check("Restart into Windows", True, "no second system (install.sh --boot-setup to change)",
                             optional=True)
            lister = lambda: chosen_systems(choice)  # noqa: E731
        systems = lister()
        return Check("Restart into Windows", True,
                     ", ".join(s.name for s in systems) if systems else "no other system found", optional=True)

    def bios(self) -> Check:
        """BIOS files of the emulated systems that have games."""
        import os

        from gamingcrypt.emulation import bios
        from gamingcrypt.emulation.library import EmulationPaths, scan_all
        from gamingcrypt.emulation.systems import short_name

        root = self.emulation_root
        if root is None:
            from gamingcrypt.config import load_config

            mount = os.path.expanduser(load_config().get("unlock", {}).get("mount_point", "") or "")
            root = os.path.join(mount, "Emulation") if mount else ""
        if not root or not os.path.isdir(root):
            return Check("BIOS files", True, "no emulated games", optional=True)
        paths = EmulationPaths(root)
        statuses = bios.check_all(paths, scan_all(paths))
        if not statuses:
            return Check("BIOS files", True, "none needed for your games", optional=True)
        problems = [s for s in statuses if s.problem]
        detail = "\n".join(f"{short_name(s.system_id)}: {s.describe()}" for s in statuses)
        return Check("BIOS files", not problems, detail,
                     "" if not problems else "Add them to the bios folder (Games → ⬆ Add ROMs)")

    def run(self) -> list[Check]:
        checks = []
        for probe in (self.veracrypt, self.helper_allowed, self.steam, self.session, self.steam_mode, self.xprop,
                      self.emoji_font, self.buttons, self.uinput, self.power_limit, self.sleep, self.other_system,
                      self.bios):
            try:
                checks.append(probe())
            except Exception as exc:  # noqa: BLE001 - one broken probe must not hide the others
                checks.append(Check(probe.__name__.replace("_", " ").capitalize(), False, f"check failed: {exc}"))
        return checks


def _gamescope_cmdline() -> str | None:
    from gamingcrypt.session.mode import gamescope_pid

    pid = gamescope_pid()
    if pid is None:
        return None
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace")
    except OSError:
        return None
