"""Turn the different unlock inputs (PIN, password, pattern) into a VeraCrypt password.

The secret is used *verbatim* as the volume password, so the volume has to be
created with exactly that string:

* PIN      -> the digits, e.g. ``"482916"``
* password -> the text as typed
* pattern  -> the visited dots of the 3x3 grid numbered 1-9 (row by row),
              e.g. an "L" shape top-left -> bottom-right is ``"14789"``
"""

from __future__ import annotations

MIN_PIN_LENGTH = 4
MIN_PATTERN_LENGTH = 4
GRID_SIZE = 3


class InvalidSecret(ValueError):
    pass


def pin_to_secret(pin: str) -> str:
    if not pin.isdigit():
        raise InvalidSecret("PIN may only contain digits")
    if len(pin) < MIN_PIN_LENGTH:
        raise InvalidSecret(f"PIN needs at least {MIN_PIN_LENGTH} digits")
    return pin


def password_to_secret(password: str) -> str:
    if not password:
        raise InvalidSecret("Password must not be empty")
    return password


def pattern_to_secret(nodes: list[int]) -> str:
    """``nodes`` are 0-based grid indices in the order they were touched."""
    if len(nodes) < MIN_PATTERN_LENGTH:
        raise InvalidSecret(f"Connect at least {MIN_PATTERN_LENGTH} dots")
    if len(set(nodes)) != len(nodes):
        raise InvalidSecret("Each dot may only be used once")
    if any(n < 0 or n >= GRID_SIZE * GRID_SIZE for n in nodes):
        raise InvalidSecret("Invalid dot in pattern")
    return "".join(str(n + 1) for n in nodes)
