"""Encrypted sticks: a VeraCrypt container with the drive's code (same password, same key derivation)."""

import json
import subprocess
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from gamingcrypt import users
from gamingcrypt.system import removable, stick_crypt
from gamingcrypt.system.removable import Drives, Removable
from gamingcrypt.unlock import kdf, keyslots, sidecar
from gamingcrypt.unlock.veracrypt import UnlockResult

FAST = {"n": 2 ** 4, "r": 8, "p": 1}  # (scrypt that's quick in tests)


class FakeVeraCrypt:
    """Containers with their passwords; "mounting" makes the folder and a note of it."""

    def __init__(self):
        self.passwords: dict[str, str] = {}
        self.mounted: set[Path] = set()
        self.calls: list[tuple] = []

    def factory(self, cfg):
        return FakeUnlocker(self, cfg["volume"], Path(cfg["mount_point"]))


class FakeUnlocker:
    def __init__(self, vc, volume, mount_point):
        self.vc, self.volume, self.mount_point = vc, volume, mount_point

    def create_volume(self, path, size_gb, secret, quick=True, progress=None, cancel=None, **_kw):
        self.vc.calls.append(("create", path, size_gb))
        Path(path).write_bytes(b"vc")
        self.vc.passwords[path] = secret
        for pct in (40.0, 100.0):
            if progress:
                progress(pct)
        return UnlockResult(True, "Container created")

    def unlock(self, password):
        self.vc.calls.append(("open", self.volume, password))
        if self.vc.passwords.get(self.volume) != password:
            return UnlockResult(False, "Wrong code - please try again")
        self.mount_point.mkdir(parents=True, exist_ok=True)
        self.vc.mounted.add(self.mount_point)
        return UnlockResult(True, "Unlocked")

    def dismount(self, force=True):
        self.vc.calls.append(("close", self.volume))
        self.vc.mounted.discard(self.mount_point)
        return UnlockResult(True, "Drive locked")

    def change_password(self, old, new, new_kdf=None):
        self.vc.calls.append(("rekey", self.volume))
        if self.vc.passwords.get(self.volume) != old:
            return UnlockResult(False, "Wrong code - please try again")
        self.vc.passwords[self.volume] = new
        return UnlockResult(True, "Unlock method changed")


@pytest.fixture
def vc(monkeypatch):
    fake = FakeVeraCrypt()
    monkeypatch.setattr(stick_crypt, "_mounted", lambda path: Path(path) in fake.mounted)
    monkeypatch.setattr(stick_crypt, "unlocker", lambda volume, factory=None: fake.factory(
        {"volume": str(volume), "mount_point": str(stick_crypt.mount_dir(volume))}))
    return fake


@pytest.fixture
def config():
    """The admin's code 1234 (a PIN) and a user's 9876 - the drive's settings as config.json has them."""
    params = dict(kdf.new_params(), **FAST)
    cfg = {"unlock": {"method": "pin", "kdf": params}, "users": []}
    master = keyslots.new_master()
    password = kdf.derive_password("1234", params)
    cfg["unlock"]["keyring"] = {"vault": keyslots.new_vault(master, password),
                                "admin": keyslots.new_slot("1234", master, dict(kdf.new_params(), **FAST))}
    cfg["users"] = [{"id": "mia", "name": "Mia", "method": "pattern",
                     "slot": keyslots.new_slot("9876", master, dict(kdf.new_params(), **FAST))}]
    return cfg


def drive_password(cfg, code="1234"):
    return kdf.derive_password(code, cfg["unlock"]["kdf"])


def encrypted_stick(tmp_path, vc, password, cfg, name="STICK"):
    mount = tmp_path / name
    mount.mkdir()
    volume = mount / stick_crypt.CONTAINER
    volume.write_bytes(b"vc")
    vc.passwords[str(volume)] = password
    stick_crypt.write_info(volume, cfg["unlock"], cfg["users"])
    return Removable(mount, "usb", name, "/dev/sdb1", "exfat", "/dev/sdb", 32 * 1024 ** 3)


