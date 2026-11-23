"""Keep a Windows game off the first CPU core (a per-game option).

The first core takes most of the hardware's interrupts (graphics, USB, touch) and the kernel's
housekeeping, and many old games (GTA IV) tie their main thread to it: pushed aside hundreds
of times a second - frames come late (micro-stutters). "Quiet cores" gives the game one thread
of every other core, and Proton (WINE_CPU_TOPOLOGY) shows the game those as its cores - its
"first core" is then a quiet one. With hyperthreading on, the game gets one thread per core
(each of its threads a whole core) and the second threads stay for the rest of the system.
"""

from __future__ import annotations

from pathlib import Path

PROFILE_KEY = "cpu_quiet"
MIN_CORES = 4  # fewer left over: it'd cost the game more than it gains


def _cpu_list(text: str) -> list[int]:
    """'0-3,8,10-11' -> [0, 1, 2, 3, 8, 10, 11]"""
    cpus = []
    for part in text.strip().split(","):
        if not part:
            continue
        first, _, last = part.partition("-")
        cpus.extend(range(int(first), int(last or first) + 1))
    return cpus


def quiet_cpus(sys_root: Path = Path("/sys")) -> list[int]:
    """One thread of every core but the first one's ([] where that leaves too few, or unknown)."""
    base = sys_root / "devices/system/cpu"
    try:
        online = _cpu_list((base / "online").read_text())
        cores: dict[tuple[int, ...], int] = {}
        for cpu in online:
            siblings = tuple(c for c in _cpu_list(
                (base / f"cpu{cpu}/topology/thread_siblings_list").read_text()) if c in online)
            cores.setdefault(siblings or (cpu,), cpu)
    except (OSError, ValueError):
        return []
    first = next((core for core in cores if online and online[0] in core), None)
    cpus = sorted(cpu for core, cpu in cores.items() if core != first)
    return cpus if len(cpus) >= MIN_CORES else []


def available(sys_root: Path = Path("/sys")) -> bool:
    return bool(quiet_cpus(sys_root))


def topology(cpus: list[int]) -> str:
    """Proton's WINE_CPU_TOPOLOGY: how many cores the game sees, and which real ones they are."""
    return f"{len(cpus)}:{','.join(str(c) for c in cpus)}"
