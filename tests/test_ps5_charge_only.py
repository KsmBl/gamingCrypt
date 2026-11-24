"""PS5 controllers: charge only over USB - the cable powers it, it stays on Bluetooth (stronger triggers)."""

import copy
import os
import subprocess

import pytest

from gamingcrypt.helper import veracrypt_helper as helper
from gamingcrypt.input import dualsense


def fake_sys(tmp_path, devices):
    """A /sys with these USB devices: name -> (vendor, product)."""
    root = tmp_path / "sys"
    bus = root / "bus/usb/devices"
    bus.mkdir(parents=True)
    for name, (vendor, product) in devices.items():
        real = root / "devices/pci0000:00/usb1" / name
        real.mkdir(parents=True)
        (real / "idVendor").write_text(vendor + "\n")
        (real / "idProduct").write_text(product + "\n")
        (real / "authorized").write_text("1\n")
        (bus / name).symlink_to(real)
    return root


def bluetooth(powered=True, paired="Device AA:BB:CC:DD:EE:FF DualSense Wireless Controller\n"):
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[1:] == ["show"]:
            return subprocess.CompletedProcess(cmd, 0, "Powered: yes\n" if powered else "Powered: no\n", "")
        if cmd[1:] == ["devices", "Paired"]:
            return subprocess.CompletedProcess(cmd, 0, paired, "")
        return subprocess.CompletedProcess(cmd, 0, "", "")

    run.calls = calls
    return run


def everything_there(path):
    return True


def authorized(root, name):
    return (root / "bus/usb/devices" / name / "authorized").read_text().strip()


def test_the_rule_calls_the_helper_for_ps5_controllers_only():
    rule = helper.charge_only_rule("/usr/local/lib/gamingcrypt/veracrypt-helper")
    assert 'ATTR{idVendor}=="054c"' in rule and 'ATTR{idProduct}=="0ce6|0df2"' in rule
    assert 'RUN+="/usr/local/lib/gamingcrypt/veracrypt-helper ps5-charge-only-device %S%p"' in rule


def test_only_ps5_controllers_in_sys_can_be_switched(tmp_path):
    root = fake_sys(tmp_path, {"1-1": ("054c", "0ce6"), "1-2": ("046d", "c52b"), "1-3": ("054c", "0df2")})
    assert [os.path.basename(d) for d in helper.ps5_usb_devices(str(root))] == ["1-1", "1-3"]
    assert not helper.is_ps5_usb(str(root / "bus/usb/devices/1-2"), str(root))
    assert not helper.is_ps5_usb("/etc", str(root))
    assert helper.charge_only_device([str(root / "bus/usb/devices/1-2")], str(root), bluetooth(),
                                      everything_there) == 2
    assert authorized(root, "1-2") == "1"


@pytest.mark.parametrize("powered, paired, refused", [
    (True, "Device AA:BB DualSense Wireless Controller\n", True),
    (False, "Device AA:BB DualSense Wireless Controller\n", False),  # Bluetooth off: the cable is its way in
    (True, "Device 11:22 Some headphones\n", False),  # never paired: it couldn't come back over Bluetooth
])
def test_plugged_in_its_usb_is_refused_only_when_bluetooth_can_take_it(tmp_path, powered, paired, refused):
    root = fake_sys(tmp_path, {"1-1": ("054c", "0ce6")})
    device = str(root / "devices/pci0000:00/usb1/1-1")
    assert helper.charge_only_device([device], str(root), bluetooth(powered, paired), everything_there) == 0
    assert authorized(root, "1-1") == ("0" if refused else "1")


def test_switched_on_and_off(tmp_path):
    root = fake_sys(tmp_path, {"1-1": ("054c", "0ce6"), "1-2": ("046d", "c52b")})
    rule = tmp_path / "74.rules"
    run = bluetooth()
    assert helper.set_charge_only(["on"], "/helper", str(root), run, everything_there, str(rule)) == 0
    assert "ps5-charge-only-device" in rule.read_text()
    assert ["/usr/bin/udevadm", "control", "--reload-rules"] in run.calls
    assert authorized(root, "1-1") == "0" and authorized(root, "1-2") == "1"  # the one on a cable now too
    assert helper.set_charge_only(["off"], "/helper", str(root), run, everything_there, str(rule)) == 0
    assert not rule.exists() and authorized(root, "1-1") == "1"  # on USB again
    assert helper.set_charge_only(["maybe"], "/helper", str(root), run, everything_there, str(rule)) == 2


def test_switched_on_without_bluetooth_the_cable_stays_its_way_in(tmp_path):
    root = fake_sys(tmp_path, {"1-1": ("054c", "0ce6")})
    rule = tmp_path / "74.rules"
    assert helper.set_charge_only(["on"], "/helper", str(root), bluetooth(powered=False), everything_there,
                                  str(rule)) == 0
    assert rule.exists() and authorized(root, "1-1") == "1"


def test_the_helper_is_asked(monkeypatch):
    from gamingcrypt.system import helper_status

    monkeypatch.setattr(helper_status, "outdated", lambda *a, **k: False)
    calls = []

    def runner(cmd, **kwargs):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    assert dualsense.set_charge_only(True, "/h", runner, lambda p: True) == (True, "")
    assert calls == [["sudo", "-n", "/h", "ps5-charge-only", "on"]]
    assert dualsense.set_charge_only(True, "/h", runner, lambda p: False)[0] is False  # not installed
    monkeypatch.setattr(helper_status, "outdated", lambda *a, **k: True)
    assert dualsense.set_charge_only(False, "/h", runner, lambda p: True) == (False, helper_status.OUTDATED)


def test_the_switch_on_the_page(qtbot):
    from gamingcrypt.config import DEFAULTS
    from gamingcrypt.ui.adaptive_triggers import AdaptiveTriggersSection

    cfg = copy.deepcopy(DEFAULTS)
    asked, answers = [], [(True, ""), (False, "Run ./install.sh to allow this")]
    section = AdaptiveTriggersSection(cfg, lambda c: None, send=lambda c: (0, ""), find=lambda: [],
                                      set_charge=lambda on: asked.append(on) or answers.pop(0))
    qtbot.addWidget(section)
    assert not section.charge_only.isChecked() and section.charge_only.text().startswith("☐")
    section.charge_only.click()
    qtbot.waitUntil(lambda: section.charge_only.isEnabled())
    assert asked == [True] and dualsense.charge_only(cfg) and section.charge_only.text().startswith("☑")
    section.charge_only.click()  # the helper says no: as it was
    qtbot.waitUntil(lambda: "install.sh" in section.status.text())
    assert asked == [True, False] and section.charge_only.isChecked() and dualsense.charge_only(cfg)
