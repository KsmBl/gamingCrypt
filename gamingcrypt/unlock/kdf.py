"""Key derivation: harden the user's secret before it becomes the VeraCrypt password.

PINs and patterns have small key spaces. Running them through scrypt (memory-hard)
with a random per-volume salt means every brute-force guess costs ~256 MB of RAM
plus VeraCrypt's own PBKDF2 on top. The derived password is
``base64url(scrypt(secret, salt))`` (43 characters, within VeraCrypt's 64 limit).

The salt is not secret, but it is *required*: it lives in config.json, so back
that file up - without it the volume can only be opened with the derived
password (see ``gamingcrypt --volume-password``).
"""

from __future__ import annotations

import base64
import hashlib
import os
from typing import Callable

ALGORITHM = "scrypt"
DEFAULT_N = 2**18
DEFAULT_R = 8
DEFAULT_P = 1
DKLEN = 32
SALT_BYTES = 16


class KDFError(ValueError):
    pass


def new_params(n: int = DEFAULT_N, r: int = DEFAULT_R, p: int = DEFAULT_P,
               rng: Callable[[int], bytes] = os.urandom) -> dict:
    """Fresh parameters with a random salt (one per volume / password change)."""
    return {"algorithm": ALGORITHM, "salt": rng(SALT_BYTES).hex(), "n": n, "r": r, "p": p}


def describe(params: dict | None) -> str:
    if not params:
        return "none (legacy setup - reset authentication to enable)"
    n = int(params.get("n", 0))
    exponent = n.bit_length() - 1 if n and n & (n - 1) == 0 else None
    cost = f"N=2^{exponent}" if exponent is not None else f"N={n}"
    return f"{params.get('algorithm', '?')} ({cost}, {128 * n * int(params.get('r', 0)) // 2**20} MB)"


def derive_password(secret: str, params: dict | None) -> str:
    """Map the entered secret to the VeraCrypt password. ``None`` = no KDF (legacy)."""
    if not params:
        return secret
    if params.get("algorithm") != ALGORITHM:
        raise KDFError(f"unsupported key derivation {params.get('algorithm')!r}")
    try:
        salt = bytes.fromhex(params["salt"])
        n, r, p = int(params["n"]), int(params["r"]), int(params["p"])
    except (KeyError, TypeError, ValueError) as exc:
        raise KDFError(f"broken key derivation settings: {exc}") from exc
    if len(salt) < 8:
        raise KDFError("salt too short")
    key = hashlib.scrypt(secret.encode("utf-8"), salt=salt, n=n, r=r, p=p,
                         maxmem=2 * 128 * n * r + 2**20, dklen=DKLEN)
    return base64.urlsafe_b64encode(key).rstrip(b"=").decode("ascii")
