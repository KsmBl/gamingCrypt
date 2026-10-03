"""Which Steam games are running right now.

On Linux Steam starts every game through its ``reaper`` process with
``SteamLaunch AppId=<id>`` on the command line, so /proc tells us reliably.
"""

from __future__ import annotations

from pathlib import Path


def running_appids(proc: Path = Path("/proc")) -> set[int]:
    found: set[int] = set()
    for cmdline in proc.glob("[0-9]*/cmdline"):
        try:
            args = cmdline.read_bytes().split(b"\0")
        except OSError:
            continue  # process ended / not ours
        if b"SteamLaunch" not in args:
            continue
        for arg in args:
            if arg.startswith(b"AppId="):
                try:
                    found.add(int(arg[6:]))
                except ValueError:
                    pass
    return found
