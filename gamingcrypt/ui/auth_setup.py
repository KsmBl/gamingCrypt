"""First-start setup and "reset authentication": choose an unlock method and
re-key the VeraCrypt volume so that the new PIN / password / pattern opens it -
or create a brand new encrypted container protected by it."""

from __future__ import annotations

import os
import shutil
import threading
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QStackedWidget, QVBoxLayout, QWidget

from gamingcrypt.ui.secret_input import METHOD_LABELS, SecretInput
from gamingcrypt.ui.tasks import run_async
from gamingcrypt.ui.widgets import KeyboardFocusFilter, OnScreenKeyboard, big_button, set_status
from gamingcrypt.unlock import kdf, sidecar
from gamingcrypt.unlock.veracrypt import UnlockResult, VeraCryptUnlocker

UnlockerFactory = Callable[[dict], VeraCryptUnlocker]

MAX_CONTAINER_GB = 100_000
GB = 1024**3


default_container_path = sidecar.default_container_path


def default_mount_point() -> str:
    return str(Path.home() / "GamingCrypt")


def validate_new_container(path: str, size_text: str,
                           free_bytes: Callable[[str], int] = lambda d: shutil.disk_usage(d).free):
    """Return ``(error, absolute_path, size_gb)``; error is None when everything is fine."""
    path = os.path.abspath(os.path.expanduser(path.strip())) if path.strip() else ""
    if not path:
        return "Please enter where the container file should go", "", 0
    if os.path.lexists(path):
        return "That file already exists - choose a new name", path, 0
    parent = os.path.dirname(path)
    if not os.path.isdir(parent):
        return f"The folder {parent} does not exist", path, 0
    try:
        size_gb = int(size_text.strip())
    except ValueError:
        return "Size must be a whole number of GB", path, 0
    if not 1 <= size_gb <= MAX_CONTAINER_GB:
        return "Size must be at least 1 GB", path, 0
    try:
        free = free_bytes(parent)
    except OSError:
        free = None
    if free is not None and size_gb * GB > free:
        return f"Not enough free space: {free // GB} GB available", path, 0
    return None, path, size_gb


class _ProgressBridge(QObject):
    """Carries progress values from the worker thread to the UI thread."""

    progress = Signal(float)


def _label(text: str, name: str = "subtitle") -> QLabel:
    label = QLabel(text)
    label.setObjectName(name)
    label.setAlignment(Qt.AlignmentFlag.AlignCenter)
    label.setWordWrap(True)
    return label