class Lsblk:
    def __init__(self, mount):
        self.mount = mount

    def __call__(self, args, **_kw):
        listing = {"blockdevices": [{"name": "sdb", "path": "/dev/sdb", "type": "disk", "tran": "usb", "rm": True,
                                     "size": 32 * 1024 ** 3, "model": "Stick", "mountpoints": [None], "children": [
                                         {"name": "sdb1", "path": "/dev/sdb1", "type": "part", "fstype": "exfat",
                                          "label": "STICK", "mountpoints": [str(self.mount)] if self.mount else [None]}
                                     ]}]} if self.mount is not False else {"blockdevices": []}
        return subprocess.CompletedProcess(args, 0, json.dumps(listing), "")


# --- the same code, the same key derivation --------------------------------------------------

def test_the_stick_has_the_drives_password_and_settings(tmp_path, vc, config):
    password = users.volume_password(config, users.ADMIN, "1234")
    assert password == drive_password(config)  # the drive's: the admin's code through its scrypt
    assert users.volume_password(config, "mia", "9876") == password  # a user's code: the same, via their slot
    stick = Removable(tmp_path / "NEW", "usb", "GAMES", "/dev/sdb1", "exfat", "/dev/sdb")
    stick.mount.mkdir()
    pct = []
    opened = stick_crypt.create(stick, password, config["unlock"], config["users"], progress=pct.append,
                                free=8 * 1024 ** 3)
    volume = stick.mount / stick_crypt.CONTAINER
    assert vc.passwords[str(volume)] == password and pct == [40.0, 100.0]
    assert vc.calls[0] == ("create", str(volume), 7)  # the stick filled (but a little)
    info = sidecar.read_sidecar(str(volume))
    assert info["kdf"] == config["unlock"]["kdf"] and info["method"] == "pin"  # same derivation, same salt
    assert info["keyring"] == config["unlock"]["keyring"] and info["users"][0]["slot"] == config["users"][0]["slot"]
    assert opened.encrypted and opened.host == stick.mount and opened.mount == stick_crypt.mount_dir(volume)
    assert opened.fstype == "ext4" and opened.mount.is_dir()
    # another device with GamingCrypt: the codes open it from what's on the stick alone
    assert stick_crypt.password_from_code(volume, "1234") == password
    assert stick_crypt.password_from_code(volume, "9876") == password


def test_too_small_for_a_container(tmp_path, vc, config):
    stick = Removable(tmp_path, "usb", "TINY")
    with pytest.raises(stick_crypt.CryptError, match="too small"):
        stick_crypt.create(stick, "pw", config["unlock"], free=1024 ** 3)


# --- opened when it's put in -----------------------------------------------------------------

def test_put_in_while_unlocked_it_opens(tmp_path, vc, config):
    password = drive_password(config)
    stick = encrypted_stick(tmp_path, vc, password, config)
    stick_crypt.keys.set(password)
    drives = Drives(run=Lsblk(stick.mount))
    found = drives.look()
    assert len(found) == 1 and found[0].encrypted and found[0].mount == stick_crypt.mount_dir(stick.mount / "GamingCrypt.vc")
    assert found[0].host == stick.mount and drives.unusable == []
    assert [c[0] for c in vc.calls] == ["open"]
    drives.look()
    assert [c[0] for c in vc.calls] == ["open"]  # open already: not again
    drives.run = Lsblk(False)  # taken out
    assert drives.look() == [] and [c[0] for c in vc.calls] == ["open", "close"] and drives.opened == set()


def test_locked_it_waits(tmp_path, vc, config):
    stick = encrypted_stick(tmp_path, vc, drive_password(config), config)
    drives = Drives(run=Lsblk(stick.mount))
    assert drives.look() == []
    assert drives.unusable[0].problem == stick_crypt.NEEDS_CODE
    assert vc.calls == []


def test_one_with_an_earlier_code_isnt_tried_again_and_again(tmp_path, vc, config):
    stick = encrypted_stick(tmp_path, vc, "an earlier password", config)
    stick_crypt.keys.set(drive_password(config))
    drives = Drives(run=Lsblk(stick.mount))
    assert drives.look() == [] and drives.unusable[0].problem == stick_crypt.EARLIER
    drives.look()
    assert [c[0] for c in vc.calls] == ["open"]  # (VeraCrypt takes seconds to say no)
    assert drives.unusable[0].problem == stick_crypt.EARLIER


