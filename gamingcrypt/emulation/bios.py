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


# --- uploads: "this is my PS1 BIOS" - name and place are worked out here --------------------------

UPLOAD_KINDS: dict[str, str] = {
    "psx": "PlayStation (PS1) BIOS",
    "ps2": "PlayStation 2 BIOS",
    "switch-keys": "Switch keys (prod.keys / title.keys)",
    "switch-firmware": "Switch firmware (.zip or .nca files)",
    "segacd": "Sega CD BIOS",
    "saturn": "Sega Saturn BIOS",
    "dreamcast": "Dreamcast BIOS",
    "gba": "Game Boy Advance BIOS",
    "pce": "PC Engine CD BIOS (System Card)",
}
PS2_BIOS_DIR = "pcsx2/bios"
SWITCH_DIR = "switch"


def _members(upload: Path):
    """(name, bytes) of the upload - or of each file in it, when it's a zip."""
    import zipfile

    if zipfile.is_zipfile(upload):
        with zipfile.ZipFile(upload) as archive:
            for info in archive.infolist():
                name = Path(info.filename).name
                if not info.is_dir() and name and not name.startswith("."):
                    yield name, archive.read(info)
    else:
        yield upload.name, upload.read_bytes()


def _write(target: Path, data: bytes) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_name(f".{target.name}.part")
    part.write_bytes(data)
    part.replace(target)
    return target


def _keys_name(name: str, data: bytes) -> str | None:
    text = data[:200_000].decode(errors="replace").lower()
    if "header_key" in text or "master_key" in text or name.lower() == "prod.keys":
        return "prod.keys"
    if name.lower() == "title.keys" or (text.strip() and all(
            len(line.split("=")[0].strip()) == 32 for line in text.splitlines() if line.strip())):
        return "title.keys"
    return None


def place(paths: EmulationPaths, kind: str, upload: Path) -> tuple[bool, str, list[Path]]:
    """Put an uploaded BIOS (or zip of them) where its emulator looks, under the right name.

    (ok, what happened - for the person uploading, the files written). The upload is removed.
    """
    import zipfile

    written: list[Path] = []
    notes: list[str] = []
    try:
        members = list(_members(upload))
    except (OSError, zipfile.BadZipFile) as exc:
        upload.unlink(missing_ok=True)
        return False, f"could not read it: {exc}", []
    upload.unlink(missing_ok=True)
    bios = paths.bios
    if kind == "ps2":
        for name, data in members:
            written.append(_write(bios / PS2_BIOS_DIR / name, data))
        notes.append(f"{len(written)} file(s) in bios/{PS2_BIOS_DIR}")
    elif kind == "switch-keys":
        for name, data in members:
            target = _keys_name(name, data)
            if target:
                written.append(_write(bios / SWITCH_DIR / target, data))
                notes.append(f"saved as {target}")
        if not written:
            return False, "no Switch keys in it (prod.keys / title.keys)", []
    elif kind == "switch-firmware":
        for name, data in members:
            if name.lower().endswith(".nca"):
                written.append(_write(bios / SWITCH_DIR / "firmware" / name, data))
        if not written:
            return False, "no firmware (.nca) files in it", []
        notes.append(f"{len(written)} firmware files")
    elif kind in REQUIREMENTS and REQUIREMENTS[kind].files:
        req = REQUIREMENTS[kind]
        by_md5 = {md5: name for name, md5 in req.files.items() if md5}
        accepted = {Path(name).name.lower(): name for name in req.files}
        loose = len(members) == 1  # a single file is surely meant as this BIOS
        for name, data in members:
            known = by_md5.get(hashlib.md5(data, usedforsecurity=False).hexdigest())
            if known:
                written.append(_write(bios / known, data))
                notes.append(f"saved as {known} (known good)")
            elif name.lower() in accepted:
                written.append(_write(bios / accepted[name.lower()], data))
                notes.append(f"saved as {accepted[name.lower()]} (unknown version - may still work)")
            elif loose:
                first = next(iter(req.files))
                existing = bios / first
                if existing.is_file() and by_md5.get(_md5(existing)):
                    return False, f"not saved: you already have a known good {first}", []
                written.append(_write(existing, data))
                notes.append(f"saved as {first} (unknown version - may still work)")
        if not written:
            return False, f"no {UPLOAD_KINDS.get(kind, kind)} in it", []
    else:
        return False, "unknown kind of BIOS", []
    return True, "; ".join(notes), written
