"""What a list was filtered and sorted by, kept across restarts (view-state.json next to the
config): the Games tab's genre / platform / year / order, the Movies and Shows filters."""

from __future__ import annotations

import json
from pathlib import Path


def default_path() -> Path:
    from gamingcrypt.config import config_dir

    return config_dir() / "view-state.json"


def load(name: str, path: Path | None = None) -> dict:
    try:
        data = json.loads((path or default_path()).read_text())
    except (OSError, ValueError):
        return {}
    value = data.get(name) if isinstance(data, dict) else None
    return value if isinstance(value, dict) else {}


def save(name: str, value: dict, path: Path | None = None) -> None:
    path = path or default_path()
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            data = {}
    except (OSError, ValueError):
        data = {}
    data[name] = value
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1))
        tmp.replace(path)
    except OSError:
        pass  # only a convenience


def restore(combo, value) -> None:
    """Choose ``value`` in the combo box - or add it while its choices aren't there yet (genres
    come in the background): it's chosen as soon as they are."""
    if value in (None, ""):
        return
    index = combo.findData(value)
    if index < 0:
        combo.addItem(str(value), value)
        index = combo.count() - 1
    combo.setCurrentIndex(index)