def test_the_panic_lock_closes_them(tmp_path, vc, config):
    password = drive_password(config)
    stick = encrypted_stick(tmp_path, vc, password, config)
    stick_crypt.keys.set(password)
    drives = Drives(run=Lsblk(stick.mount))
    drives.look()
    drives.close_all()
    assert vc.mounted == set() and drives.opened == set()


def test_formatting_closes_it_first_and_can_encrypt(tmp_path, vc, config):
    from tests.test_removable import StickWithoutTable

    password = drive_password(config)
    stick = encrypted_stick(tmp_path, vc, password, config)
    stick_crypt.keys.set(password)
    opened = replace(Drives(run=Lsblk(stick.mount)).look()[0], disk="/dev/sda")  # (StickWithoutTable: sda)
    new = tmp_path / "NEW"
    new.mkdir()
    now = removable.format_drive(opened, "exfat", "GAMES", run=StickWithoutTable(new), step=lambda _k: None,
                                 encrypt=lambda s: stick_crypt.create(s, password, config["unlock"], config["users"],
                                                                      free=4 * 1024 ** 3))
    assert ("close", str(stick.mount / "GamingCrypt.vc")) in vc.calls  # (closed before the stick was unmounted)
    assert now.encrypted and now.host == new
    assert (now.mount / "Emulation" / "roms" / "snes").is_dir() and (now.mount / "Windows Games").is_dir()
    assert not (new / "Emulation").exists()  # the folders are inside, not on the stick itself


def test_rekey_when_the_admins_code_changes(tmp_path, vc, config):
    old = drive_password(config)
    stick = encrypted_stick(tmp_path, vc, old, config)
    volume = stick.mount / stick_crypt.CONTAINER
    stick_crypt.open_stick(stick, old)
    assert stick_crypt.rekey(volume, old, "new password", config["unlock"], config["users"])
    assert vc.passwords[str(volume)] == "new password" and stick_crypt.is_open(volume)  # open again after


# --- unlocking one with an earlier code -----------------------------------------------------------

def test_unlock_with_an_earlier_code_gives_it_todays(qtbot, tmp_path, vc, config):
    from gamingcrypt.ui.unlock_stick import UnlockStick

    earlier = dict(config, unlock=dict(config["unlock"], kdf=dict(kdf.new_params(), **FAST), keyring=None), users=[])
    old = kdf.derive_password("1111", earlier["unlock"]["kdf"])
    stick = encrypted_stick(tmp_path, vc, old, earlier)
    today = drive_password(config)
    stick_crypt.keys.set(today)
    drives = Drives(run=Lsblk(stick.mount))
    drives.look()
    locked = drives.unusable[0]
    box = UnlockStick(locked, config)
    qtbot.addWidget(box)
    assert box.methods == ["pin"]
    done = []
    box.unlocked.connect(done.append)
    box.try_code("2222")
    qtbot.waitUntil(lambda: not box.working)
    assert "doesn't fit" in box.status.text() and done == []
    box.try_code("1111")
    qtbot.waitUntil(lambda: bool(done) or not box.working)
    assert done, box.status.text()
    assert done == ["STICK is open - and opens with today's code from now on"]
    volume = str(stick.mount / stick_crypt.CONTAINER)
    assert vc.passwords[volume] == today
    assert sidecar.read_sidecar(volume)["kdf"] == config["unlock"]["kdf"]  # today's settings next to it
    drives.refused.clear()
    assert drives.look()[0].encrypted


# --- the Storage page and the format dialog -------------------------------------------------------

def check_code(config):
    """As the app checks it (MainWindow.password_for_code): the admin's 1234 -> the drive's password."""
    return lambda secret: drive_password(config) if secret == "1234" else None


