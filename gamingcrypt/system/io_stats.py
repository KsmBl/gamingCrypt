"""Network and disk counters for the Downloads tab (download speed, disk speed, free space)."""

from __future__ import annotations

import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass
class IoSample:
    time: float
    net_rx: int  # bytes received on all interfaces except loopback (cumulative)
    disk_written: int | None  # bytes written to the library's block device (cumulative)
    free: int | None  # free bytes on the library's filesystem


def net_rx_bytes(proc: Path = Path("/proc")) -> int:
    total = 0
    try:
        lines = (proc / "net/dev").read_text().splitlines()[2:]
    except OSError:
        return 0
    for line in lines:
        name, _, data = line.partition(":")
        if name.strip() == "lo" or not data.split():
            continue
        total += int(data.split()[0])
    return total


def block_device(path: str, sys_root: Path = Path("/sys")) -> str | None:
    """Kernel name (e.g. nvme0n1p2, dm-1) of the device holding ``path``."""
    try:
        st = os.stat(path)
    except OSError:
        return None
    link = sys_root / "dev/block" / f"{os.major(st.st_dev)}:{os.minor(st.st_dev)}"
    try:
        return os.path.basename(os.path.realpath(link)) if link.exists() else None
    except OSError:
        return None


def disk_written_bytes(device: str, proc: Path = Path("/proc")) -> int | None:
    try:
        for line in (proc / "diskstats").read_text().splitlines():
            fields = line.split()
            if len(fields) > 9 and fields[2] == device:
                return int(fields[9]) * 512  # sectors written
    except (OSError, ValueError):
        pass
    return None


def sample(library: str | None, proc: Path = Path("/proc"), sys_root: Path = Path("/sys"),
           clock=time.monotonic) -> IoSample:
    written = free = None
    if library:
        device = block_device(library, sys_root)
        if device:
            written = disk_written_bytes(device, proc)
        try:
            free = shutil.disk_usage(library).free
        except OSError:
            free = None
    return IoSample(clock(), net_rx_bytes(proc), written, free)


def rate(old: IoSample | None, new: IoSample, field: str) -> float | None:
    if old is None:
        return None
    a, b = getattr(old, field), getattr(new, field)
    elapsed = new.time - old.time
    if a is None or b is None or elapsed <= 0 or b < a:
        return None
    return (b - a) / elapsed
