"""Which BIOS files the RetroArch cores need, and whether they're in Emulation/bios.

Never shipped or downloaded - only checked: present, and (by MD5) a known good dump.
An unknown dump is reported as such, it may still work.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

from gamingcrypt.emulation.library import EmulationPaths


@dataclass(frozen=True)
class Requirement:
    files: dict[str, str]  # acceptable file name -> MD5 of the known good dump ("": any), one is enough
    required: bool = True
    note: str = ""
    any_in: str = ""  # or: any file in this folder (inside bios/) - e.g. the many PS2 BIOS versions


REQUIREMENTS: dict[str, Requirement] = {
    "psx": Requirement({"scph5501.bin": "490f666e1afb15b7362b406ed1cea246",
                        "scph5500.bin": "8dd7d5296a650fac7319bce665a6a53c",
                        "scph5502.bin": "32736f17079d0b2b7024407c39bd3050",
                        "scph1001.bin": "924e392ed05558ffdb115408c263dccf",
                        "scph7001.bin": "1e68c231d0896b7eadcad1d7d8e76129",
                        "scph101.bin": "6e3735ff4c7dc899ee98981385f6f3d0"}),
    "segacd": Requirement({"bios_CD_U.bin": "2efd74e3232ff260e371b99f84024f7f",
                           "bios_CD_E.bin": "e66fa1dc5820d254611fdcdba0662372",
                           "bios_CD_J.bin": "278a9397d192149e84e820ac621a8edd"}),
    "saturn": Requirement({"sega_101.bin": "85ec9ca47d8f6807718151cbcca8b964",
                           "mpr-17933.bin": "3240872c70984b6cbfda1586cab68dbe"}),
    "gba": Requirement({"gba_bios.bin": "a860e8c0b6d573d191e4ec7db1b1e4f6"}, required=False,
                       note="optional - mGBA has its own"),
    "dreamcast": Requirement({"dc/dc_boot.bin": "e10c53c2f8b90bab96ead2d368858623"}, required=False,
                             note="optional - some games need it"),
    "pce": Requirement({"syscard3.pce": "38179df8f4ac870017db21ebcbf53114"}, required=False,
                       note="only for CD games"),
    "ps2": Requirement({}, any_in="pcsx2/bios", note="a PS2 BIOS dump, e.g. SCPH-70004.bin"),
    "switch": Requirement({"switch/prod.keys": ""},
                          note="your console's keys; the firmware files go into bios/switch/firmware"),
}


@dataclass
class BiosStatus:
    system_id: str
    state: str  # "ok", "unverified" (present, unknown dump), "missing"
    found: list[str] = field(default_factory=list)
    requirement: Requirement | None = None

    @property
    def problem(self) -> bool:
        return self.state == "missing" and self.requirement is not None and self.requirement.required

    def describe(self) -> str:
        req = self.requirement
        if self.state == "ok":
            return ", ".join(self.found)
        if self.state == "unverified":
            return f"{', '.join(self.found)} (unknown version - may still work)"
        names = f"any file in bios/{req.any_in}" if req.any_in else " or ".join(req.files)
        return f"missing: {names}" + (f" ({req.note})" if req.note else "")


def _md5(path: Path) -> str:
    digest = hashlib.md5(usedforsecurity=False)
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _find(bios_dir: Path, name: str) -> Path | None:
    """Case doesn't matter (SCPH5501.BIN works too)."""
    exact = bios_dir / name
    if exact.exists():
        return exact
    parent = (bios_dir / name).parent
    try:
        for entry in parent.iterdir():
            if entry.name.lower() == Path(name).name.lower():
                return entry
    except OSError:
        pass
    return None


def check(paths: EmulationPaths, system_id: str) -> BiosStatus | None:
    """None: this system needs no BIOS."""
    req = REQUIREMENTS.get(system_id)
    if req is None:
        return None
    if req.any_in:
        try:
            found = sorted(f.name for f in (paths.bios / req.any_in).iterdir()
                           if f.is_file() and not f.name.startswith("."))
        except OSError:
            found = []
        return BiosStatus(system_id, "ok" if found else "missing", found, req)
    found, good = [], False
    for name, md5 in req.files.items():
        path = _find(paths.bios, name)
        if path is None:
            continue
        found.append(name)
        if not md5:  # any version
            good = True
            continue
        try:
            good = good or _md5(path) == md5
        except OSError:
            continue
    state = "missing" if not found else ("ok" if good else "unverified")
    return BiosStatus(system_id, state, found, req)


def check_all(paths: EmulationPaths, system_ids) -> list[BiosStatus]:
    return [status for sid in system_ids if (status := check(paths, sid)) is not None]
