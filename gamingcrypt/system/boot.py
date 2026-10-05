"""Other installed systems (e.g. Windows) and restarting into one of them once.

GRUB can't be used by touch or controller, so the choice is made here: the UEFI
``BootNext`` variable makes the firmware start that system's own boot loader on
the next boot only - independent of the GRUB configuration. Listing the entries
works without root; setting BootNext goes through the GamingCrypt helper.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Callable

Runner = Callable[..., subprocess.CompletedProcess]
DEFAULT_HELPER = "/usr/local/lib/gamingcrypt/veracrypt-helper"
ENTRY = re.compile(r"^Boot([0-9A-Fa-f]{4})(\*?)\s+(.*?)\t(.*)$")


@dataclass(frozen=True)
class BootEntry:
    num: str
    label: str
    path: str
    active: bool = True

    @property
    def windows(self) -> bool:
        return "bootmgfw.efi" in self.path.lower()

    @property
    def on_disk(self) -> bool:
        """Starts a boot loader file from a disk (not USB / network / CD firmware entries)."""
        return "HD(" in self.path and "\\efi\\" in self.path.lower()

    @property
    def name(self) -> str:
        return "Windows" if self.windows else self.label


def parse(text: str) -> tuple[str | None, list[BootEntry]]:
    """``efibootmgr`` output -> (BootCurrent, entries)."""
    current, entries = None, []
    for line in text.splitlines():
        if line.startswith("BootCurrent:"):
            current = line.split(":", 1)[1].strip().upper()
            continue
        match = ENTRY.match(line)
        if match:
            num, star, label, path = match.groups()
            entries.append(BootEntry(num.upper(), label.strip(), path.strip(), bool(star)))
    return current, entries


def other_systems(runner: Runner = subprocess.run,
                  which: Callable[[str], str | None] = shutil.which) -> list[BootEntry]:
    """Bootable systems on the disks other than the running one. Empty without UEFI."""
    if not which("efibootmgr"):
        return []
    try:
        result = runner(["efibootmgr"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return []
    if result.returncode != 0:
        return []
    current, entries = parse(result.stdout)
    return [e for e in entries if e.active and e.on_disk and e.num != current]


def reboot_into(entry: BootEntry, runner: Runner = subprocess.run, helper: str = DEFAULT_HELPER,
                exists: Callable[[str], bool] | None = None) -> tuple[bool, str]:
    if not (exists or os.path.exists)(helper):
        return False, "Run install.sh to allow restarting into another system"
    try:
        result = runner(["sudo", "-n", helper, "boot-next", entry.num], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, f"Could not choose {entry.name}: {exc}"
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "").strip().removeprefix("Error: gamingcrypt helper: ")
        return False, message or f"Could not choose {entry.name} for the next start"
    from gamingcrypt.system.session import power_action

    ok, message = power_action("restart", runner)
    return ok, f"Restarting into {entry.name}…" if ok else message
