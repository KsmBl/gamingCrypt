"""Settings -> Health: what GamingCrypt needs, green or red, with the fix."""

from __future__ import annotations

from PySide6.QtWidgets import QGridLayout, QLabel, QVBoxLayout, QWidget

from gamingcrypt.system.health import Health
from gamingcrypt.ui.tasks import run_async
from gamingcrypt.ui.widgets import big_button, set_status


class HealthPage(QWidget):
    def __init__(self, health: Health | None = None, parent: QWidget | None = None):
        super().__init__(parent)
        self.health = health or Health()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        intro = QLabel("Everything GamingCrypt relies on. Red lines say what to do - usually run "
                       "./install.sh again.")
        intro.setObjectName("cardMeta")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.rows = QWidget()
        self.grid = QGridLayout(self.rows)
        self.grid.setColumnStretch(2, 1)
        layout.addWidget(self.rows)
        self.status = QLabel("")
        self.status.setObjectName("status")
        layout.addWidget(self.status)
        self.recheck_button = big_button("↻  Check again")
        self.recheck_button.clicked.connect(self.refresh)
        layout.addWidget(self.recheck_button)
        self.checks = []
        self.busy = False

    def refresh(self) -> None:
        if self.busy:
            return
        self.busy = True
        self.recheck_button.setEnabled(False)
        set_status(self.status, "Checking…")
        run_async(self.health.run, self.show_checks,
                  lambda exc: self.show_checks([]) or set_status(self.status, str(exc), error=True), owner=self)

    def show_checks(self, checks) -> None:
        self.busy = False
        self.recheck_button.setEnabled(True)
        self.checks = checks
        while self.grid.count():
            item = self.grid.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for row, check in enumerate(checks):
            mark = QLabel("✓" if check.ok else ("–" if check.optional else "✗"))
            mark.setObjectName("healthOk" if check.ok else ("healthOptional" if check.optional else "healthBad"))
            name = QLabel(check.name)
            detail = QLabel(check.detail + (f"\n→ {check.fix}" if check.fix and not check.ok else ""))
            detail.setObjectName("cardMeta")
            detail.setWordWrap(True)
            self.grid.addWidget(mark, row, 0)
            self.grid.addWidget(name, row, 1)
            self.grid.addWidget(detail, row, 2)
        problems = [c for c in checks if not c.ok and not c.optional]
        set_status(self.status, "All good" if not problems else f"{len(problems)} problem(s) found",
                   error=bool(problems))
