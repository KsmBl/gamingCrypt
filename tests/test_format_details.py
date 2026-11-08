"""Formatting: the stick's name (typed, also on the on-screen keyboard) and how much of it is encrypted -
a step of its own, that fits any screen."""

from pathlib import Path

import pytest

from gamingcrypt.system import removable
from gamingcrypt.system.removable import Removable
from gamingcrypt.ui.modal import show_modal
from tests.test_code_dialogs import rect_in, screen, shown_parts

SCREENS = [(1280, 800), (1280, 720), (1920, 1080), (1366, 768), (1024, 600)]
STICK = Removable(Path("/x"), "usb", "OLD NAME", "/dev/sdb1", "exfat", "/dev/sdb", 64 * 1024 ** 3)


def dialog(qtbot, host, encrypt=True, check=None):
    from gamingcrypt.ui.format_drive import FormatConfirm

    box = FormatConfirm(STICK, formats=["exfat", "ext4"],
                        encrypt=(lambda *a, **k: None) if encrypt else None,
                        check_code=check or (lambda _s: "pw"), method="pin")
    show_modal(host, box, lambda: None)
    qtbot.wait(20)
    return box


def fits(box, host, w, h) -> None:
    where = rect_in(box, host)
    assert host.rect().contains(where), f"the box {where} is off the {w}x{h} screen"
    from PySide6.QtWidgets import QLabel

    for part in shown_parts(box):
        assert box.rect().contains(rect_in(part, box)), f"{type(part).__name__} cut off at {w}x{h}"
        if not isinstance(part, QLabel):
            assert part.height() >= part.minimumSizeHint().height() - 1, f"{part.text()!r} squeezed at {w}x{h}"


@pytest.mark.parametrize("w,h", SCREENS)
@pytest.mark.parametrize("encrypt", [True, False])
def test_the_step_fits_and_the_keyboard_is_the_apps(qtbot, w, h, encrypt):
    from gamingcrypt.ui.keyboard_overlay import KeyboardOverlay

    host = screen(qtbot, w, h)
    box = dialog(qtbot, host, encrypt)
    box.choose("exfat")
    qtbot.wait(20)
    assert box.name_field.text() == "OLD_NAME"  # (its name as a file system takes it)
    assert bool(box.share_buttons) == encrypt
    fits(box, host, w, h)
    box.keyboard_button.click()  # ⌨: the app's own on-screen keyboard (as for every text field)
    qtbot.wait(20)
    overlay = host.keyboard_overlay
    assert isinstance(overlay, KeyboardOverlay) and overlay.isVisible() and overlay.target() is box.name_field
    assert host.rect().contains(rect_in(overlay, host)), f"the keyboard is off the {w}x{h} screen"
    field = rect_in(box.name_field, host)
    assert not rect_in(overlay, host).intersects(field)  # (out of the field's way)
    overlay.close_keyboard()
    assert not overlay.isVisible()


def test_a_tap_on_the_name_opens_the_keyboard(qtbot):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest

    host = screen(qtbot, 1280, 800)
    box = dialog(qtbot, host, encrypt=False)
    box.choose("exfat")
    QTest.mouseClick(box.name_field, Qt.MouseButton.LeftButton)
    qtbot.wait(20)
    assert host.keyboard_overlay.isVisible() and host.keyboard_overlay.target() is box.name_field


def test_its_name_typed_on_the_keyboard(qtbot):
    from PySide6.QtWidgets import QPushButton

    host = screen(qtbot, 1280, 800)
    box = dialog(qtbot, host, encrypt=False)
    box.choose("exfat")
    box.name_field.clear()
    box.keyboard_button.click()
    keys = {b.text(): b for b in host.keyboard_overlay.keys.findChildren(QPushButton)}
    for letter in "ssd":
        keys[letter].click()
    assert box.name_field.text().lower() == "ssd"
    host.keyboard_overlay.enter()  # ↵: the keyboard closes
    assert not host.keyboard_overlay.isVisible()
    box.next_button.click()
    assert box.name == box.name_field.text() and f"called {box.name}" in box.question.text()


def test_a_name_with_spaces_and_signs_is_made_one_that_fits(qtbot):
    host = screen(qtbot, 1280, 800)
    box = dialog(qtbot, host, encrypt=False)
    box.choose("ext4")
    box.name_field.setText("My Games!")
    box.next_button.click()
    assert box.name == "My_Games"
    assert not box.format_button.isHidden()


def test_name_and_share_go_to_formatting(qtbot, monkeypatch):
    seen = []

    def fake_format(drive, fstype, label, run=None, step=None, encrypt=None):
        seen.append((fstype, label))
        if encrypt is not None:
            encrypt(drive)
        return drive

    monkeypatch.setattr(removable, "format_drive", fake_format)
    made = []
    host = screen(qtbot, 1280, 800)
    from gamingcrypt.ui.format_drive import FormatConfirm

    box = FormatConfirm(STICK, formats=["exfat"], method="pin", check_code=lambda s: "pw" if s == "1234" else None,
                        encrypt=lambda stick, password, progress=None, share=1.0: made.append((password, share)) or stick)
    show_modal(host, box, lambda: None)
    box.choose("exfat")
    assert [b.text() for b in box.share_buttons.values()] == ["All of it", "¾", "½", "¼"]
    box.share_buttons[0.5].click()
    assert box.share == 0.5 and box.share_buttons[0.5].isChecked() and not box.share_buttons[1.0].isChecked()
    box.name_field.setText("SSD")
    box.next_button.click()
    box.code.try_code("1234")  # (encrypting: the code next)
    qtbot.waitUntil(lambda: box.code is None)
    assert "encrypted (½ of it) and called SSD" in box.question.text()
    box.format_button.click()
    qtbot.waitUntil(lambda: box.over)
    assert seen == [("exfat", "SSD")] and made == [("pw", 0.5)]


def test_only_a_share_is_encrypted(tmp_path, monkeypatch):
    from gamingcrypt.system import stick_crypt

    sizes = []

    class Fake:
        def create_volume(self, path, size_gb, *_a, **_k):
            sizes.append(size_gb)
            Path(path).write_bytes(bytes(70))
            from gamingcrypt.unlock.veracrypt import UnlockResult

            return UnlockResult(True, "")

    monkeypatch.setattr(stick_crypt, "unlocker", lambda *a, **k: Fake())
    monkeypatch.setattr(stick_crypt, "open_stick", lambda stick, *a, **k: stick)
    stick = Removable(tmp_path, "usb", "S")
    for share in (1.0, 0.5, 0.25):
        (tmp_path / stick_crypt.CONTAINER).unlink(missing_ok=True)
        stick_crypt.create(stick, "pw", {"method": "pin", "kdf": None}, free=100 * 1024 ** 3, share=share)
    assert sizes == [99, 50, 25]  # (all of it: a little left for its own files)
