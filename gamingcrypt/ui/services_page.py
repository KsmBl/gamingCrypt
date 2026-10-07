"""Settings -> Services: the SSH server and the whole drive as a network share (SMB).

The drive share runs while the drive is unlocked: this page is made after unlocking and
starts it when it's switched on; locking stops it before the drive is unmounted (app.py).
"""

from __future__ import annotations

import getpass
import os
from typing import Callable

from PySide6.QtCore import Qt, QThreadPool
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from gamingcrypt.emulation.sharing import DRIVE_SHARE, DriveShare, new_password
from gamingcrypt.emulation.upload_server import local_ip
from gamingcrypt.system.ssh import Ssh, SshState
from gamingcrypt.ui.tasks import run_async
from gamingcrypt.ui.widgets import big_button, set_status

PASSWORD_WORDS = 3  # on all the time, so longer than the upload pages' passwords


def drive_url(ip: str, user: str, password: str) -> str:
    from urllib.parse import quote

    return f"smb://{quote(user, safe='')}:{quote(password, safe='')}@{ip}/{DRIVE_SHARE}"


def _card(title: str) -> tuple[QFrame, QVBoxLayout, QHBoxLayout]:
    card = QFrame()
    card.setObjectName("card")
    box = QVBoxLayout(card)
    box.setContentsMargins(24, 18, 24, 18)
    top = QHBoxLayout()
    heading = QLabel(title)
    heading.setObjectName("section")
    top.addWidget(heading)
    top.addStretch()
    box.addLayout(top)
    return card, box, top


def _label(name: str) -> QLabel:
    label = QLabel("")
    label.setObjectName(name)
    label.setWordWrap(True)
    return label


def _set_toggle(button, on: bool) -> None:
    button.blockSignals(True)
    button.setChecked(on)
    button.setText("On" if on else "Off")
    button.blockSignals(False)


