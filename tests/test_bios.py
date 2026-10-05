"""BIOS check for the emulated systems (Settings -> Health and the system page)."""

import hashlib

import pytest

from gamingcrypt.emulation import bios
from gamingcrypt.emulation.bios import Requirement
from gamingcrypt.emulation.library import EmulationPaths


@pytest.fixture
def paths(tmp_path):
    p = EmulationPaths(tmp_path / "Emulation")
    p.ensure()
    return p


def test_missing_ok_unverified(paths, monkeypatch):
    good = b"the real dump"
    monkeypatch.setitem(bios.REQUIREMENTS, "psx", Requirement({"scph5501.bin": hashlib.md5(good).hexdigest(),
                                                               "scph1001.bin": "0" * 32}))
    status = bios.check(paths, "psx")
    assert status.state == "missing" and status.problem
    assert status.describe() == "missing: scph5501.bin or scph1001.bin"
    (paths.bios / "SCPH1001.BIN").write_bytes(b"some other dump")  # any case works
    status = bios.check(paths, "psx")
    assert status.state == "unverified" and not status.problem and "may still work" in status.describe()
    (paths.bios / "scph5501.bin").write_bytes(good)
    assert bios.check(paths, "psx").state == "ok"


def test_optional_subfolders_and_systems_without_bios(paths):
    status = bios.check(paths, "dreamcast")
    assert status.state == "missing" and not status.problem and "optional" in status.describe()
    (paths.bios / "dc").mkdir()
    (paths.bios / "dc" / "dc_boot.bin").write_bytes(b"x")
    assert bios.check(paths, "dreamcast").found == ["dc/dc_boot.bin"]
    assert bios.check(paths, "snes") is None  # needs none
    assert [s.system_id for s in bios.check_all(paths, ["snes", "psx", "gba"])] == ["psx", "gba"]


def test_known_hashes_look_right():
    for system_id, req in bios.REQUIREMENTS.items():
        assert req.files or req.any_in, system_id
        assert all(md5 == "" or (len(md5) == 32 and int(md5, 16) >= 0) for md5 in req.files.values()), system_id


def test_health_only_checks_systems_with_games(paths):
    from gamingcrypt.system.health import Health

    health = Health(emulation_root=str(paths.root))
    assert health.bios().detail == "none needed for your games"
    (paths.roms / "snes" / "Mario.sfc").write_text("x")
    assert health.bios().ok
    (paths.roms / "psx" / "Crash.chd").write_text("x")
    check = health.bios()
    assert not check.ok and check.detail.startswith("PS1: missing: scph5501.bin") and "Add ROMs" in check.fix
    assert Health(emulation_root=str(paths.root.parent / "nowhere")).bios().optional


def test_system_page_names_the_missing_bios(qtbot, paths):
    import copy

    from gamingcrypt.config import DEFAULTS
    from gamingcrypt.emulation.systems import BY_ID
    from gamingcrypt.ui.emulation_pages import SystemPage
    from gamingcrypt.ui.games_tab import GamesTab
    from tests.fakes import FakeService

    tab = GamesTab(FakeService(), library_settings=copy.deepcopy(DEFAULTS)["libraries"],
                   emulation_root=str(paths.root))
    qtbot.addWidget(tab)
    psx = SystemPage(tab, BY_ID["psx"], [])
    assert not psx.bios_note.isHidden() and "scph5501.bin" in psx.bios_note.text()
    assert psx.bios_note.property("error") is True
    assert SystemPage(tab, BY_ID["snes"], []).bios_note.isHidden()  # SNES needs none


def test_ps2_any_bios_in_its_folder_and_switch_keys(tmp_path):
    from gamingcrypt.emulation import bios
    from gamingcrypt.emulation.library import EmulationPaths

    paths = EmulationPaths(tmp_path / "Emulation")
    paths.ensure()
    status = bios.check(paths, "ps2")
    assert status.problem and status.describe().startswith("missing: any file in bios/pcsx2/bios")
    (paths.bios / "pcsx2" / "bios").mkdir(parents=True)
    (paths.bios / "pcsx2" / "bios" / "SCPH-70004.bin").write_bytes(b"x")
    status = bios.check(paths, "ps2")
    assert status.state == "ok" and status.found == ["SCPH-70004.bin"]
    assert bios.check(paths, "switch").problem
    (paths.bios / "switch").mkdir()
    (paths.bios / "switch" / "prod.keys").write_text("header_key = 00")
    assert bios.check(paths, "switch").state == "ok"  # keys are per console: no MD5
