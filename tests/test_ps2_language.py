"""PS2 games take their language from the console's settings: the .nvm file next to each BIOS."""

import struct

import pytest

from gamingcrypt.emulation import bios, ps2_nvram, retroarch
from gamingcrypt.emulation.library import EmulationPaths, scan
from gamingcrypt.emulation.systems import BY_ID


def fake_bios(romver: str) -> bytes:
    """A BIOS image as PCSX2 reads it: RESET's file at 0, the ROMDIR entries in ROMDIR's, then ROMVER."""
    data = bytearray(0x200)

    def entry(at: int, name: bytes, size: int) -> None:
        data[at:at + 10] = name.ljust(10, b"\0")
        struct.pack_into("<HI", data, at + 10, 0, size)

    entry(0x40, b"RESET", 0x40)
    entry(0x50, b"ROMDIR", 0x40)
    entry(0x60, b"ROMVER", 0x10)
    data[0x80:0x8E] = romver.encode()
    return bytes(data)


def test_the_bios_version_and_region():
    assert ps2_nvram.bios_version(fake_bios("0230EC20040614")) == (0x21E, "E")  # v2.30, Europe
    assert ps2_nvram.bios_version(fake_bios("0160JC20011004")) == (0x13C, "J")  # v1.60: (1 << 8) | 60
    assert ps2_nvram.bios_version(b"\0" * 0x200) is None


def test_written_where_pcsx2_reads_it():
    """config1 (0x2B0 from BIOS v1.70 on): byte 0x10 bit 4 = not Japanese, byte 0x11 = OSD version
    << 5 | language - the bytes PCSX2's ReadOSDConfigParames takes (params[1], params[2])."""
    nvram = ps2_nvram.apply(bytearray(), 0x21E, "E", "German")
    assert len(nvram) == 1024
    assert nvram[0x2B0 + 0x11] == 0x20 | 4 and nvram[0x2B0 + 0x10] == 0x30  # OSD 1, German
    assert nvram[0x180:0x187] == b"EEengEE"  # a PStwo-era BIOS needs its region (else the core starts over)
    assert nvram[0x1E0:0x1E8] == ps2_nvram.ILINK_ID and nvram[0x1E8:0x1EA] == ps2_nvram.ILINK_CHECKSUM
    japanese = ps2_nvram.apply(nvram, 0x21E, "E", "Japanese")
    assert japanese[0x2B0 + 0x11] == 0x20 and japanese[0x2B0 + 0x10] == 0x20
    old = ps2_nvram.apply(bytearray(), 0x120, "J", "English")  # before v1.70: elsewhere
    assert old[0x300 + 0x11] == 0x21 and not any(old[0x2B0:0x2C0]) and not any(old[0x180:0x18C])


def test_the_rest_of_the_settings_is_kept():
    nvram = ps2_nvram.apply(bytearray(), 0x21E, "E", "English")
    nvram[0x2B0 + 0x13] = 0x55  # (the time zone …)
    nvram[0x2B0 + 0x11] = 0x40 | 1  # an OSD version 2 console
    nvram[0x10] = 0x99
    again = ps2_nvram.apply(bytearray(nvram), 0x21E, "E", "French")
    assert again[0x2B0 + 0x11] == 0x40 | 2 and again[0x2B0 + 0x13] == 0x55 and again[0x10] == 0x99


@pytest.fixture
def paths(tmp_path, monkeypatch):
    monkeypatch.setattr(retroarch, "CORE_DIRS", ())
    p = EmulationPaths(tmp_path / "Emulation")
    p.ensure()
    return p


def test_a_ps2_game_starts_in_it(paths, tmp_path):
    folder = paths.bios / bios.PS2_BIOS_DIR
    folder.mkdir(parents=True)
    (folder / "SCPH-70004.bin").write_bytes(fake_bios("0200EC20040614"))
    (folder / "readme.txt").write_text("not a BIOS")
    (paths.cores / "pcsx2_libretro.so").write_text("x")
    (paths.roms_for(BY_ID["ps2"]) / "Ratchet.iso").write_text("x")
    game = scan(paths, BY_ID["ps2"])[0]
    run = dict(popen=lambda cmd, **k: None, which=lambda n: "/usr/bin/retroarch")
    retroarch.launch(game, paths, tmp_path / "d", tmp_path / "l", language="German", **run)
    nvm = folder / "SCPH-70004.nvm"
    assert nvm.read_bytes()[0x2B0 + 0x11] & 0x1F == 4 and not (folder / "readme.nvm").exists()
    retroarch.launch(game, paths, tmp_path / "d", tmp_path / "l", language="Spanish", **run)
    assert nvm.read_bytes()[0x2B0 + 0x11] & 0x1F == 3
    assert ps2_nvram.set_language(folder, "Spanish") == []  # as it is: not written again
