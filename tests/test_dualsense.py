"""PS5 controller adaptive triggers: the reports, finding the controller, the settings page."""

import binascii
import copy
import io

from gamingcrypt.input import dualsense as ds


def test_stop_and_resistance_bytes():
    stop = ds.effect_bytes(ds.Effect(ds.STOP, 50, 6))
    assert stop[0] == 0x25 and int.from_bytes(stop[1:3], "little") == (1 << 5) | (1 << 6) and stop[3] == 5
    assert len(stop) == 11 and not any(stop[4:])
    low = ds.effect_bytes(ds.Effect(ds.STOP, 10, 1))  # the controller's limits: zones 2 .. 8
    assert int.from_bytes(low[1:3], "little") == (1 << 2) | (1 << 3) and low[3] == 0
    res = ds.effect_bytes(ds.Effect(ds.RESISTANCE, 70, 8))
    assert res[0] == 0x21 and int.from_bytes(res[1:3], "little") == 0b1110000000
    forces = int.from_bytes(res[3:7], "little")
    assert all((forces >> (3 * i)) & 7 == (7 if i >= 7 else 0) for i in range(10))
    assert ds.effect_bytes(ds.Effect())[0] == 0x05


def test_usb_and_bluetooth_reports():
    lt, rt = ds.Effect(ds.STOP, 50, 6), ds.Effect()
    usb = ds.report(lt, rt, ds.BUS_USB)
    assert usb[0] == 0x02 and usb[1] == 0x0C and len(usb) == 48
    assert usb[11] == 0x05 and usb[22] == 0x25  # right trigger first, then left
    bt = ds.report(lt, rt, ds.BUS_BLUETOOTH, seq=3)
    assert len(bt) == 78 and bt[0] == 0x31 and bt[1] == 0x30 and bt[2] == 0x10 and bt[3] == 0x0C
    assert bt[13] == 0x05 and bt[24] == 0x25
    assert int.from_bytes(bt[74:], "little") == binascii.crc32(b"\xa2" + bt[:74]) & 0xFFFFFFFF


def hidraw(root, name, hid_id):
    node = root / "class/hidraw" / name / "device"
    node.mkdir(parents=True)
    (node / "uevent").write_text(f"DRIVER=playstation\nHID_ID={hid_id}\nHID_NAME=x\n")


def test_find_and_send(tmp_path):
    hidraw(tmp_path, "hidraw3", "0003:0000054C:00000CE6")
    hidraw(tmp_path, "hidraw5", "0005:0000054C:00000DF2")
    hidraw(tmp_path, "hidraw1", "0003:0000045E:0000028E")  # an Xbox pad
    found = ds.find(tmp_path, dev=tmp_path)
    assert [(c.name, c.bus) for c in found] == [("DualSense", 3), ("DualSense Edge", 5)]
    written = {}

    class Sink(io.BytesIO):
        def __init__(self, path):
            super().__init__()
            self.path = path

        def close(self):
            written[self.path] = self.getvalue()
            super().close()

    cfg = {"input": {"adaptive_triggers": {"lt": {"effect": "stop", "position": 50, "strength": 6}}}}
    assert ds.apply(cfg, found, opener=lambda path, *a, **k: Sink(path)) == (2, "")
    assert written[found[0].path][22] == 0x25 and len(written[found[1].path]) == 78

    def denied(path, *a, **k):
        raise PermissionError(13, "Permission denied")

    done, error = ds.apply(cfg, found, opener=denied)
    assert done == 0 and "Settings → System" in error


def test_page_saves_and_sends(qtbot):
    from gamingcrypt.config import DEFAULTS
    from gamingcrypt.ui.adaptive_triggers import AdaptiveTriggersSection

    cfg = copy.deepcopy(DEFAULTS)
    saved, sent = [], []
    pad = ds.Controller("/dev/hidraw3", ds.BUS_BLUETOOTH, "DualSense")
    section = AdaptiveTriggersSection(cfg, saved.append, send=lambda c: sent.append(copy.deepcopy(c)) or (1, ""),
                                      find=lambda: [pad])
    qtbot.addWidget(section)
    assert "DualSense (Bluetooth)" in section.connected.text()
    section.aim_button.click()
    assert cfg["input"]["adaptive_triggers"]["lt"] == {"effect": "stop", "position": 50, "strength": 6}
    assert saved and sent[-1]["input"]["adaptive_triggers"]["lt"]["effect"] == "stop"
    assert "pull the trigger" in section.status.text()
    section.boxes["rt"].kind.setCurrentIndex(section.boxes["rt"].kind.findData(ds.RESISTANCE))
    assert cfg["input"]["adaptive_triggers"]["rt"]["effect"] == "resistance"
    section.off_button.click()
    assert all(v["effect"] == "off" for v in cfg["input"]["adaptive_triggers"].values())
    none = AdaptiveTriggersSection(cfg, saved.append, send=lambda c: (0, ""), find=lambda: [])
    qtbot.addWidget(none)
    assert "No PS5 controller" in none.connected.text()


def test_bump_is_one_zone_of_resistance():
    bump = ds.effect_bytes(ds.Effect(ds.BUMP, 50, 6))
    assert bump[0] == 0x21 and int.from_bytes(bump[1:3], "little") == 1 << 5
    forces = int.from_bytes(bump[3:7], "little")
    assert forces == 5 << 15  # only zone 5, strength 6
    assert ds.Effect.from_dict({"effect": "bump"}).kind == ds.BUMP