class ServicesPage(QWidget):
    def __init__(self, config: dict, save: Callable[[dict], None], ssh: Ssh | None = None,
                 share: DriveShare | None = None, ip: Callable[[], str] = local_ip,
                 mounted: Callable[[str], bool] = os.path.ismount, parent: QWidget | None = None):
        super().__init__(parent)
        self.config, self.save = config, save
        self.settings = config.setdefault("services", {})
        self.ssh = ssh or Ssh()
        self.share = share or DriveShare()
        self.ip, self.mounted = ip, mounted
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(1)  # switching on and off quickly stays in order
        self.share_busy = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        card, box, top = _card("SSH")
        self.ssh_toggle = big_button("Off", checkable=True)
        self.ssh_toggle.toggled.connect(self.set_ssh)
        top.addWidget(self.ssh_toggle)
        hint = _label("cardMeta")
        hint.setText("Log in to this device from a PC with your Linux user and password. "
                     "Stays on after a restart.")
        box.addWidget(hint)
        self.ssh_info = _label("detailMeta")
        self.ssh_info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        box.addWidget(self.ssh_info)
        self.ssh_status = _label("status")
        box.addWidget(self.ssh_status)
        layout.addWidget(card)

        card, box, top = _card("Network share (SMB)")
        self.share_toggle = big_button("Off", checkable=True)
        self.share_toggle.toggled.connect(self.set_share)
        top.addWidget(self.share_toggle)
        hint = _label("cardMeta")
        hint.setText("Your whole encrypted drive in the network, for copying games, movies and shows from a PC "
                     "or phone. Available while the drive is unlocked; locking turns it off until the next unlock.")
        box.addWidget(hint)
        self.share_info = _label("detailMeta")
        self.share_info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        box.addWidget(self.share_info)
        self.share_qr = QLabel()
        self.share_qr.setToolTip("Scan with your phone's camera")
        self.share_qr.hide()
        box.addWidget(self.share_qr, alignment=Qt.AlignmentFlag.AlignLeft)
        self.new_password_button = big_button("New password")
        self.new_password_button.clicked.connect(self.change_password)
        self.new_password_button.hide()
        box.addWidget(self.new_password_button, alignment=Qt.AlignmentFlag.AlignLeft)
        self.share_status = _label("status")
        box.addWidget(self.share_status)
        layout.addWidget(card)

        _set_toggle(self.share_toggle, bool(self.settings.get("smb_drive")))
        self.show_share()
        if self.settings.get("smb_drive"):
            self.start_share()  # switched on before: share the drive that was just unlocked

    # SSH ----------------------------------------------------------------------------------
    def refresh(self) -> None:
        run_async(self.ssh.state, self.show_ssh, owner=self)

    def show_ssh(self, state: SshState) -> None:
        self.ssh_toggle.setVisible(state.installed)
        if not state.installed:
            self.ssh_info.setText("")
            set_status(self.ssh_status, "OpenSSH isn't installed (Arch: sudo pacman -S openssh)", error=True)
            return
        on = state.enabled or state.active
        _set_toggle(self.ssh_toggle, on)
        self.ssh_info.setText(f"ssh {getpass.getuser()}@{self.ip()}" if state.active else "")

    def set_ssh(self, on: bool) -> None:
        self.ssh_toggle.setEnabled(False)
        set_status(self.ssh_status, "Starting SSH…" if on else "Stopping SSH…")
        run_async(lambda: self.ssh.set(on), lambda r: self._ssh_set(on, r),
                  lambda exc: self._ssh_set(on, (False, str(exc))), owner=self)

    def _ssh_set(self, on: bool, result) -> None:
        ok, message = result
        self.ssh_toggle.setEnabled(True)
        set_status(self.ssh_status, "" if ok else message, error=not ok)
        if not ok:
            _set_toggle(self.ssh_toggle, not on)
        self.refresh()

    # drive share --------------------------------------------------------------------------
    def folder(self) -> str:
        return os.path.expanduser(self.config.get("unlock", {}).get("mount_point", "") or "")

    def password(self) -> str:
        if not self.settings.get("smb_password"):
            self.settings["smb_password"] = new_password(PASSWORD_WORDS)
            self.save(self.config)
        return self.settings["smb_password"]

    def set_share(self, on: bool) -> None:
        self.settings["smb_drive"] = on
        self.save(self.config)
        _set_toggle(self.share_toggle, on)
        if on:
            self.start_share()
        else:
            self.stop_share()

    def start_share(self) -> None:
        folder = self.folder()
        if not folder or not self.mounted(folder):
            set_status(self.share_status, "The drive isn't unlocked, or it has no mount point "
                                          "(set one in the first-start setup)", error=True)
            return
        password = self.password()
        self.share_busy = True
        self.share_toggle.setEnabled(False)
        set_status(self.share_status, "Starting the share…")
        run_async(lambda: self.share.start(folder, password), self._share_started,
                  lambda exc: self._share_started((False, str(exc))), owner=self, pool=self.pool)

    def _share_started(self, result) -> None:
        ok, message = result
        self.share_busy = False
        self.share_toggle.setEnabled(True)
        set_status(self.share_status, "" if ok else f"Not available: {message}", error=not ok)
        if not ok:
            self.settings["smb_drive"] = False
            self.save(self.config)
            _set_toggle(self.share_toggle, False)
        self.show_share()

    def stop_share(self) -> None:
        self.share_busy = True
        self.share_toggle.setEnabled(False)
        run_async(self.share.stop, lambda _r: self._share_stopped(), lambda _e: self._share_stopped(),
                  owner=self, pool=self.pool)

    def _share_stopped(self) -> None:
        self.share_busy = False
        self.share_toggle.setEnabled(True)
        set_status(self.share_status, "")
        self.show_share()

    def change_password(self) -> None:
        self.settings["smb_password"] = new_password(PASSWORD_WORDS)
        self.save(self.config)
        if self.share.running:
            self.start_share()  # the running share takes the new one
        self.show_share()

    def show_share(self) -> None:
        from gamingcrypt.ui.qr import qr_pixmap

        running = self.share.running
        self.new_password_button.setVisible(running)
        if not running:
            self.share_info.setText("")
            self.share_qr.qr_text = None
            self.share_qr.hide()
            return
        ip, user, password = self.ip(), self.share.user, self.share.password
        self.share_info.setText(f"Windows: \\\\{ip}\\{DRIVE_SHARE}\nMac / Linux: smb://{ip}/{DRIVE_SHARE}\n"
                                f"User: {user}\nPassword: {password}")
        text = drive_url(ip, user, password)
        pixmap = qr_pixmap(text)
        self.share_qr.qr_text = text if pixmap is not None else None
        if pixmap is None:
            self.share_qr.hide()
        else:
            self.share_qr.setPixmap(pixmap)
            self.share_qr.show()
