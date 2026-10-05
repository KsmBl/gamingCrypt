"""RetroArch cores downloaded automatically from the libretro buildbot.

A system that has games but no core gets its preferred core (the next one when that
isn't offered) - into the drive's cores/ folder, like an uploaded core. Downloads are
unzipped to a ".part" file and renamed when complete, and the same core is never
fetched twice at the same time.
"""

from __future__ import annotations

import io
import platform
import threading
import zipfile
from pathlib import Path
from typing import Callable

import requests

from gamingcrypt.emulation import retroarch
from gamingcrypt.emulation.library import EmulationPaths
from gamingcrypt.emulation.systems import System

BASE = "https://buildbot.libretro.com/nightly/linux/{arch}/latest/{core}_libretro.so.zip"
ARCHES = {"x86_64": "x86_64", "amd64": "x86_64", "aarch64": "aarch64", "arm64": "aarch64"}

_locks: dict[str, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock(core: str) -> threading.Lock:
    with _locks_guard:
        return _locks.setdefault(core, threading.Lock())


def url(core: str, machine: str | None = None) -> str | None:
    arch = ARCHES.get((machine or platform.machine()).lower())
    return BASE.format(arch=arch, core=core) if arch else None


def download(paths: EmulationPaths, core: str, get: Callable | None = None,
             machine: str | None = None) -> Path | None:
    """The core in cores/ (downloaded now, or already there); None: not offered or offline."""
    target = paths.cores / f"{core}_libretro.so"
    address = url(core, machine)
    if address is None:
        return None
    get = get or (lambda u: requests.get(u, timeout=120))
    with _lock(core):
        if target.exists():  # another thread was quicker
            return target
        try:
            response = get(address)
        except requests.RequestException:
            return None
        if response.status_code != 200:
            return None
        try:
            with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
                data = archive.read(target.name)
        except (zipfile.BadZipFile, KeyError):
            return None
        target.parent.mkdir(parents=True, exist_ok=True)
        part = target.with_name(target.name + ".part")
        part.write_bytes(data)
        part.replace(target)
        return target


def ensure(paths: EmulationPaths, system: System, wanted: str | None = None, get: Callable | None = None,
           machine: str | None = None) -> Path | None:
    """A core for the system: the installed one, else the first that can be downloaded."""
    found = retroarch.find_core(paths, system, wanted)
    if found is not None:
        return found
    for core in ((wanted,) if wanted else ()) + tuple(c for c in system.cores if c != wanted):
        path = download(paths, core, get, machine)
        if path is not None:
            return path
    return None


def missing(paths: EmulationPaths, systems) -> list[System]:
    """Systems (with games) that have no core yet."""
    return [s for s in systems if retroarch.find_core(paths, s) is None]
