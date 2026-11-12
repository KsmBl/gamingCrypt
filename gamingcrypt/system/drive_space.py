"""How much room is left on the encrypted games drive - it's a container of a fixed size: when it's
full, downloads and saves fail. Said before a download that won't fit, and once when it's nearly full."""

from __future__ import annotations

import shutil
from pathlib import Path

GiB = 1024 ** 3
LOW_BYTES = 10 * GiB  # less than that left: about one bigger game


def free(path: str | Path | None) -> int | None:
    if not path:
        return None
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return None


def is_low(free_bytes: int | None) -> bool:
    return free_bytes is not None and free_bytes < LOW_BYTES


def fits(need: int | None, free_bytes: int | None) -> bool:
    """Unknown (no size, no drive): it's not said that it doesn't."""
    return not need or free_bytes is None or need <= free_bytes
