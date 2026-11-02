"""Sounds and rumble: a soft tick when the controller moves the highlight, a short rumble when a
game starts or something goes wrong. Both can be switched off (Settings -> Device -> Appearance).

The sounds are made here, written once to the cache folder and played by whatever plays sounds on
this device (pw-play, paplay, aplay) - QtMultimedia isn't everywhere the distribution's PySide6 is.
Nothing happens until the app calls configure(): not in tests, and never while a game is in front.
"""

from __future__ import annotations

import math
import shutil
import struct
import subprocess
import time
import wave
from pathlib import Path
from typing import Callable

RATE = 44100
ATTACK_S = 0.004  # no click at the start
VERSION = 1  # another sound under the same name: a new file

# name: (notes (Hz, ms), how loud 0-1) - quiet, it's next to the game's own sound
SOUNDS = {
    "move": (((1320, 28),), 0.08),
    "tab": (((880, 25), (1100, 35)), 0.10),
    "select": (((880, 40), (1320, 70)), 0.13),
    "back": (((990, 40), (660, 70)), 0.11),
    "launch": (((523, 60), (659, 60), (784, 60), (1047, 170)), 0.16),
    "error": (((196, 90), (165, 150)), 0.18),
}
# name: (strong motor, weak motor (0-65535), ms)
RUMBLES = {"launch": (0x6000, 0x3000, 180), "error": (0x9000, 0, 130)}
MIN_GAP_S = {"move": 0.06, "error": 0.5}  # holding the D-pad, a status that says it again
PLAYERS = ("pw-play", "paplay", "aplay")


def samples(notes: tuple, volume: float) -> bytes:
    """Sine tones with a little overtone, each dying away (16 bit, mono)."""
    out = bytearray()
    for frequency, ms in notes:
        count = int(RATE * ms / 1000)
        for i in range(count):
            t = i / RATE
            attack = min(1.0, t / ATTACK_S)
            decay = math.exp(-4.0 * i / count)
            value = math.sin(2 * math.pi * frequency * t) + 0.2 * math.sin(4 * math.pi * frequency * t)
            out += struct.pack("<h", int(32767 * volume * attack * decay * value / 1.2))
    return bytes(out)


def sound_file(folder: Path, name: str) -> Path:
    """The sound's file - written the first time."""
    path = folder / f"{name}-{VERSION}.wav"
    if not path.is_file():
        folder.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        with wave.open(str(temporary), "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(RATE)
            out.writeframes(samples(*SOUNDS[name]))
        temporary.replace(path)
    return path


class Feedback:
    def __init__(self, config: dict, folder: Path, visible: Callable[[], bool] = lambda: True,
                 rumble: Callable[[int, int, int], None] | None = None,
                 which: Callable[[str], str | None] = shutil.which, popen=subprocess.Popen,
                 clock: Callable[[], float] = time.monotonic):
        self.config, self.folder, self.visible, self.rumble = config, folder, visible, rumble
        self.popen, self.clock = popen, clock
        self.player = next((found for found in map(which, PLAYERS) if found), None)
        self.running: list = []
        self.last: dict[str, float] = {}

    def wanted(self, what: str) -> bool:
        """Read each time: logging in brings that user's choice."""
        return bool((self.config.get("appearance") or {}).get(what, True))

    def play(self, name: str) -> None:
        now = self.clock()
        if now - self.last.get(name, -1000.0) < MIN_GAP_S.get(name, 0.0) or not self.visible():
            return
        self.last[name] = now
        if self.wanted("sounds"):
            self._sound(name)
        if name in RUMBLES and self.rumble is not None and self.wanted("rumble"):
            self.rumble(*RUMBLES[name])

    def _sound(self, name: str) -> None:
        self.running = [process for process in self.running if process.poll() is None]  # (none left behind)
        if self.player is None:
            return
        try:
            self.running.append(self.popen([self.player, str(sound_file(self.folder, name))],
                                           stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                           stderr=subprocess.DEVNULL))
        except OSError:
            pass


_active: Feedback | None = None


def configure(feedback: Feedback | None) -> None:
    global _active
    _active = feedback


def play(name: str) -> None:
    if _active is not None:
        _active.play(name)
