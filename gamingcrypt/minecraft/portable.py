"""portablemc - the launcher that installs and starts Minecraft - driven through its command line
in its machine-readable output (a line each: what it is, then its values, tab separated).

Signing in is Microsoft's device code: portablemc asks for a code, the player opens
microsoft.com/link on a phone (a QR code on screen) and types it in - no keyboard needed on the
handheld. portablemc keeps the account in a file of its own: one per GamingCrypt user, on the
encrypted drive (<drive>/Minecraft/.accounts).
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from gamingcrypt.minecraft.library import ACCOUNTS, SHARED, MinecraftInstance

LINK = "https://www.microsoft.com/link"
PACKAGE = "portablemc>=5.0.6,<6"  # (its machine output is what's read here)
# Mojang's own Java for the version first (the one it's made for), the system's when there's none
JVM_POLICY = "mojang-then-system"
ERRORS = {"error_auth_declined": "Signing in was declined",
          "error_auth_timed_out": "Signing in took too long - try again",
          "error_auth_does_not_own_game": "This Microsoft account doesn't own Minecraft: Java Edition",
          "error_account_not_found": "Not signed in any more - sign in again",
          "error_auth_outdated_token": "Signed in too long ago - sign in again",
          "error_version_not_found": "This Minecraft version doesn't exist",
          "error_download": "A download failed - is the device online?",
          "error_jvm_not_found": "No Java found for this Minecraft version"}


def available() -> bool:
    return importlib.util.find_spec("portablemc") is not None or shutil.which("portablemc") is not None


def ensure(run=subprocess.run) -> tuple[bool, str]:
    """portablemc into GamingCrypt's own Python, the first time Minecraft is opened (a prebuilt
    package - where there's none for this device, there's no Minecraft)."""
    if available():
        return True, ""
    try:
        done = run([sys.executable, "-m", "pip", "install", "--quiet", "--only-binary=:all:", PACKAGE],
                   capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"Minecraft's launcher (portablemc) could not be installed: {exc}"
    importlib.invalidate_caches()
    if done.returncode != 0 or not available():
        last = (done.stderr or done.stdout or "").strip().splitlines()[-1:] or [""]
        return False, f"Minecraft's launcher (portablemc) could not be installed - is the device online? {last[0]}"
    return True, ""


def base_command() -> list[str]:
    if importlib.util.find_spec("portablemc") is not None:
        return [sys.executable, "-m", "portablemc"]
    return ["portablemc"]


def parse(line: str) -> tuple[str, list[str]]:
    """("download", ["3/10", …]) - values unescaped (portablemc writes \\t and \\n in them)."""
    kind, *values = line.rstrip("\n").split("\t")
    return kind, [v.replace("\\t", "\t").replace("\\n", "\n") for v in values]


def error_text(kind: str, values: list[str]) -> str:
    known = ERRORS.get(kind)
    if known is not None:
        return known
    detail = " ".join(v for v in values if v)
    return f"Minecraft: {kind.removeprefix('error_').replace('_', ' ')}" + (f" ({detail})" if detail else "")


@dataclass(frozen=True)
class Account:
    username: str
    uuid: str


@dataclass(frozen=True)
class Paths:
    root: Path  # <drive>/Minecraft
    user: str = ""  # the GamingCrypt user ("" - the admin)

    @property
    def shared(self) -> Path:
        return self.root / SHARED

    @property
    def accounts(self) -> Path:
        return self.root / ACCOUNTS / f"{self.user or 'admin'}.json"

    def command(self, *args: str) -> list[str]:
        return [*base_command(), "--main-dir", str(self.shared), "--msa-db-file", str(self.accounts),
                "--output", "machine", *args]

    def prepare(self) -> None:
        self.shared.mkdir(parents=True, exist_ok=True)
        self.accounts.parent.mkdir(parents=True, exist_ok=True)


def rows(lines: list[str]) -> list[list[str]]:
    """A table's rows (after its header and "sep" line)."""
    found, header = [], True
    for line in lines:
        kind, values = parse(line)
        if kind == "sep":
            header = False
        elif kind == "row" and not header:
            found.append(values)
    return found


