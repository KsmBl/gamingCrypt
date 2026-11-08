"""A stick that isn't in keeps its games in the list, greyed out - each user chooses it - and which
games are on which stick is kept on the encrypted drive, nowhere else."""

import copy
import json
from pathlib import Path

import pytest

from gamingcrypt import stick_memory, users
from gamingcrypt.config import DEFAULTS
from gamingcrypt.system.removable import Removable
from tests.test_code_dialogs import rect_in, screen

SCREENS = [(1280, 800), (1280, 720), (1920, 1080), (1366, 768), (1024, 600)]


@pytest.fixture
def drive(tmp_path, monkeypatch):
    """The encrypted drive (a folder stands in for its mount) with an Emulation and Windows Games folder."""
    from gamingcrypt.emulation.library import EmulationPaths

    monkeypatch.setattr(stick_memory, "REQUIRE_MOUNT", False)
    root = tmp_path / "GamingCrypt"
    paths = EmulationPaths(root / "Emulation")
    paths.ensure()
    (root / "Windows Games").mkdir()
    return root


@pytest.fixture
def stick(tmp_path):
    mount = tmp_path / "STICK"
    rom = mount / "roms" / "snes" / "Earthbound (USA).sfc"
    rom.parent.mkdir(parents=True)
    rom.write_bytes(b"x" * 10)
    (mount / "Windows Games" / "Celeste").mkdir(parents=True)
    (mount / "Windows Games" / "Celeste" / "Celeste.exe").write_bytes(b"MZ")
    return Removable(mount, "usb", "STICK", "/dev/sdb1", "exfat", "/dev/sdb", uuid="1234-abcd")


@pytest.fixture
def config():
    cfg = copy.deepcopy(DEFAULTS)
    return cfg


def make_tab(qtbot, drive, config, user=None):
    from gamingcrypt.ui.games_tab import GamesTab
    from tests.fakes import FakeService

    tab = GamesTab(FakeService(), library_settings=config["libraries"], emulation_root=str(drive / "Emulation"),
                   windows_root=str(drive / "Windows Games"), stick_settings=lambda: config.get("sticks") or {},
                   user=user)
    qtbot.addWidget(tab)
    tab.show()
    return tab


def names(tab) -> dict:
    return {g.name: g.away for games in [*tab.roms.values(), tab.pc_games()] for g in games}


def test_taken_out_its_games_stay_greyed_out(qtbot, drive, config, stick):
    tab = make_tab(qtbot, drive, config)
    tab.set_drives([stick])
    qtbot.waitUntil(lambda: names(tab) == {"Earthbound": "", "Celeste": ""})
    tab.set_drives([])
    qtbot.waitUntil(lambda: names(tab) == {"Earthbound": "STICK", "Celeste": "STICK"})
    cards = {c.game.name: c for c in tab.home.grid.widgets() if hasattr(c.game, "away")}
    for card in cards.values():
        assert card.property("away") and card.cover.graphicsEffect().opacity() < 0.5
        assert card.meta.text().endswith("On STICK · not in") and card.cover.badge == "usb"
    tab.set_drives([stick])  # back in
    qtbot.waitUntil(lambda: names(tab) == {"Earthbound": "", "Celeste": ""})
    cards = {c.game.name: c for c in tab.home.grid.widgets() if hasattr(c.game, "away")}
    assert all(card.cover.graphicsEffect() is None for card in cards.values())


def test_kept_on_the_encrypted_drive_only(qtbot, drive, config, stick, tmp_path, isolated_home):
    tab = make_tab(qtbot, drive, config)
    tab.set_drives([stick])
    qtbot.waitUntil(lambda: (drive / ".gamingcrypt" / "sticks.json").exists() and "Celeste" in names(tab))
    qtbot.wait(100)
    data = json.loads((drive / ".gamingcrypt" / "sticks.json").read_text())
    entry = data["fs:1234-abcd"]
    assert entry["name"] == "STICK" and [g["name"] for g in entry["roms"]] == ["Earthbound"]
    assert [g["name"] for g in entry["windows"]] == ["Celeste"]
    # nothing about the games anywhere outside the encrypted drive: not the config, not the home folder
    assert "Earthbound" not in json.dumps(config)
    outside = [p for p in isolated_home.rglob("*") if p.is_file()]
    assert not [p for p in outside if "Earthbound" in p.read_text(errors="ignore")]


def test_nothing_written_while_the_drive_isnt_mounted(tmp_path, monkeypatch, stick):
    monkeypatch.setattr(stick_memory, "REQUIRE_MOUNT", True)
    root = tmp_path / "GamingCrypt"  # locked: an empty folder on the device itself
    root.mkdir()
    memory = stick_memory.StickMemory(root)
    assert not memory.usable
    from gamingcrypt.emulation.library import EmulationPaths, scan_all

    paths = EmulationPaths(root / "Emulation")
    memory.update("roms", [stick], [g for gs in scan_all(paths, [stick]).values() for g in gs])
    assert not (root / ".gamingcrypt").exists()


def test_moved_off_the_stick_its_forgotten_there(qtbot, drive, config, stick):
    from gamingcrypt import moving

    tab = make_tab(qtbot, drive, config)
    tab.set_drives([stick])
    qtbot.waitUntil(lambda: "Earthbound" in names(tab))
    moving.move(tab.roms["snes"][0], moving.Place(None), tab.emulation)
    tab.reload_roms()
    qtbot.waitUntil(lambda: names(tab).get("Earthbound") == "" and tab.roms["snes"][0].removable == "")
    qtbot.wait(100)
    tab.set_drives([])
    qtbot.waitUntil(lambda: names(tab).get("Celeste") == "STICK")
    assert names(tab)["Earthbound"] == ""  # on the drive now: there, not a remembered one