def test_encrypting_asks_for_your_code(qtbot, monkeypatch, tmp_path, config):
    from gamingcrypt.ui.storage_page import StoragePage

    monkeypatch.setattr(removable, "formats", lambda: ["exfat"])
    made = []
    monkeypatch.setattr(removable, "format_drive", lambda drive, fstype, label, run=None, step=None, encrypt=None:
                        made.append(encrypt) or drive)
    monkeypatch.setattr(stick_crypt, "create", lambda stick, password, *_a, **_k: made.append(password) or stick)
    page = StoragePage(lambda: None, emulation_fn=lambda: None)
    page.config_fn, page.code_check_fn, page.code_method_fn = lambda: config, check_code(config), lambda: "pin"
    qtbot.addWidget(page)
    stick = Removable(tmp_path, "usb", "STICK", "/dev/sdb1", "exfat", "/dev/sdb")
    page.ask_format(stick)  # (no code known: a restart - it's asked for)
    box = page.formatter
    assert box.encrypt_button.isEnabled() and box.encrypting and box.encrypt_button.text() == "🔒 Encrypted: on"
    box.encrypt_button.click()
    assert not box.encrypting and box.encrypt_button.text() == "🔓 Encrypted: off"
    box.encrypt_button.click()
    box.choices["exfat"].click()
    assert box.code is not None and box.code.input.method == "pin" and box.format_button.isHidden()
    assert box.question.text() == "It's encrypted with your code - enter your PIN."
    box.start()
    assert not box.working  # (not without the code)
    box.code.try_code("0000")
    qtbot.waitUntil(lambda: not box.code.working)
    assert box.code.status.text() == "Wrong code - try again" and box.format_button.isHidden()
    box.code.try_code("1234")
    qtbot.waitUntil(lambda: box.code is None)
    assert box.password == drive_password(config) and "exFAT, encrypted" in box.question.text()
    assert not box.format_button.isHidden()  # the last question now
    box.format_button.click()
    qtbot.waitUntil(lambda: box.over)
    encrypt = made[0]
    encrypt(stick)
    assert made[1] == drive_password(config)  # the container: the drive's password, from the code
    assert stick_crypt.keys.password == drive_password(config)  # (and the sticks open with it now)


def test_without_encryption_no_code_is_asked(qtbot, tmp_path, config):
    from gamingcrypt.ui.format_drive import FormatConfirm

    box = FormatConfirm(Removable(tmp_path, "usb", "STICK", disk="/dev/sdb"), formats=["exfat"],
                        encrypt=lambda *a, **k: None, check_code=check_code(config), method="pin")
    qtbot.addWidget(box)
    box.encrypt_button.click()
    box.choose("exfat")
    assert box.code is None and not box.format_button.isHidden()


def test_a_locked_stick_is_unlocked_with_your_code(qtbot, tmp_path, vc, config):
    from gamingcrypt.ui.storage_page import StoragePage

    stick = encrypted_stick(tmp_path, vc, drive_password(config), config)
    drives = Drives(run=Lsblk(stick.mount))
    drives.look()  # (GamingCrypt started again while unlocked: the code isn't known)
    locked = drives.unusable[0]
    page = StoragePage(lambda: None, emulation_fn=lambda: None)
    page.config_fn, page.code_check_fn, page.code_method_fn = lambda: config, check_code(config), lambda: "pin"
    qtbot.addWidget(page)
    page.show()
    looked = []
    page.drives_changed.connect(lambda: looked.append(1))
    page.set_drives([], [locked])
    unlock = page.drive_rows[("unusable", "/dev/sdb", "/dev/sdb1")][3]
    assert unlock.text() == "🔓 Unlock…"
    unlock.click()
    prompt = page.code_prompt
    assert prompt.question.text() == "It's encrypted with your code. Enter your PIN."
    prompt.entry.try_code("1234")
    qtbot.waitUntil(lambda: page.code_prompt is None)
    assert stick_crypt.keys.password == drive_password(config) and looked == [1]
    assert drives.look()[0].encrypted  # open now


def test_format_dialog_shows_the_container_being_made(qtbot, tmp_path, config, monkeypatch):
    from gamingcrypt.ui.format_drive import FormatConfirm

    box = FormatConfirm(Removable(tmp_path, "usb", "STICK", disk="/dev/sdb"), formats=["exfat"],
                        encrypt=lambda stick, password, progress=None: stick, check_code=check_code(config))
    qtbot.addWidget(box)
    box.password = "pw"
    box.choose("exfat")
    box.working, box.started_at = True, box.clock()
    box.reached += ["check", "unmount", "table", "filesystem", "mount", "encrypt"]
    box.percent = 42.0
    for key, label in box.step_labels.items():
        label.setVisible(True)
    box.show_steps()
    assert box.step_labels["encrypt"].text() == "◐  Encrypting it (a VeraCrypt container, your code)… 42%"
    assert box.bar.value() == 542 and box.bar.maximum() == 700


