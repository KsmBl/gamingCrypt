"""Power limit on AMD APUs without a power1_cap file (AYANEO 2021 Pro: Ryzen 7 4800U)
through the SMU mailbox - like RyzenAdj, built into the root helper."""

import struct
from pathlib import Path

import pytest

from gamingcrypt.helper import veracrypt_helper as helper
from gamingcrypt.system import power

CPUINFO_4800U = """processor\t: 0
vendor_id\t: AuthenticAMD
cpu family\t: 23
model\t\t: 96
model name\t: AMD Ryzen 7 4800U with Radeon Graphics

processor\t: 1
vendor_id\t: AuthenticAMD
"""
CPUINFO_INTEL = "processor\t: 0\nvendor_id\t: GenuineIntel\ncpu family\t: 6\nmodel\t\t: 140\n"


def test_cpu_detection_and_ranges():
    assert helper.cpu_info(CPUINFO_4800U) == (23, 96, "AMD Ryzen 7 4800U with Radeon Graphics")
    assert helper.cpu_info(CPUINFO_INTEL) is None
    assert helper.smu_range(23, 96, "AMD Ryzen 7 4800U with Radeon Graphics") == (5, 28)
    assert helper.smu_range(25, 80, "AMD Ryzen 9 5900HS with Radeon Graphics") == (5, 45)
    assert helper.smu_range(23, 144, "AMD Custom APU 0405") == (5, 20)  # Steam Deck class
    assert helper.smu_range(23, 1, "AMD Ryzen 7 1700") is None  # desktop CPU: no mailbox known


class FakeSmu(helper.Smu):
    """In-memory SMN registers; the 'firmware' answers every message with OK."""

    def __init__(self, family, model, sys_root="", answer=helper.SMU_OK, writable=True):
        _n, box, msgs = helper.SMU_FAMILIES[(family, model)]
        self.msg_addr, self.rep_addr, self.arg_addr = helper.MAILBOXES[box]
        self.limit_msgs = helper.LIMIT_MSGS[msgs]
        self.timeout = 0.05
        self.regs, self.sent, self.answer, self.writable = {}, [], answer, writable

    def close(self):
        pass

    def write(self, addr, value):
        if not self.writable:
            return
        self.regs[addr] = value
        if addr == self.msg_addr:
            self.sent.append((value, self.regs.get(self.arg_addr)))
            if self.answer:
                self.regs[self.rep_addr] = self.answer

    def read(self, addr):
        return self.regs.get(addr, 0)


def test_smu_sets_all_three_limits_in_milliwatts(tmp_path):
    made = []
    state = tmp_path / "state"

    def factory(family, model, root):
        made.append(FakeSmu(family, model))
        return made[-1]

    assert helper.set_smu_power_limit(12, cpuinfo=CPUINFO_4800U, smu_factory=factory, state_file=str(state)) == 0
    assert made[0].sent == [(0x1, 0), (0x14, 12000), (0x15, 12000), (0x16, 12000)]  # test msg first
    assert state.read_text() == "12\n"  # the UI shows it as the current value


@pytest.mark.parametrize("watts", [4, 29, 100])
def test_smu_refuses_outside_range(watts, tmp_path):
    made = []
    rc = helper.set_smu_power_limit(watts, cpuinfo=CPUINFO_4800U, state_file=None,
                                    smu_factory=lambda *a: made.append(1) or FakeSmu(23, 96))
    assert rc == 2 and made == []  # never touches the hardware


def test_smu_errors(capsys):
    assert helper.set_smu_power_limit(10, cpuinfo=CPUINFO_INTEL, state_file=None) == 2
    assert "no adjustable power limit" in capsys.readouterr().err
    locked = lambda *a: FakeSmu(23, 96, writable=False)  # noqa: E731 - kernel lockdown
    assert helper.set_smu_power_limit(10, cpuinfo=CPUINFO_4800U, smu_factory=locked, state_file=None) == 2
    assert "Secure Boot" in capsys.readouterr().err
    silent = lambda *a: FakeSmu(23, 96, answer=0)  # noqa: E731 - no answer: timeout, no hang
    assert helper.set_smu_power_limit(10, cpuinfo=CPUINFO_4800U, smu_factory=silent, state_file=None) == 2
    assert "didn't answer" in capsys.readouterr().err
    refused = lambda *a: FakeSmu(23, 96, answer=0xFE)  # noqa: E731
    assert helper.set_smu_power_limit(10, cpuinfo=CPUINFO_4800U, smu_factory=refused, state_file=None) == 2


def test_smn_access_through_pci_config(tmp_path):
    config = tmp_path / helper.PCI_ROOT
    config.parent.mkdir(parents=True)
    config.write_bytes(bytes(256))
    smu = helper.Smu(23, 96, sys_root=str(tmp_path))
    try:
        smu.write(0x3B10998, 0x47)
        data = config.read_bytes()
        assert struct.unpack("<I", data[0xB8:0xBC])[0] == 0x3B10998  # index register
        assert struct.unpack("<I", data[0xBC:0xC0])[0] == 0x47  # data register
        assert smu.read(0x3B10999) == 0x47  # aligned address
    finally:
        smu.close()


def test_ui_side_shows_the_same_range(tmp_path):
    state = tmp_path / "state"
    limit = power.read_limit(tmp_path / "sys", cpuinfo=CPUINFO_4800U, state=state)
    assert (limit.min_w, limit.max_w, limit.current_w) == (5, 28, 15) and "Renoir" in limit.source
    state.write_text("9\n")
    assert power.read_limit(tmp_path / "sys", cpuinfo=CPUINFO_4800U, state=state).current_w == 9
    assert power.read_limit(tmp_path / "sys", cpuinfo=CPUINFO_INTEL, state=state) is None
