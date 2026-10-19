"""A virtual keyboard (uinput) for the on-screen keyboard over a game: what's typed on it
reaches the game in front as real key presses.

Keys are sent as on a US keyboard (gamescope's layout unless the session sets another).
"""

from __future__ import annotations

import time
from typing import Callable

from gamingcrypt.input import evdev as e

NAME = "GamingCrypt Virtual Keyboard"
VENDOR, PRODUCT = 0x1209, 0x6743  # not the virtual controller's: games must not take it for one

KEY_ESC, KEY_BACKSPACE, KEY_TAB, KEY_ENTER, KEY_SPACE = 1, 14, 15, 28, 57
KEY_LEFTCTRL, KEY_LEFTSHIFT, KEY_LEFTALT = 29, 42, 56
KEY_HOME, KEY_UP, KEY_PAGEUP, KEY_LEFT, KEY_RIGHT, KEY_END, KEY_DOWN, KEY_PAGEDOWN = 102, 103, 104, 105, 106, \
    107, 108, 109
KEY_INSERT, KEY_DELETE = 110, 111
F_KEYS = [59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 87, 88]  # F1 - F12

_PLAIN = {**{c: code for c, code in zip("1234567890", range(2, 12))},
          **{c: code for c, code in zip("qwertyuiop", range(16, 26))},
          **{c: code for c, code in zip("asdfghjkl", range(30, 39))},
          **{c: code for c, code in zip("zxcvbnm", range(44, 51))},
          "-": 12, "=": 13, "[": 26, "]": 27, ";": 39, "'": 40, "`": 41, "\\": 43, ",": 51, ".": 52, "/": 53,
          " ": KEY_SPACE, "\t": KEY_TAB, "\n": KEY_ENTER}
_SHIFTED = {"!": "1", "@": "2", "#": "3", "$": "4", "%": "5", "^": "6", "&": "7", "*": "8", "(": "9", ")": "0",
            "_": "-", "+": "=", "{": "[", "}": "]", ":": ";", '"': "'", "~": "`", "|": "\\", "<": ",", ">": ".",
            "?": "/"}

# by name, for the keys the on-screen keyboard has besides letters
NAMED = {"Esc": KEY_ESC, "Tab": KEY_TAB, "Enter": KEY_ENTER, "Backspace": KEY_BACKSPACE, "Space": KEY_SPACE,
         "Home": KEY_HOME, "End": KEY_END, "PgUp": KEY_PAGEUP, "PgDn": KEY_PAGEDOWN, "Ins": KEY_INSERT,
         "Del": KEY_DELETE, "Up": KEY_UP, "Down": KEY_DOWN, "Left": KEY_LEFT, "Right": KEY_RIGHT,
         **{f"F{n}": code for n, code in enumerate(F_KEYS, 1)}}
MODIFIERS = {"Ctrl": KEY_LEFTCTRL, "Alt": KEY_LEFTALT, "Shift": KEY_LEFTSHIFT}
ALL_KEYS = sorted({*_PLAIN.values(), *NAMED.values(), *MODIFIERS.values()})
HOLD_S = 0.012  # between press and release: games that look once a frame still see it


def key_for(char: str) -> tuple[int, bool] | None:
    """(key code, with Shift) for a character - None for one a US keyboard hasn't got."""
    if char in _PLAIN:
        return _PLAIN[char], False
    if char.lower() in _PLAIN and char.isalpha():
        return _PLAIN[char.lower()], True
    if char in _SHIFTED:
        return _PLAIN[_SHIFTED[char]], True
    return None


def presses(code: int, modifiers: tuple[int, ...] = ()) -> tuple[list, list]:
    """The events to press a key with modifiers held - and to let go of all again."""
    down = [(e.EV_KEY, m, 1) for m in modifiers] + [(e.EV_KEY, code, 1), (e.EV_SYN, e.SYN_REPORT, 0)]
    up = [(e.EV_KEY, code, 0)] + [(e.EV_KEY, m, 0) for m in reversed(modifiers)] + [(e.EV_SYN, e.SYN_REPORT, 0)]
    return down, up


class VirtualKeyboard:
    """Opened at the first key (uinput needs no permission more than the virtual controller's).

    Has the on-screen keyboard's text-field interface too (insert / backspace), so it types
    into the game like into a field."""

    def __init__(self, make_uinput: Callable[[], e.UInput] | None = None, pause: Callable[[float], None] = time.sleep):
        self.make_uinput = make_uinput or (lambda: e.UInput(NAME, keys=ALL_KEYS, axes=[], vendor=VENDOR,
                                                            product=PRODUCT))
        self.pause = pause
        self.device = None
        self.error = ""
        self.held: set[str] = set()  # "Ctrl" / "Alt" for the next key (on-screen toggles)

    def _open(self) -> bool:
        if self.device is None:
            try:
                self.device = self.make_uinput()
            except OSError as exc:
                self.error = str(exc.strerror or exc)
                return False
        return True

    def press(self, code: int, shift: bool = False) -> bool:
        if not self._open():
            return False
        modifiers = tuple(MODIFIERS[m] for m in ("Ctrl", "Alt") if m in self.held)
        modifiers += (KEY_LEFTSHIFT,) if shift else ()
        down, up = presses(code, modifiers)
        try:
            self.device.emit(down)
            self.pause(HOLD_S)
            self.device.emit(up)
        except OSError as exc:
            self.error = str(exc.strerror or exc)
            self.close()
            return False
        self.held.clear()  # (one key each, as sticky keys)
        return True

    def key(self, name: str) -> bool:
        return name in NAMED and self.press(NAMED[name])

    def insert(self, text: str) -> None:
        for char in text:
            found = key_for(char)
            if found is not None:
                self.press(*found)

    def backspace(self) -> None:
        self.press(KEY_BACKSPACE)

    def close(self) -> None:
        if self.device is not None:
            self.device.close()
            self.device = None
