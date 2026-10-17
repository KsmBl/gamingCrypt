"""The PS2's own settings - its language - in the NVRAM file next to each BIOS (<bios>.nvm).

PS2 games show their text in the language of the console's settings; the PS2 core has no
option for it, it keeps the console's settings in that file. The language is written there
before a game starts - laid out as PCSX2 reads it (CDVD.cpp, CDVD_internal.h, BiosTools.cpp):
the second config block holds the OSD settings, its byte 0x10 says Japanese or not (bit 4),
byte 0x11 the language (bits 0-4, the OSD version above them).
"""

from __future__ import annotations

import struct
from pathlib import Path

# the OSD's language numbers (ps2sdk osd_config.h)
LANGUAGES = {"Japanese": 0, "English": 1, "French": 2, "Spanish": 3, "German": 4, "Italian": 5, "Dutch": 6,
             "Portuguese": 7, "Russian": 8, "Korean": 9, "Traditional Chinese": 10, "Simplified Chinese": 11}
SIZE = 1024
NEW_LAYOUT = 0x146  # BIOS v1.70 and later keep their settings elsewhere in the file
# (config1, ilink id, PStwo region parameters) for BIOS before / from v1.70
LAYOUTS = {False: (0x300, 0x1C0, 0x180), True: (0x2B0, 0x1E0, 0x180)}
ILINK_ID = bytes((0x00, 0xAC, 0xFF, 0xFF, 0xFF, 0xFF, 0xB9, 0x86))
ILINK_CHECKSUM = bytes((0x00, 0x18))
# ROMVER's region letter -> what a new console of that region has (PCSX2's defaults)
REGIONS = {"J": ("JJjpnJJ", 0x20, 0x20, 0x30), "A": ("AAengAU", 0x30, 0x21, 0x41),
           "E": ("EEengEE", 0x30, 0x21, 0x41), "H": ("HHengJA", 0x30, 0x21, 0x41),
           "C": ("CCschJC", 0x30, 0x2B, 0x4B)}


def bios_version(data: bytes) -> tuple[int, str] | None:
    """(version - 0x230 for v2.30, region letter) from the BIOS's ROMVER file; None: no PS2 BIOS."""
    start = next((i for i in range(0, min(len(data), 512 * 1024 * 16), 16) if data[i:i + 10].rstrip(b"\0") == b"RESET"),
                 None)
    if start is None:
        return None
    offset, entry = 0, start
    while entry + 16 <= len(data) and data[entry] != 0:
        name = data[entry:entry + 10].rstrip(b"\0")
        size = struct.unpack_from("<I", data, entry + 12)[0]
        if name == b"ROMVER":
            romver = data[offset:offset + 14].decode("ascii", "replace")
            try:
                return int(romver[0:2]) << 8 | int(romver[2:4]), romver[4]
            except ValueError:
                return None
        offset += size if size % 16 == 0 else (size + 16) & ~15
        entry += 16
    return None


def apply(nvram: bytearray, version: int, region: str, language: str) -> bytearray:
    """The language written into a console's settings - made like a new console's (of the BIOS's
    region) first where the core would throw them away as missing."""
    config1, ilink, regparams = LAYOUTS[version >= NEW_LAYOUT]
    params, first, second, last = REGIONS.get(region, REGIONS["E"])
    pstwo = version >> 8 == 2 and version & 0xFF != 10  # (the core wants region parameters there)
    if len(nvram) < SIZE or not any(nvram[config1 + 0x10:config1 + 0x20]) or (
            pstwo and not any(nvram[regparams:regparams + 12])):
        nvram = bytearray(SIZE)  # as the core does with missing settings
        if pstwo:
            nvram[regparams:regparams + 7] = params.encode()
        nvram[ilink:ilink + 8] = ILINK_ID
        if version >= NEW_LAYOUT:
            nvram[ilink + 8:ilink + 10] = ILINK_CHECKSUM
        nvram[config1 + 0x10], nvram[config1 + 0x11] = first, second
        nvram[config1 + 0x15], nvram[config1 + 0x1F] = 0x70, last
    number = LANGUAGES.get(language, LANGUAGES["English"])
    osd = nvram[config1 + 0x11] >> 5 or 1
    nvram[config1 + 0x11] = osd << 5 | number
    nvram[config1 + 0x10] = nvram[config1 + 0x10] & ~0x10 | (0 if number == 0 else 0x10)
    return nvram


def set_language(folder: Path, language: str) -> list[Path]:
    """Every PS2 BIOS in the folder: its settings in the language. -> the files written."""
    written = []
    for bios in sorted(folder.iterdir()) if folder.is_dir() else []:
        if not bios.is_file() or bios.suffix.lower() in (".nvm", ".mec"):
            continue
        try:
            found = bios_version(bios.read_bytes())
            if found is None:
                continue
            nvm = bios.with_suffix(".nvm")
            old = bytearray(nvm.read_bytes()) if nvm.exists() else bytearray()
            new = apply(bytearray(old), *found, language)
            if new != old:
                nvm.write_bytes(bytes(new))
                written.append(nvm)
        except OSError:
            continue
    return written
