"""Users: an admin and the people the admin adds - each with a code that opens the same volume."""

import copy
import os
import json

import pytest

from gamingcrypt import users
from gamingcrypt.config import DEFAULTS, load_config, save_config
from gamingcrypt.unlock import kdf, keyslots

FAST = dict(n=2**4, r=8, p=1)  # scrypt as in the app, only cheap


def config(method="pin"):
    cfg = copy.deepcopy(DEFAULTS)
    cfg["unlock"].update(method=method, volume=f"/tmp/gamingcrypt-test-{os.getpid()}.vc", kdf=kdf.new_params(**FAST))
    return cfg


ADMIN_CODE = "482916"


def verify(secret):
    return secret == ADMIN_CODE


# --- the boxes ---------------------------------------------------------------------------------

def test_seal_and_unseal():
    key, other = b"k" * 32, b"o" * 32
    box = keyslots.seal(key, b"the volume's password")
    assert keyslots.unseal(key, box) == b"the volume's password"
    assert keyslots.unseal(other, box) is None  # the wrong key: nothing, not rubbish
    assert b"password" not in bytes.fromhex(box["data"])
    assert keyslots.seal(key, b"the volume's password")["data"] != box["data"]  # a nonce each time
    for field in ("nonce", "data", "check"):  # changed afterwards: noticed
        broken = dict(box, **{field: ("00" if box[field][:2] != "00" else "ff") + box[field][2:]})
        assert keyslots.unseal(key, broken) is None
    assert keyslots.unseal(key, None) is None and keyslots.unseal(key, {"nonce": "zz"}) is None
    long = bytes(range(256)) * 3  # longer than one block of the key stream
    assert keyslots.unseal(key, keyslots.seal(key, long)) == long


def test_a_slot_opens_with_its_code_only():
    master = keyslots.new_master()
    slot = keyslots.new_slot("1234", master, kdf.new_params(**FAST))
    assert keyslots.open_slot("1234", slot) == master
    assert keyslots.open_slot("1235", slot) is None and keyslots.open_slot("1234", None) is None
    assert keyslots.open_slot("1234", dict(slot, kdf={"algorithm": "md5"})) is None
    vault = keyslots.new_vault(master, "pässword")
    assert keyslots.open_vault(master, vault) == "pässword" and keyslots.open_vault(b"x" * 32, vault) is None


def test_derive_password_is_what_it_always_was():
    """The admin's code -> the volume's password: not a byte different (existing volumes!)."""
    params = {"algorithm": "scrypt", "salt": "00112233445566778899aabbccddeeff", "n": 16, "r": 8, "p": 1}
    import base64
    import hashlib

    key = hashlib.scrypt(b"482916", salt=bytes.fromhex(params["salt"]), n=16, r=8, p=1, dklen=32)
    assert kdf.derive_password("482916", params) == base64.urlsafe_b64encode(key).rstrip(b"=").decode()
    assert kdf.derive_password("plain", None) == "plain"
    with pytest.raises(kdf.KDFError):
        kdf.derive_password("x", {"algorithm": "other"})


# --- who there is --------------------------------------------------------------------------------

def test_a_config_from_before_is_one_admin():
    cfg = config()
    assert "users" not in DEFAULTS and "keyring" not in cfg["unlock"]
    found = users.all_users(cfg)
    assert [(u.id, u.name, u.admin, u.method, u.age) for u in found] == [("admin", "admin", True, "pin", None)]
    assert users.current(cfg).id == "admin" and users.current(cfg).can_delete_games
    assert users.volume_password(cfg, "admin", ADMIN_CODE) == kdf.derive_password(ADMIN_CODE, cfg["unlock"]["kdf"])
    assert users.persistable(cfg) == cfg  # written as it was


def test_renaming():
    cfg = config()
    assert users.rename(cfg, "admin", "  Papa  ") == "Papa" and users.admin(cfg).name == "Papa"
    master = users.admin_master(cfg, ADMIN_CODE, verify)
    kid = users.add(cfg, "Mia", "pin", "1111", master)
    assert users.rename(cfg, kid.id, "Mia S.") == "Mia S." and users.get(cfg, kid.id).name == "Mia S."
    for bad in ("", "   ", "x" * 25, "papa", "MIA S."):
        with pytest.raises(users.UserError):
            users.rename(cfg, kid.id if bad.lower() != "mia s." else "admin", bad)
    assert users.rename(cfg, kid.id, "mia s.") == "mia s."  # one's own name, written differently


