"""Check the unlock code again (lock after sleep) without mounting anything.

After a successful unlock a keyed hash of the code is kept - in memory and in a
0600 file in the runtime dir (gone at reboot), so a self-restarted GamingCrypt
can lock too. The code itself is never stored.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from pathlib import Path

from gamingcrypt.unlock.veracrypt import UnlockResult


def make(secret: str) -> dict:
    key = secrets.token_bytes(32)
    return {"key": key.hex(), "digest": hmac.new(key, secret.encode(), hashlib.sha256).hexdigest()}


def check(verifier: dict, secret: str) -> bool:
    try:
        key = bytes.fromhex(verifier["key"])
        expected = verifier["digest"]
    except (KeyError, ValueError, TypeError):
        return False
    return hmac.compare_digest(hmac.new(key, secret.encode(), hashlib.sha256).hexdigest(), expected)


def save(verifier: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(verifier, fh)


def load(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


class VerifyUnlocker:
    """Stands in for the VeraCrypt unlocker on the after-sleep lock screen."""

    configured = True

    def __init__(self, verifier: dict):
        self.verifier = verifier

    def unlock(self, secret: str) -> UnlockResult:
        if check(self.verifier, secret):
            return UnlockResult(True, "")
        return UnlockResult(False, "Wrong code")
