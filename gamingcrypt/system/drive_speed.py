"""How fast a USB stick, USB drive or SD card is - looked at once, the first time it's put in.

Two things: the USB port it's in (from the system: a USB 3 stick in a USB 2 port is a USB 2 stick),
and how fast it writes (a short test file, fsynced, then deleted). A slow one gets a notice: its
games load slowly. The result is kept with the remembered sticks, on the encrypted drive.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

SYS = Path("/sys")
TEST_BYTES = 32 * 1024 ** 2
CHUNK = 4 * 1024 ** 2
TEST_NAME = ".gamingcrypt-speed-test"
SLOW_MB_S = 15.0  # writes slower than this: games load slowly from it
SLOW_USB = ("1.1", "2.0")
USB_VERSIONS = {1.5: "1.1", 12: "1.1", 480: "2.0", 5000: "3.0", 10000: "3.1", 20000: "3.2", 40000: "4"}


def usb_version(disk: str, sys_root: Path | None = None) -> str | None:
    """"2.0", "3.0" … - the speed the stick talks to the device at (its port and itself). None: not on
    USB (an SD card slot), or not known."""
    if not disk:
        return None
    sys_root = SYS if sys_root is None else sys_root
    try:
        device = (sys_root / "block" / Path(disk).name / "device").resolve()
    except OSError:
        return None
    for folder in [device, *device.parents]:
        speed = folder / "speed"
        if (folder / "idVendor").exists() and speed.is_file():
            try:
                value = float(speed.read_text().strip())
            except (OSError, ValueError):
                return None
            return USB_VERSIONS.get(value) or ("2.0" if value <= 480 else "3.0")
        if folder == sys_root or folder.parent == folder:
            break
    return None


def write_speed(folder: Path, size: int | None = None, clock=time.monotonic) -> float | None:
    """MB/s writing a test file there (on the drive for good: fsync), deleted again. None: it can't."""
    size = TEST_BYTES if size is None else size
    test = Path(folder) / TEST_NAME
    chunk = os.urandom(min(CHUNK, size))  # (not zeros: some sticks compress them)
    try:
        started = clock()
        with open(test, "wb") as f:
            written = 0
            while written < size:
                f.write(chunk[:size - written])
                written += min(len(chunk), size - written)
            f.flush()
            os.fsync(f.fileno())
        took = max(clock() - started, 1e-6)
    except OSError:
        return None
    finally:
        try:
            test.unlink(missing_ok=True)
        except OSError:
            pass
    return round(size / 1024 ** 2 / took, 1)


def measure(drive, sys_root: Path | None = None, size: int | None = None) -> dict:
    """{"usb": "3.0" | None, "write": MB/s | None, "at": when} - no write test on one that can't be
    written to."""
    usb = usb_version(getattr(drive, "disk", ""), sys_root)
    write = None if getattr(drive, "read_only", "") else write_speed(Path(drive.mount), size)
    return {"usb": usb, "write": write, "at": int(time.time())}


def slow(result: dict | None) -> bool:
    if not result:
        return False
    write = result.get("write")
    return result.get("usb") in SLOW_USB or (write is not None and write < SLOW_MB_S)


def describe(result: dict | None) -> str:
    """"USB 3.0 · writes 95 MB/s" - what's known."""
    if not result:
        return ""
    parts = []
    if result.get("usb"):
        parts.append(f"USB {result['usb']}")
    if result.get("write") is not None:
        parts.append(f"writes {result['write']:.0f} MB/s")
    text = "  ·  ".join(parts)
    return f"{text}  ·  🐢 slow" if slow(result) and text else text


def why_slow(name: str, result: dict) -> str:
    if result.get("usb") in SLOW_USB:
        return (f"{name} is in a USB {result['usb']} port (or is a USB {result['usb']} stick): its games load "
                "slowly. A USB 3 port - often blue - is a lot faster")
    return f"{name} writes only {result.get('write', 0):.0f} MB/s: its games load slowly"