def test_every_users_code_opens_the_same_volume():
    cfg = config()
    password = kdf.derive_password(ADMIN_CODE, cfg["unlock"]["kdf"])
    with pytest.raises(users.UserError):
        users.admin_master(cfg, "000000", verify)  # the first user needs the admin's right code
    assert "keyring" not in cfg["unlock"]
    with pytest.raises(users.UserError, match="unlock it once"):
        users.admin_master(cfg, ADMIN_CODE)  # nothing to check the code against
    master = users.admin_master(cfg, ADMIN_CODE, verify)
    mia = users.add(cfg, "Mia", "pin", "1111", master, age=12)
    ben = users.add(cfg, "Ben", "pattern", "14789", master)
    assert [u.name for u in users.all_users(cfg)] == ["admin", "Mia", "Ben"] and mia.id != ben.id
    assert (mia.age, ben.age, mia.method, ben.method, mia.admin) == (12, None, "pin", "pattern", False)
    assert not mia.can_delete_games
    assert users.volume_password(cfg, mia.id, "1111") == password
    assert users.volume_password(cfg, ben.id, "14789") == password
    assert users.volume_password(cfg, mia.id, "14789") is None  # Ben's code isn't Mia's
    assert users.volume_password(cfg, mia.id, "1112") is None
    assert users.volume_password(cfg, "admin", ADMIN_CODE) == password  # as ever
    assert users.admin_master(cfg, ADMIN_CODE) == master  # from now on checked by itself
    with pytest.raises(users.UserError):
        users.admin_master(cfg, "000000")
    text = json.dumps(cfg)
    assert password not in text and master.hex() not in text and "1111" not in json.dumps(cfg["users"])


def test_it_survives_config_json(tmp_path):
    cfg = config()
    master = users.admin_master(cfg, ADMIN_CODE, verify)
    mia = users.add(cfg, "Mia", "pin", "1111", master, age=6)
    users.enter(cfg, mia.id)
    save_config(users.persistable(cfg), tmp_path / "config.json")
    again = load_config(tmp_path / "config.json")
    assert "session" not in again and users.current(again).id == "admin"  # nobody is logged in after a start
    assert users.get(again, mia.id).age == 6
    assert users.volume_password(again, mia.id, "1111") == kdf.derive_password(ADMIN_CODE, cfg["unlock"]["kdf"])


def test_new_code_and_removal():
    cfg = config()
    master = users.admin_master(cfg, ADMIN_CODE, verify)
    mia = users.add(cfg, "Mia", "pin", "1111", master)
    assert users.user_master(cfg, mia.id, "1111") == master and users.user_master(cfg, mia.id, "2222") is None
    users.set_code(cfg, mia.id, "password", "new one", users.user_master(cfg, mia.id, "1111"))  # by herself
    assert users.get(cfg, mia.id).method == "password"
    assert users.volume_password(cfg, mia.id, "1111") is None
    assert users.volume_password(cfg, mia.id, "new one") is not None
    users.set_age(cfg, mia.id, 16)
    users.set_age(cfg, mia.id, None)
    assert users.get(cfg, mia.id).age is None
    with pytest.raises(users.UserError):
        users.set_age(cfg, "admin", 12)
    with pytest.raises(users.UserError):
        users.remove(cfg, "admin")
    users.enter(cfg, mia.id)
    users.remove(cfg, mia.id)
    assert [u.id for u in users.all_users(cfg)] == ["admin"] and users.current(cfg).id == "admin"
    assert users.volume_password(cfg, mia.id, "new one") != users.volume_password(cfg, "admin", ADMIN_CODE)


def test_the_admin_changes_their_code_and_the_others_still_get_in():
    cfg = config()
    master = users.admin_master(cfg, ADMIN_CODE, verify)
    mia = users.add(cfg, "Mia", "pin", "1111", master)
    cfg["unlock"]["kdf"] = kdf.new_params(**FAST)  # the wizard re-keyed the volume
    cfg["unlock"]["method"] = "password"
    assert users.admin_code_changed(cfg, ADMIN_CODE, "a new password")
    new_password = kdf.derive_password("a new password", cfg["unlock"]["kdf"])
    assert users.volume_password(cfg, mia.id, "1111") == new_password
    assert users.admin_master(cfg, "a new password") == master
    with pytest.raises(users.UserError):
        users.admin_master(cfg, ADMIN_CODE)
    # the old code unknown (a volume set up anew): the users stay, their codes are gone
    cfg["unlock"]["kdf"] = kdf.new_params(**FAST)
    assert not users.admin_code_changed(cfg, "not the old one", "third")
    assert users.volume_password(cfg, mia.id, "1111") is None and not users.has_code(cfg, mia.id)
    assert [u.name for u in users.all_users(cfg)] == ["admin", "Mia"] and users.has_code(cfg, "admin")
    assert users.admin_code_changed(config(), "a", "b")  # no users: nothing to do