class AuthSetupWizard(QWidget):
    """Steps:
        existing volume: [source -> volume] -> current secret -> method -> new -> confirm -> apply
        new container:   source -> create -> method -> new -> confirm -> create -> done

    ``first_start`` adds the source/volume steps and asks for the container's
    current (plain) password; otherwise the current secret is entered with the
    configured method.
    """

    completed = Signal()
    cancelled = Signal()

    def __init__(
        self,
        config: dict,
        save: Callable[[dict], None],
        unlocker_factory: UnlockerFactory = VeraCryptUnlocker.from_config,
        first_start: bool = False,
        new_kdf_params=kdf.new_params,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.config = config
        self.save = save
        self.unlocker_factory = unlocker_factory
        self.first_start = first_start
        self.new_kdf_params = new_kdf_params
        self.new_kdf: dict | None = None
        self.busy = False
        self.current_secret = ""
        self.new_method = ""
        self.new_secret = ""
        unlock = config["unlock"]
        self.volume = unlock.get("volume", "")
        self.mount_point = unlock.get("mount_point", "")
        self.creating = False
        self.size_gb = 0
        self.quick = True
        self._bridge = _ProgressBridge(self)
        self._bridge.progress.connect(self._show_progress)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 30, 40, 30)
        self.title = _label("Welcome to GamingCrypt" if first_start else "Reset authentication", "title")
        layout.addWidget(self.title)
        self.hint = _label("")
        layout.addWidget(self.hint)

        self.stack = QStackedWidget()
        layout.addWidget(self.stack, 1)
        self._keyboard = OnScreenKeyboard(compact=True)
        self._focus_filter = KeyboardFocusFilter(self._keyboard, self)
        self.source_page = self._build_source_page()
        self.volume_page = self._build_volume_page()
        self.create_page = self._build_create_page()
        self.method_page = self._build_method_page()
        self.done_page = self._build_done_page()
        self.creating_page = self._build_creating_page()
        for page in (self.source_page, self.volume_page, self.create_page, self.method_page,
                     self.creating_page, self.done_page):
            self.stack.addWidget(page)
        self.input_page: SecretInput | None = None

        self.status = _label("", "status")
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        self._cancel_text = "Skip setup" if first_start else "Cancel"
        self._cancel_event: threading.Event | None = None
        self.cancel_button = big_button(self._cancel_text)
        self.cancel_button.clicked.connect(self._cancel_clicked)
        buttons.addWidget(self.cancel_button)
        buttons.addStretch()
        self.back_button = big_button("‹ Back")
        self.back_button.clicked.connect(self.show_volume_step)
        buttons.addWidget(self.back_button)
        self.next_button = big_button("Next", "primary")
        self.next_button.clicked.connect(self._keyboard_enter)
        buttons.addWidget(self.next_button)
        layout.addLayout(buttons)
        self._set_nav(False)

        # The keyboard is shared by the text pages and moved into the visible one.
        self._keyboard.submitted.connect(self._keyboard_enter)

        if first_start and sidecar.existing_container(config["unlock"]):
            # A container is already there: go straight to authenticating it.
            self.show_current_step()
        elif first_start:
            self.show_volume_step()
        else:
            self.show_current_step()

    # pages ------------------------------------------------------------------
    def _build_source_page(self) -> QWidget:
        page = QWidget()
        h = QHBoxLayout(page)
        h.addStretch()
        self.existing_button = big_button("📂\nUse existing\nVeraCrypt volume")
        self.existing_button.setStyleSheet("min-height: 180px; min-width: 300px;")
        self.existing_button.clicked.connect(self.choose_existing)
        h.addWidget(self.existing_button)
        self.create_button = big_button("✨\nCreate new\nencrypted container", "primary")
        self.create_button.setStyleSheet("min-height: 180px; min-width: 300px;")
        self.create_button.clicked.connect(self.choose_create)
        h.addWidget(self.create_button)
        # Never offer to create a second container when one is already there.
        existing = sidecar.existing_container(self.config["unlock"])
        if existing:
            self.create_button.hide()
            if not self.volume:
                self.volume = existing
        h.addStretch()
        return page

    def _edit(self, text: str, placeholder: str) -> QLineEdit:
        edit = QLineEdit(text)
        edit.setPlaceholderText(placeholder)
        self._focus_filter.watch(edit)
        return edit

    def _set_nav(self, visible: bool) -> None:
        """Back/Next only exist on the form pages (volume path / new container)."""
        self.back_button.setVisible(visible)
        self.next_button.setVisible(visible)

    def _build_volume_page(self) -> QWidget:
        page = QWidget()
        self.volume_page_layout = v = QVBoxLayout(page)
        self.volume_edit = self._edit(self.volume, "VeraCrypt volume, e.g. /dev/sda3 or /home/me/games.vc")
        self.mount_edit = self._edit(self.mount_point, "Mount point (optional), e.g. /mnt/games")
        v.addWidget(self.volume_edit)
        v.addWidget(self.mount_edit)
        v.addStretch()
        return page

    def _build_create_page(self) -> QWidget:
        page = QWidget()
        self.create_page_layout = v = QVBoxLayout(page)
        self.path_edit = self._edit(default_container_path(), "Container file, e.g. ~/GamingCrypt.vc")
        v.addWidget(self.path_edit)
        row = QHBoxLayout()
        self.size_edit = self._edit("64", "Size")
        self.size_edit.setFixedWidth(160)
        row.addWidget(self.size_edit)
        row.addWidget(QLabel("GB"))
        self.create_mount_edit = self._edit(default_mount_point(), "Mount point, e.g. ~/GamingCrypt")
        row.addWidget(self.create_mount_edit, 1)
        v.addLayout(row)
        row2 = QHBoxLayout()
        self.quick_button = big_button("⚡ Quick format", checkable=True)
        self.quick_button.setChecked(True)
        row2.addWidget(self.quick_button)
        self.free_label = QLabel("")
        self.free_label.setObjectName("cardMeta")
        row2.addWidget(self.free_label, 1)
        v.addLayout(row2)
        self.path_edit.textChanged.connect(self._update_free_space)
        self._update_free_space()
        v.addStretch()
        return page

    def _build_creating_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.addStretch()
        self.progress_label = _label("0%", "title")
        v.addWidget(self.progress_label)
        v.addWidget(_label("Please wait - you can cancel, which deletes the unfinished container."))
        v.addStretch()
        return page

    def _build_done_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.addStretch()
        self.done_label = _label("")
        v.addWidget(self.done_label)
        continue_button = big_button("Continue", "primary")
        continue_button.clicked.connect(self.completed.emit)
        v.addWidget(continue_button, alignment=Qt.AlignmentFlag.AlignCenter)
        v.addStretch()
        return page

    def _attach_keyboard(self, layout: QVBoxLayout, target: QLineEdit) -> None:
        self._keyboard.set_target(target)
        layout.insertWidget(layout.count() - 1, self._keyboard)
        self._keyboard.show()

    def _keyboard_enter(self) -> None:
        if self.step == "create":
            self._create_next()
        elif self.step == "volume":
            self._volume_next()

    def _update_free_space(self) -> None:
        parent = os.path.dirname(os.path.abspath(os.path.expanduser(self.path_edit.text().strip() or "~")))
        try:
            self.free_label.setText(f"{shutil.disk_usage(parent).free // GB} GB free in {parent}")
        except OSError:
            self.free_label.setText("")

    def _build_method_page(self) -> QWidget:
        page = QWidget()
        h = QHBoxLayout(page)
        h.addStretch()
        self.method_buttons = {}
        for method, label in METHOD_LABELS.items():
            button = big_button(label)
            button.setStyleSheet("min-height: 140px; min-width: 200px;")
            button.clicked.connect(lambda _=False, m=method: self.choose_method(m))
            self.method_buttons[method] = button
            h.addWidget(button)
        h.addStretch()
        return page

    def _show_input(self, method: str, hint: str, handler) -> None:
        if self.input_page is not None:
            self.stack.removeWidget(self.input_page)
            self.input_page.deleteLater()
        self.input_page = SecretInput(method)
        self.input_page.secret_entered.connect(handler)
        self.input_page.invalid.connect(lambda msg: set_status(self.status, msg, error=True))
        self.stack.addWidget(self.input_page)
        self.stack.setCurrentWidget(self.input_page)
        self.hint.setText(hint)

    # steps ------------------------------------------------------------------
    def show_volume_step(self) -> None:
        self._set_nav(False)
        self.step = "source"
        self.creating = False
        self.hint.setText("Where should your games live?" if self.create_button.isVisibleTo(self)
                          else f"Found an existing container: {self.volume}")
        self.stack.setCurrentWidget(self.source_page)

    def choose_existing(self) -> None:
        self._set_nav(True)
        self.step = "volume"
        self.creating = False
        self.hint.setText("Which VeraCrypt volume holds your games?")
        self.stack.setCurrentWidget(self.volume_page)
        self._attach_keyboard(self.volume_page_layout, self.volume_edit)

    def choose_create(self) -> None:
        self._set_nav(True)
        self.step = "create"
        self.hint.setText("New encrypted container (ext4) - Steam games can be installed into it")
        self.stack.setCurrentWidget(self.create_page)
        self._attach_keyboard(self.create_page_layout, self.path_edit)

    def _create_next(self) -> None:
        self.submit_create(self.path_edit.text(), self.size_edit.text(),
                           self.create_mount_edit.text(), self.quick_button.isChecked())

    def submit_create(self, path: str, size_text: str, mount_point: str, quick: bool = True,
                      free_bytes=None) -> None:
        args = (path, size_text) if free_bytes is None else (path, size_text, free_bytes)
        error, path, size_gb = validate_new_container(*args)
        if error:
            set_status(self.status, error, error=True)
            return
        self.creating = True
        self.volume = path
        self.size_gb = size_gb
        self.quick = quick
        self.mount_point = os.path.abspath(os.path.expanduser(mount_point.strip())) if mount_point.strip() else ""
        set_status(self.status, "")
        self.show_method_step()

    def _volume_next(self) -> None:
        self.submit_volume(self.volume_edit.text(), self.mount_edit.text())

    def submit_volume(self, volume: str, mount_point: str) -> None:
        volume = volume.strip()
        if not volume:
            set_status(self.status, "Please enter the path of the volume", error=True)
            return
        self.volume = volume
        self.mount_point = mount_point.strip()
        set_status(self.status, "")
        self.show_current_step()

    def show_current_step(self) -> None:
        self._set_nav(False)
        self.step = "current"
        if self.first_start or not self.config["unlock"].get("method"):
            method, hint = "password", f"Enter the current password of {self.volume or 'the volume'}"
        else:
            method = self.config["unlock"]["method"]
            hint = f"Enter your current {METHOD_LABELS.get(method, 'password')}"
        self._show_input(method, hint, self.submit_current)

    def submit_current(self, secret: str) -> None:
        self.current_secret = secret
        set_status(self.status, "")
        self.show_method_step()

    def show_method_step(self) -> None:
        self._set_nav(False)
        self.step = "method"
        self.hint.setText("How do you want to unlock from now on?")
        self.stack.setCurrentWidget(self.method_page)

    def choose_method(self, method: str) -> None:
        self._set_nav(False)
        self.new_method = method
        self.step = "new"
        self._show_input(method, f"Choose your new {METHOD_LABELS[method]}", self.submit_new)

    def submit_new(self, secret: str) -> None:
        self.new_secret = secret
        self.step = "confirm"
        set_status(self.status, "")
        self._show_input(self.new_method, f"Repeat your new {METHOD_LABELS[self.new_method]}", self.submit_confirm)

    def submit_confirm(self, secret: str) -> None:
        if secret != self.new_secret:
            set_status(self.status, "That didn't match - try again", error=True)
            self.choose_method(self.new_method)
            return
        self.apply()

    def apply(self) -> None:
        if self.busy:
            return
        self.busy = True
        self.step = "apply"
        self.cancel_button.setEnabled(False)
        if self.creating:
            self._apply_create()
            return
        set_status(self.status, "Updating the volume… this can take a few seconds")
        # A volume set up by hand has the plain password; otherwise use the stored KDF.
        current_kdf = None if self.first_start else self.config["unlock"].get("kdf")
        unlock_cfg = dict(self.config["unlock"], volume=self.volume, mount_point=self.mount_point, kdf=current_kdf)
        unlocker = self.unlocker_factory(unlock_cfg)
        current, new = self.current_secret, self.new_secret
        self.new_kdf = new_kdf = self.new_kdf_params()
        run_async(
            lambda: unlocker.change_password(current, new, new_kdf),
            self._applied,
            lambda exc: self._applied(UnlockResult(False, str(exc))),
        )

    def _cancel_clicked(self) -> None:
        if self.busy and self.creating:
            if self._cancel_event is not None:
                self._cancel_event.set()
            self.cancel_button.setEnabled(False)
            set_status(self.status, "Cancelling…")
            return
        if not self.busy:
            self.cancelled.emit()

    def abort(self) -> None:
        """Window is closing: stop a running creation (deletes the unfinished file)."""
        if self.busy and self.creating and self._cancel_event is not None:
            self._cancel_event.set()

    def _apply_create(self) -> None:
        self._set_nav(False)
        self.new_kdf = new_kdf = self.new_kdf_params()
        unlock_cfg = dict(self.config["unlock"], volume=self.volume, mount_point=self.mount_point, kdf=new_kdf)
        unlocker = self.unlocker_factory(unlock_cfg)
        path, size, secret, quick = self.volume, self.size_gb, self.new_secret, self.quick
        self._cancel_event = cancel = threading.Event()
        # While creating there is nothing to continue to - only "Cancel creation".
        self.step = "creating"
        self.stack.setCurrentWidget(self.creating_page)
        self.progress_label.setText("0%")
        self.hint.setText("Creating your encrypted container…")
        self.cancel_button.setText("Cancel creation")
        self.cancel_button.setEnabled(True)
        set_status(self.status, "")
        run_async(
            lambda: unlocker.create_volume(path, size, secret, quick, progress=self._bridge.progress.emit,
                                           cancel=cancel),
            self._applied,
            lambda exc: self._applied(UnlockResult(False, str(exc))),
            owner=self,
        )

    def _show_progress(self, percent: float) -> None:
        if self.busy:
            self.progress_label.setText(f"{percent:.0f}%")

    def _applied(self, result: UnlockResult) -> None:
        self.busy = False
        self._cancel_event = None
        self.cancel_button.setText(self._cancel_text)
        self.cancel_button.setEnabled(True)
        if result.cancelled:
            self.choose_create()
            set_status(self.status, "Creation cancelled - the unfinished container was deleted")
            return
        if not result.success:
            set_status(self.status, result.message, error=True)
            if self.creating:
                self.choose_create()
            else:
                self.show_current_step()
            return
        unlock = self.config["unlock"]
        unlock["method"] = self.new_method
        unlock["kdf"] = self.new_kdf
        unlock["volume"] = self.volume
        unlock["mount_point"] = self.mount_point
        self.save(self.config)
        sidecar.write_sidecar(self.volume, unlock)
        set_status(self.status, "Done")
        if self.creating:
            self.step = "done"
            self.hint.setText("Your encrypted container is ready ✓")
            where = self.mount_point or "the mount point"
            self.done_label.setText(
                f"After unlocking, the container is mounted at {where}.\n"
                "In Steam open Settings → Storage → Add drive and choose that folder,\n"
                "then install games onto it."
            )
            self.stack.setCurrentWidget(self.done_page)
            self.cancel_button.hide()  # finished: the only way on is Continue
            return
        self.completed.emit()
