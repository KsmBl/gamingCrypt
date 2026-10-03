"""Small log file in the cache dir, so problems on the handheld can be traced."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup(cache_dir: Path) -> Path | None:
    path = Path(cache_dir) / "gamingcrypt.log"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(path, maxBytes=512 * 1024, backupCount=1)
    except OSError:
        return None
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger("gamingcrypt")
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    return path
