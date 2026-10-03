import copy
import json

from gamingcrypt.app import MainWindow
from gamingcrypt.config import DEFAULTS
from gamingcrypt.ui.auth_setup import AuthSetupWizard
from gamingcrypt.ui.lock_screen import LockScreen
from gamingcrypt.unlock import sidecar

KDF = {"algorithm": "scrypt", "salt": "aa" * 16, "n": 2, "r": 1, "p": 1}


def test_roundtrip(tmp_path):
    volume = tmp_path / "g.vc"
    volume.write_text("")
    assert sidecar.write_sidecar(str(volume), {"method": "grid5", "kdf": KDF, "mount_point": "/m"})
    assert sidecar.read_sidecar(str(volume)) == {"method": "grid5", "kdf": KDF, "mount_point": "/m"}
    assert json.loads((tmp_path / "g.vc.gamingcrypt.json").read_text())["version"] == 1


def test_not_written_for_devices_or_missing_files(tmp_path):
    assert not sidecar.write_sidecar("/dev/null", {"method": "pin"})
    assert not sidecar.write_sidecar(str(tmp_path / "missing.vc"), {"method": "pin"})
    assert not sidecar.write_sidecar("", {"method": "pin"})


def test_invalid_sidecars_are_ignored(tmp_path):
    volume = tmp_path / "g.vc"
    path = sidecar.sidecar_path(str(volume))
    assert sidecar.read_sidecar(str(volume)) is None
    for content in ["{broken", "[]", '{"method": "telepathy"}', '{"method": "pin", "kdf": "x"}']:
        path.write_text(content)
        assert sidecar.read_sidecar(str(volume)) is None


def test_find_container_prefers_configured_volume(tmp_path, isolated_home):
    configured = tmp_path / "mine.vc"
    configured.write_text("")
    sidecar.write_sidecar(str(configured), {"method": "pin", "kdf": KDF})
    default = isolated_home / "GamingCrypt.vc"
    default.write_text("")
    sidecar.write_sidecar(str(default), {"method": "password"})
    assert sidecar.find_container({"volume": str(configured)})["volume"] == str(configured)
    assert sidecar.find_container({})["method"] == "password"
    assert sidecar.existing_container({}) == str(default)


def test_nothing_found(isolated_home):
    assert sidecar.find_container({}) is None
    assert sidecar.existing_container({}) is None


def test_start_with_existing_container_goes_straight_to_unlock(qtbot, isolated_home):
    default = isolated_home / "GamingCrypt.vc"
    default.write_text("")
    sidecar.write_sidecar(str(default), {"method": "grid5", "kdf": KDF, "mount_point": str(isolated_home / "G")})
    saved = []
    window = MainWindow(copy.deepcopy(DEFAULTS), saved.append)
    qtbot.addWidget(window)
    assert window.screen_name == "lock"
    lock = window.stack.currentWidget()
    assert isinstance(lock, LockScreen) and lock.method == "grid5"
    assert lock.unlocker.kdf == KDF and lock.unlocker.volume == str(default)
    assert saved[-1]["unlock"]["method"] == "grid5"  # config repaired


def test_start_with_container_without_sidecar_asks_for_its_password(qtbot, isolated_home):
    (isolated_home / "GamingCrypt.vc").write_text("")
    window = MainWindow(copy.deepcopy(DEFAULTS), lambda c: None)
    qtbot.addWidget(window)
    wizard = window.stack.currentWidget()
    assert isinstance(wizard, AuthSetupWizard)
    assert wizard.step == "current" and not wizard.create_button.isVisibleTo(wizard)


def test_start_without_container_offers_create(qtbot):
    window = MainWindow(copy.deepcopy(DEFAULTS), lambda c: None)
    qtbot.addWidget(window)
    wizard = window.stack.currentWidget()
    assert wizard.step == "source" and wizard.create_button.isVisibleTo(wizard)