def test_each_user_has_their_own_setting(qtbot, drive, config, stick):
    from gamingcrypt.unlock import kdf, keyslots

    config["unlock"]["kdf"] = dict(kdf.new_params(), n=2 ** 4)
    master = keyslots.new_master()
    config["unlock"]["keyring"] = {"vault": keyslots.new_vault(master, "pw"),
                                   "admin": keyslots.new_slot("1234", master, dict(kdf.new_params(), n=2 ** 4))}
    mia = users.add(config, "Mia", "pin", "9876", master)
    users.enter(config, mia.id)
    config["sticks"]["remember"] = False  # Mia doesn't want them
    users.leave(config)
    assert config["sticks"]["remember"] is True  # the admin's is as it was
    users.enter(config, mia.id)
    assert config["sticks"]["remember"] is False
    tab = make_tab(qtbot, drive, config, user=users.current(config))
    tab.set_drives([stick])
    qtbot.waitUntil(lambda: "Earthbound" in names(tab))
    tab.set_drives([])
    qtbot.waitUntil(lambda: names(tab) == {})  # Mia: not shown
    users.leave(config)
    admin_tab = make_tab(qtbot, drive, config)
    qtbot.waitUntil(lambda: names(admin_tab) == {"Earthbound": "STICK", "Celeste": "STICK"})  # the admin: shown


def test_its_page_waits_for_the_stick(qtbot, drive, config, stick):
    tab = make_tab(qtbot, drive, config)
    tab.set_drives([stick])
    qtbot.waitUntil(lambda: "Earthbound" in names(tab))
    tab.set_drives([])
    qtbot.waitUntil(lambda: names(tab).get("Earthbound") == "STICK")
    tab.open_rom(tab.roms["snes"][0])
    page = tab.currentWidget()
    assert not page.main_button.isEnabled() and page.move_button.isHidden()
    assert page.status.text() == "Not here at the moment - put STICK in again to play it"
    tab.set_drives([stick])
    qtbot.waitUntil(lambda: page.main_button.isEnabled())
    assert page.game.away == "" and page.status.text() == ""


def test_favorites_and_continue_playing(qtbot, drive, config, stick):
    tab = make_tab(qtbot, drive, config)
    tab.set_drives([stick])
    qtbot.waitUntil(lambda: "Earthbound" in names(tab))
    game = tab.roms["snes"][0]
    tab.profiles.set(game.appid, "favorite", True)
    tab.set_drives([])
    qtbot.waitUntil(lambda: names(tab).get("Earthbound") == "STICK")
    assert game.appid in tab.favorites()  # still counted
    away = tab.roms["snes"][0]
    away.last_played = 1_700_000_000
    card = tab.home.continue_card
    card.set_game(away)
    assert not card.play_button.isEnabled() and card.play_button.text() == "Put STICK in"
    launched = []
    tab.rom_launcher = lambda g: launched.append(g) or (True, "")
    card.play()
    assert launched == []


def test_hidden_its_games_go(qtbot, drive, config, stick):
    tab = make_tab(qtbot, drive, config)
    tab.set_drives([stick])
    qtbot.waitUntil(lambda: "Earthbound" in names(tab))
    tab.set_drives([])
    qtbot.waitUntil(lambda: bool(names(tab)))
    config["sticks"]["remember"] = False
    tab.reload_roms()
    qtbot.waitUntil(lambda: names(tab) == {})


# --- Settings → Storage: the switch and the remembered sticks ----------------------------------------

def storage(qtbot, host, tab, config, drives=()):
    from gamingcrypt.ui.storage_page import StoragePage

    saved = []
    page = StoragePage(lambda: None, emulation_fn=lambda: None)
    page.library_fn = lambda: tab
    page.stick_settings_fn = lambda: config.setdefault("sticks", {"remember": True})
    page.save_fn = lambda: saved.append(json.loads(json.dumps(config["sticks"])))
    page.setParent(host)
    page.resize(host.size())
    page.show()
    page.set_drives(list(drives))
    page.show_drives()
    qtbot.wait(20)
    return page, saved


@pytest.mark.parametrize("w,h", SCREENS)
def test_the_switch_and_forgetting(qtbot, drive, config, stick, w, h):
    tab = make_tab(qtbot, drive, config)
    tab.set_drives([stick])
    qtbot.waitUntil(lambda: "Celeste" in names(tab))
    qtbot.wait(100)
    tab.set_drives([])
    host = screen(qtbot, w, h)
    page, saved = storage(qtbot, host, tab, config)
    assert page.remember_button.isChecked() and "shown" in page.remember_button.text()
    text, forget = page.remembered_rows["fs:1234-abcd"]
    assert text.text() == "STICK\nUSB stick  ·  2 games  ·  not in"
    for widget in (page.remember_button, page.remember_hint, text, forget):
        assert host.rect().contains(rect_in(widget, host)), f"{widget} off the {w}x{h} screen"
    changed = []
    page.remember_changed.connect(lambda: changed.append(1))
    page.remember_button.click()
    assert config["sticks"]["remember"] is False and saved == [{"remember": False}] and changed == [1]
    assert "hidden" in page.remember_button.text()
    page.remember_button.click()
    forget.click()
    assert page.remembered_rows == {} and changed == [1, 1, 1]
    tab.reload_roms()
    qtbot.waitUntil(lambda: names(tab) == {})


def test_a_stick_thats_in_isnt_listed_as_remembered(qtbot, drive, config, stick):
    tab = make_tab(qtbot, drive, config)
    tab.set_drives([stick])
    qtbot.waitUntil(lambda: "Celeste" in names(tab))
    qtbot.wait(100)
    page, _saved = storage(qtbot, screen(qtbot, 1280, 800), tab, config, drives=[stick])
    assert page.remembered_rows == {}
