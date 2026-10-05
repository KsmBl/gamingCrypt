"""Add emulator games (ROMs), cores and BIOS over Wi-Fi: browser address and SMB share.

Both services run only while this page is visible - they stop when it's left.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from gamingcrypt.emulation.library import EmulationPaths
from gamingcrypt.emulation.sharing import SHARE, SmbShare
from gamingcrypt.emulation.upload_server import UploadServer, local_ip
from gamingcrypt.ui.tasks import run_async
from gamingcrypt.ui.widgets import big_button, set_status

MAX_RECEIVED = 6


class _Bridge(QObject):
    received = Signal(str, str)


def _card(title: str) -> tuple[QFrame, QVBoxLayout]:
    card = QFrame()
    card.setObjectName("card")
    box = QVBoxLayout(card)
    box.setContentsMargins(24, 16, 24, 16)
    heading = QLabel(title)
    heading.setObjectName("section")
    box.addWidget(heading)
    return card, box


def smb_url(ip: str, user: str, password: str) -> str:
    """For a phone's file manager: share, user and (temporary) password in one."""
    from urllib.parse import quote

    return f"smb://{quote(user, safe='')}:{quote(password, safe='')}@{ip}/{SHARE}"


class UploadPage(QWidget):
    closed = Signal()

    def __init__(self, paths: EmulationPaths, server_factory: Callable = UploadServer,
                 share: SmbShare | None = None, ip: Callable[[], str] = local_ip, parent: QWidget | None = None):
        super().__init__(parent)
        self.paths = paths
        self.server_factory = server_factory
        self.share = share or SmbShare()
        self.ip = ip
        self.server = None
        self.received: list[str] = []
        self.bridge = _Bridge(self)
        self.bridge.received.connect(self._received)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 16, 30, 16)
        top = QHBoxLayout()
        title = QLabel("Add emulator games")
        title.setObjectName("title")
        top.addWidget(title, 1)
        self.done_button = big_button("Done", "primary")
        self.done_button.clicked.connect(self.closed.emit)
        top.addWidget(self.done_button)
        layout.addLayout(top)
        hint = QLabel("For the emulators (RetroArch) only: ROMs, cores and BIOS files from a PC or phone in the "
                      "same Wi-Fi. Steam games are installed from the Steam library as usual. Everything lands "
                      "on your encrypted drive; both ways work only while this page is open.")
        hint.setObjectName("cardMeta")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        row = QHBoxLayout()
        browser, box = _card("Browser")
        self.url = QLabel("")
        self.url.setObjectName("sourceTitle")
        self.url.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.url.setWordWrap(True)
        box.addWidget(self.url)
        self.browser_status = QLabel("")
        self.browser_status.setObjectName("status")
        box.addWidget(self.browser_status)
        self.browser_qr = self._qr_label(box)
        box.addStretch()
        row.addWidget(browser, 1)
        smb, box = _card("Network share (SMB)")
        self.smb = QLabel("Starting…")
        self.smb.setObjectName("detailMeta")
        self.smb.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.smb.setWordWrap(True)
        box.addWidget(self.smb)
        self.smb_qr = self._qr_label(box)
        box.addStretch()
        row.addWidget(smb, 1)
        layout.addLayout(row)
        folders = QLabel("Where things go:  roms/<system> - games (e.g. roms/snes, roms/psx)  ·  bios - BIOS "
                         "files  ·  cores - RetroArch cores (*_libretro.so - missing ones are "
                         "downloaded automatically)")
        folders.setObjectName("cardMeta")
        folders.setWordWrap(True)
        layout.addWidget(folders)
        self.log = QLabel("")
        self.log.setObjectName("detailMeta")
        layout.addWidget(self.log)
        layout.addStretch()

    @staticmethod
    def _qr_label(box: QVBoxLayout) -> QLabel:
        label = QLabel()
        label.setToolTip("Scan with your phone's camera")
        label.hide()
        box.addWidget(label, alignment=Qt.AlignmentFlag.AlignLeft)
        return label

    @staticmethod
    def _show_qr(label: QLabel, text: str | None) -> None:
        from gamingcrypt.ui.qr import qr_pixmap

        pixmap = qr_pixmap(text) if text else None
        label.qr_text = text if pixmap is not None else None
        if pixmap is None:
            label.hide()
            return
        label.setPixmap(pixmap)
        label.show()

    # services live exactly as long as the page is shown --------------------------------------
    def showEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().showEvent(event)
        self.start()

    def hideEvent(self, event) -> None:  # noqa: N802 - Qt API
        self.stop()
        super().hideEvent(event)

    def start(self) -> None:
        if self.server is not None:
            return
        self.paths.ensure()
        ip = self.ip()
        self.server = self.server_factory(self.paths, lambda folder, path: self.bridge.received.emit(folder, path.name))
        if self.server.start():
            self.url.setText(self.server.url(ip))
            set_status(self.browser_status, "Open this address in a browser - or scan the code with your phone")
            self._show_qr(self.browser_qr, self.server.url(ip))
        else:
            self.url.setText("-")
            set_status(self.browser_status, "No free port for the upload page", error=True)
            self._show_qr(self.browser_qr, None)
        self.smb.setText("Starting…")
        self._show_qr(self.smb_qr, None)
        folder = str(self.paths.root)
        run_async(lambda: self.share.start(folder), lambda r: self._share_started(r, ip), owner=self)

    def _share_started(self, result, ip: str) -> None:
        ok, message = result
        if not self.isVisible() and self.share.running:
            self.share.stop()  # left the page meanwhile
            return
        if not ok:
            self.smb.setText(f"Not available: {message}")
            return
        self.smb.setText(f"Windows: \\\\{ip}\\{SHARE}\nMac / Linux: smb://{ip}/{SHARE}\n"
                         f"User: {self.share.user}\nPassword: {self.share.password}")
        self._show_qr(self.smb_qr, smb_url(ip, self.share.user, self.share.password))

    def stop(self) -> None:
        if self.server is not None:
            self.server.stop()
            self.server = None
        self.share.stop()

    def _received(self, folder: str, name: str) -> None:
        self.received.insert(0, f"✓ {folder}/{name}")
        self.log.setText("\n".join(self.received[:MAX_RECEIVED]))