def test_each_user_has_steam_settings_of_their_own():
    cfg = config()
    cfg["steam"].update(api_key="A" * 32, steam_id="111", account="111", silent_install=True)
    master = users.admin_master(cfg, ADMIN_CODE, verify)
    mia = users.add(cfg, "Mia", "pin", "1111", master)
    users.enter(cfg, mia.id)
    assert cfg["steam"]["api_key"] == "" and cfg["steam"]["steam_id"] == ""  # nothing of the admin's
    assert cfg["steam"]["silent_install"] is True  # the device's settings are everybody's
    cfg["steam"].update(api_key="B" * 32, steam_id="222", silent_install=False)
    written = users.persistable(cfg)
    assert written["steam"]["api_key"] == "A" * 32 and written["steam"]["steam_id"] == "111"
    assert written["steam"]["silent_install"] is False and "session" not in written and "_admin_steam" not in written
    assert written["users"][0]["steam"]["api_key"] == "B" * 32
    assert cfg["steam"]["api_key"] == "B" * 32  # (what's in use isn't touched by writing)
    users.leave(cfg)
    assert cfg["steam"]["api_key"] == "A" * 32 and "session" not in cfg and "_admin_steam" not in cfg
    users.enter(cfg, mia.id)
    assert cfg["steam"]["api_key"] == "B" * 32 and cfg["steam"]["steam_id"] == "222"
    users.enter(cfg, "admin")
    assert cfg["steam"]["api_key"] == "A" * 32 and users.persistable(cfg)["steam"]["api_key"] == "A" * 32
    users.enter(cfg, "someone deleted")  # unknown: the admin
    assert users.current(cfg).admin


# --- unlocking ---------------------------------------------------------------------------------

class Volume:
    """VeraCrypt with one password."""

    def __init__(self, password):
        self.password, self.tried = password, []

    def factory(self, unlock_cfg):
        from gamingcrypt.unlock.veracrypt import UnlockResult

        volume = self

        class Unlocker:
            configured = True

            def unlock(self, secret):
                password = kdf.derive_password(secret, unlock_cfg.get("kdf"))
                volume.tried.append(password)
                ok = password == volume.password
                return UnlockResult(ok, "Unlocked" if ok else "Wrong code")

            def is_mounted(self):
                return False

        return Unlocker()


def with_users():
    cfg = config()
    master = users.admin_master(cfg, ADMIN_CODE, verify)
    mia = users.add(cfg, "Mia", "pattern", "14789", master, age=12)
    return cfg, mia, Volume(kdf.derive_password(ADMIN_CODE, cfg["unlock"]["kdf"]))


def test_a_users_code_unlocks_the_volume():
    cfg, mia, volume = with_users()
    unlocker = users.unlocker_for(cfg, mia, volume.factory)
    assert unlocker.configured and unlocker.unlock("14789").success
    assert volume.tried == [volume.password]
    result = unlocker.unlock("12369")
    assert not result.success and result.message == "Wrong code" and len(volume.tried) == 1  # VeraCrypt not asked
    assert users.unlocker_for(cfg, users.admin(cfg), volume.factory).unlock(ADMIN_CODE).success
    assert not users.unlocker_for(cfg, users.admin(cfg), volume.factory).unlock("14789").success  # Mia's isn't the admin's
    users.forget_codes(cfg)
    result = users.unlocker_for(cfg, mia, volume.factory).unlock("14789")
    assert not result.success and "admin can set one" in result.message


def test_a_users_code_on_an_open_drive():
    """The drive open already: the user's code is checked by their key slot (the drive stays open,
    VeraCrypt isn't asked) - a wrong code still doesn't get in."""
    cfg, mia, volume = with_users()
    seen = []

    def factory(unlock_cfg):
        seen.append(unlock_cfg)
        unlocker = volume.factory(unlock_cfg)
        unlocker.is_mounted = lambda: True
        return unlocker

    unlocker = users.unlocker_for(cfg, mia, factory)
    assert unlocker.unlock("14789").success and volume.tried == []
    assert not unlocker.unlock("12369").success
    assert seen[0]["keyring"] is None  # its base gets the volume's password, not the admin's code


