import pytest

from gamingcrypt.system.battery import BatteryState, read_battery
from gamingcrypt.ui.shell import Shell


def supply(root, name, **files):
    d = root / "class" / "power_supply" / name
    d.mkdir(parents=True)
    for key, value in files.items():
        (d / key).write_text(f"{value}\n")


def test_no_battery(tmp_path):
    supply(tmp_path, "AC", type="Mains", online=1)
    assert read_battery(tmp_path) is None
    assert read_battery(tmp_path / "nothing") is None


@pytest.mark.parametrize("status,mains,expected", [
    ("Discharging", 0, BatteryState(57, False, False)),
    ("Charging", 1, BatteryState(57, True, True)),
    ("Full", 1, BatteryState(57, False, True)),
    ("Not charging", 0, BatteryState(57, False, True)),  # e.g. charge limit reached, plugged in
])
def test_states(tmp_path, status, mains, expected):
    supply(tmp_path, "BAT0", type="Battery", capacity=57, status=status)
    supply(tmp_path, "AC", type="Mains", online=mains)
    # a USB-C source reporting "Charging" must not be taken for the battery
    supply(tmp_path, "ucsi-source-psy-USBC000:001", type="USB", status="Charging", online=1)
    assert read_battery(tmp_path) == expected


def test_controller_batteries_are_ignored_and_energy_fallback(tmp_path):
    supply(tmp_path, "sony_controller_battery_00:11", type="Battery", scope="Device", capacity=5,
           status="Discharging")
    supply(tmp_path, "BAT1", type="Battery", energy_now=30, energy_full=40, status="Discharging")
    assert read_battery(tmp_path) == BatteryState(75, False, False)


def test_labels():
    assert BatteryState(82, True, True).label == "⚡ 82%"
    assert BatteryState(82, False, False).label == "🔋 82%"
    assert BatteryState(12, False, False).low and not BatteryState(12, True, True).low


def test_real_battery_does_not_crash():
    state = read_battery()
    assert state is None or 0 <= state.percent <= 100


def test_shell_shows_battery_left_of_power_button(qtbot):
    states = iter([BatteryState(82, False, False), BatteryState(83, True, True), BatteryState(9, False, False)])
    shell = Shell(battery_reader=lambda: next(states))
    qtbot.addWidget(shell)
    shell.show()
    assert shell.battery.text() == "🔋 82%" and shell.battery.isVisible()
    assert shell.battery.x() < shell.exit_button.x()  # left of ⏻
    shell.update_battery()
    assert shell.battery.text() == "⚡ 83%" and shell.battery.property("charging") is True
    shell.update_battery()
    assert shell.battery.property("low") is True
    assert shell.battery_timer.isActive()


def test_shell_without_battery(qtbot):
    shell = Shell(battery_reader=lambda: None)
    qtbot.addWidget(shell)
    shell.show()
    assert not shell.battery.isVisible()