def test_storage_lists_an_encrypted_stick_and_offers_unlock(qtbot, tmp_path, vc, config, monkeypatch):
    from gamingcrypt.ui.storage_page import StoragePage

    page = StoragePage(lambda: None, emulation_fn=lambda: None)
    page.config_fn = lambda: config
    qtbot.addWidget(page)
    page.show()
    opened = Removable(tmp_path / "in", "usb", "GAMES", "/dev/sdb1", "ext4", "/dev/sdb", container="x", host=tmp_path)
    opened.mount.mkdir()
    earlier = Removable(tmp_path, "sd", "OLD", "/dev/sdc1", "exfat", "/dev/sdc", container="y", host=tmp_path,
                        problem=stick_crypt.EARLIER)
    page.set_drives([opened], [earlier])
    text = page.drive_rows[opened][0].text()
    assert "GAMES\nUSB stick  ·  🔒 encrypted" in text
    row = page.drive_rows[("unusable", "/dev/sdc", "/dev/sdc1")]
    assert row[3].text() == "🔓 Unlock…"
    monkeypatch.setattr("gamingcrypt.ui.unlock_stick.methods_of", lambda _v: ["pin", "pattern"])
    row[3].click()
    assert page.unlocker is not None and set(page.unlocker.method_buttons) == {"pin", "pattern"}
    page.unlocker.method_buttons["pattern"].click()
    assert page.unlocker.input.method == "pattern"
    page.unlocker.cancel_button.click()
    assert page.unlocker is None


# --- the app: the password while it's unlocked, a changed code, udev ---------------------------------

def test_the_password_is_learned_at_login_and_forgotten_at_the_lock(qtbot, config):
    from PySide6.QtCore import QObject

    from gamingcrypt.app import MainWindow

    class App(QObject):
        screen_name = "shell"
        learn_drive_password = MainWindow.learn_drive_password

        def __init__(self):
            super().__init__()
            self.config, self.looked = config, 0

        def look_for_drives(self):
            self.looked += 1

    app = App()
    app.learn_drive_password("mia", "9876")
    qtbot.waitUntil(lambda: app.looked == 1)
    assert stick_crypt.keys.password == drive_password(config)  # a user's code: the drive's password


def test_a_changed_admin_code_rekeys_the_sticks_that_are_in(qtbot, config, monkeypatch):
    from PySide6.QtCore import QObject

    from gamingcrypt.app import MainWindow

    rekeyed = []
    monkeypatch.setattr(stick_crypt, "rekey", lambda v, old, new, *_a, **_k: rekeyed.append((v, old, new)) or True)
    monkeypatch.setattr(users, "current", lambda _cfg: SimpleNamespace(id=users.ADMIN))

    class App(QObject):
        screen_name = "shell"
        learn_drive_password = MainWindow.learn_drive_password
        code_changed_to = MainWindow.code_changed_to

        def __init__(self):
            super().__init__()
            self.config, self.drives = config, SimpleNamespace(opened={"/s/GamingCrypt.vc"})

        def remember_code(self, _secret):
            pass

        def look_for_drives(self):
            pass

        def notify(self, *_a):
            pass

    old = drive_password(config)
    stick_crypt.keys.set(old)
    config["unlock"]["kdf"] = dict(kdf.new_params(), **FAST)  # (Settings → Security wrote the new one)
    App().code_changed_to("5555")
    new = kdf.derive_password("5555", config["unlock"]["kdf"])
    qtbot.waitUntil(lambda: bool(rekeyed))
    assert rekeyed == [("/s/GamingCrypt.vc", old, new)] and stick_crypt.keys.password == new