def test_users_are_kept_next_to_a_container_file(tmp_path):
    from gamingcrypt.unlock import sidecar

    cfg, mia, _ = with_users()
    volume = tmp_path / "games.vc"
    volume.write_bytes(b"x")
    cfg["unlock"]["volume"] = str(volume)
    users.rename(cfg, "admin", "Papa")
    users.enter(cfg, mia.id)
    cfg["steam"]["api_key"] = "B" * 32
    assert users.write_sidecar(cfg)
    assert "B" * 32 not in sidecar.sidecar_path(str(volume)).read_text()  # no Steam keys next to the file
    lost = copy.deepcopy(DEFAULTS)  # config.json is gone
    found = sidecar.find_container({"volume": str(volume)})
    users.adopt(lost, found)
    assert [u.name for u in users.all_users(lost)] == ["Papa", "Mia"] and users.get(lost, mia.id).age == 12
    assert users.volume_password(lost, mia.id, "14789") == kdf.derive_password(ADMIN_CODE, cfg["unlock"]["kdf"])
    assert "users" not in lost["unlock"] and lost["unlock"]["volume"] == str(volume)
    plain = tmp_path / "plain.vc"  # a container from before there were users: as ever
    plain.write_bytes(b"x")
    assert sidecar.write_sidecar(str(plain), {"method": "pin", "kdf": None, "mount_point": "/m"})
    assert sidecar.read_sidecar(str(plain)) == {"method": "pin", "kdf": None, "mount_point": "/m"}


def test_lock_screen_without_more_users_is_as_it_was(qtbot):
    from gamingcrypt.ui.lock_screen import LockScreen

    cfg = config("pin")
    volume = Volume(kdf.derive_password(ADMIN_CODE, cfg["unlock"]["kdf"]))
    lock = LockScreen(volume.factory(cfg["unlock"]), "pin", users=users.all_users(cfg),
                      unlocker_for=lambda u: users.unlocker_for(cfg, u, volume.factory))
    qtbot.addWidget(lock)
    lock.show()
    assert not lock.user_row.isVisible() and lock.method == "pin" and lock.user.admin
    old = LockScreen(volume.factory(cfg["unlock"]), "pattern")  # as the app made it before
    qtbot.addWidget(old)
    assert old.method == "pattern" and old.user is None and not old.user_row.isVisibleTo(old)


def test_lock_screen_asks_who_and_takes_their_code(qtbot):
    from gamingcrypt.ui.lock_screen import LockScreen

    cfg, mia, volume = with_users()
    lock = LockScreen(volume.factory(cfg["unlock"]), "pin", users=users.all_users(cfg),
                      unlocker_for=lambda u: users.unlocker_for(cfg, u, volume.factory))
    qtbot.addWidget(lock)
    lock.show()
    assert lock.user_row.isVisible() and list(lock.user_buttons) == ["admin", mia.id]
    assert lock.user.admin and lock.method == "pin" and lock.user_buttons["admin"].isChecked()
    assert [b.text() for b in lock.user_buttons.values()] == ["admin", "Mia"]
    accepted, unlocked = [], []
    lock.accepted.connect(accepted.append)
    lock.unlocked.connect(lambda: unlocked.append(lock.user.id))
    lock.user_buttons[mia.id].click()
    assert lock.user.id == mia.id and lock.method == "pattern" and "Swipe pattern" in lock.subtitle.text()
    assert lock.user_buttons[mia.id].isChecked() and not lock.user_buttons["admin"].isChecked()
    lock.input.secret_entered.emit(ADMIN_CODE)  # the admin's code as Mia: no
    qtbot.waitUntil(lambda: not lock.busy)
    assert "Wrong code" in lock.status.text() and unlocked == []
    lock.input.secret_entered.emit("14789")
    qtbot.waitUntil(lambda: unlocked == [mia.id])
    assert accepted == ["14789"]
    again = LockScreen(volume.factory(cfg["unlock"]), "pin", users=users.all_users(cfg), user_id=mia.id,
                       unlocker_for=lambda u: users.unlocker_for(cfg, u, volume.factory))
    qtbot.addWidget(again)
    assert again.user.id == mia.id and again.method == "pattern"  # who was there last