def accounts(paths: Paths, run=subprocess.run) -> list[Account]:
    paths.prepare()
    try:
        done = run(paths.command("auth", "list"), capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return []
    return [Account(r[0], r[1]) for r in rows(done.stdout.splitlines()) if len(r) >= 2]


def forget(paths: Paths, account: Account, run=subprocess.run) -> bool:
    try:
        done = run(paths.command("auth", "forget", "-u", account.username), capture_output=True, text=True,
                   timeout=30)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def releases(paths: Paths, run=subprocess.run) -> list[str]:
    """Every Minecraft release, the newest first (Mojang's list - needs the network)."""
    paths.prepare()
    try:
        done = run(paths.command("search"), capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return []
    return [r[0] for r in rows(done.stdout.splitlines()) if len(r) >= 2 and r[1].rstrip("*") == "release"]


class Login:
    """Signing in: on_code(link, code) as soon as Microsoft gave one, on_done(ok, message) at the
    end (from a thread of its own)."""

    def __init__(self, paths: Paths, on_code: Callable[[str, str], None], on_done: Callable[[bool, str], None],
                 popen=subprocess.Popen):
        self.paths, self.on_code, self.on_done, self.popen = paths, on_code, on_done, popen
        self.process = None
        self.cancelled = False

    def start(self) -> None:
        threading.Thread(target=self._run, name="gamingcrypt-minecraft-login", daemon=True).start()

    def _run(self) -> None:
        try:
            self.paths.prepare()
            self.process = self.popen(self.paths.command("auth", "login"), stdout=subprocess.PIPE,
                                      stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True)
        except OSError as exc:
            self.on_done(False, f"portablemc didn't start: {exc}")
            return
        error = ""
        for line in self.process.stdout:
            kind, values = parse(line)
            if kind == "auth_device_code" and len(values) >= 2:
                self.on_code(values[0] or LINK, values[1])
            elif kind.startswith("error_") and not error:
                error = error_text(kind, values)
        code = self.process.wait()
        if self.cancelled:
            self.on_done(False, "")
        elif code == 0 and not error:
            self.on_done(True, "Signed in")
        else:
            self.on_done(False, error or "Signing in didn't work - try again")

    def cancel(self) -> None:
        self.cancelled = True
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()


def version_spec(instance: MinecraftInstance) -> str:
    return instance.version


def installed_version(lines: list[str]) -> str:
    """The version an install resolved to ("release" -> "1.21.4")."""
    found = ""
    for line in lines:
        kind, values = parse(line)
        if kind == "loaded_hierarchy" and values:
            found = values[0]
    return found


def install(paths: Paths, instance: MinecraftInstance, progress: Callable[[float, str], None],
            popen=subprocess.Popen) -> tuple[bool, str, str]:
    """Download everything it needs (portablemc's dry run: all but starting it) -> (ok, message,
    the version installed). progress(0..1, what) as it goes."""
    paths.prepare()
    try:
        process = popen(paths.command("start", "--dry", "--jvm-policy", JVM_POLICY, "--mc-dir", str(instance.path),
                                      version_spec(instance)),
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, text=True)
    except OSError as exc:
        return False, f"portablemc didn't start: {exc}", ""
    lines, error = [], ""
    for line in process.stdout:
        lines.append(line)
        kind, values = parse(line)
        if kind == "download" and len(values) >= 2:
            progress(_fraction(values), "Downloading Minecraft…")
        elif kind == "load_jvm":
            progress(0.0, "Getting Java…")
        elif kind.startswith("error_") and not error:
            error = error_text(kind, values)
    code = process.wait()
    if code != 0 or error:
        return False, error or "Installing didn't work", ""
    return True, "Installed", installed_version(lines)


def _fraction(values: list[str]) -> float:
    """From "count/total" and "bytes/total bytes" (the total size isn't always known)."""
    try:
        done, total = (int(v) for v in values[1].split("/"))
        if total > 0:
            return min(1.0, done / total)
        done, total = (int(v) for v in values[0].split("/"))
        return min(1.0, done / total) if total > 0 else 0.0
    except (ValueError, IndexError):
        return 0.0


def launch_command(paths: Paths, instance: MinecraftInstance, account: Account) -> list[str]:
    """Start it - nothing is downloaded any more (installed first), only checked."""
    return paths.command("start", "--jvm-policy", JVM_POLICY, "--mc-dir", str(instance.path), "-a",
                         "-u", account.username, instance.installed or version_spec(instance))