def test_udev_says_a_stick_came_and_its_looked_at_right_away(qtbot):
    from PySide6.QtCore import QObject

    from gamingcrypt.app import MainWindow

    class App(QObject):
        UDEV_MONITOR = ["sh", "-c", "echo 'UDEV [1] add /block/sdb (block)'; echo 'UDEV [2] add /block/sdb/sdb1'; "
                                    "sleep 5"]
        watch_udev = MainWindow.watch_udev
        _udev_event = MainWindow._udev_event

        def __init__(self):
            super().__init__()
            self.looked = 0

        def look_for_drives(self):
            self.looked += 1

    app = App()
    app.watch_udev()
    qtbot.waitUntil(lambda: app.looked >= 1, timeout=3000)
    qtbot.wait(300)
    assert app.looked == 1  # two events, one look
    app.udev.kill()
    app.udev.waitForFinished(1000)


# --- the game's page follows its stick -----------------------------------------------------------

def test_a_game_page_says_when_its_stick_is_out_and_comes_back(qtbot, tmp_path):
    import copy

    from gamingcrypt.config import DEFAULTS
    from gamingcrypt.emulation.library import EmulationPaths
    from gamingcrypt.ui.games_tab import GamesTab
    from tests.fakes import FakeService

    paths = EmulationPaths(tmp_path / "GamingCrypt" / "Emulation")
    paths.ensure()
    stick = Removable(tmp_path / "STICK", "usb", "STICK")
    rom = stick.mount / "roms" / "snes" / "Earthbound (USA).sfc"
    rom.parent.mkdir(parents=True)
    rom.write_bytes(b"x")
    tab = GamesTab(FakeService(), library_settings=copy.deepcopy(DEFAULTS)["libraries"], emulation_root=str(paths.root))
    qtbot.addWidget(tab)
    tab.show()
    tab.set_drives([stick])
    qtbot.waitUntil(lambda: "snes" in tab.roms)
    tab.open_rom(tab.roms["snes"][0])
    page = tab.currentWidget()
    assert page.main_button.isEnabled() and page.cover.badge == "usb"
    tab.set_drives([])
    qtbot.waitUntil(lambda: page.gone)
    assert not page.main_button.isEnabled()
    assert "put its USB stick in again" in page.status.text()
    moved = replace(stick, mount=tmp_path / "AGAIN")  # back in - mounted somewhere else this time
    stick.mount.rename(moved.mount)
    tab.set_drives([moved])
    qtbot.waitUntil(lambda: not page.gone)
    assert page.main_button.isEnabled() and page.game.path == moved.mount / "roms" / "snes" / "Earthbound (USA).sfc"
    assert page.status.text() == ""


# --- the app checks the code -----------------------------------------------------------------------

def test_the_code_is_checked_before_its_used(qtbot, config, monkeypatch):
    from gamingcrypt.app import MainWindow
    from gamingcrypt.unlock import verifier

    app = SimpleNamespace(config=config, verifier=verifier.make("1234"))
    monkeypatch.setattr(users, "current", lambda _cfg: SimpleNamespace(id=users.ADMIN, admin=True))
    assert MainWindow.password_for_code(app, "1234") == drive_password(config)
    assert MainWindow.password_for_code(app, "4321") is None  # not the code that unlocked
    app.verifier = None  # (its check is gone: the admin's key slot says)
    assert MainWindow.password_for_code(app, "1234") == drive_password(config)
    assert MainWindow.password_for_code(app, "4321") is None
    config["unlock"].pop("keyring")  # nothing to check it with at all: not taken on trust
    assert MainWindow.password_for_code(app, "1234") is None
    stick_crypt.keys.set(drive_password(config))  # ... unless the password is known: it has to match
    assert MainWindow.password_for_code(app, "1234") == drive_password(config)
    assert MainWindow.password_for_code(app, "4321") is None


def test_a_users_code_gives_the_drives_password(config, monkeypatch):
    from gamingcrypt.app import MainWindow
    from gamingcrypt.unlock import verifier

    monkeypatch.setattr(users, "current", lambda _cfg: SimpleNamespace(id="mia", admin=False))
    app = SimpleNamespace(config=config, verifier=verifier.make("9876"))
    assert MainWindow.password_for_code(app, "9876") == drive_password(config)
    assert MainWindow.password_for_code(app, "1234") is None  # the admin's isn't Mia's
