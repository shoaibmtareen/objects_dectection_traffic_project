from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QVBoxLayout, QWidget)

SCOPE_CURRENT = "current"
SCOPE_ALL = "all"


class SearchPanel(QWidget):
    """Search box + filters. Emits `changed` (debounced) whenever a filter changes."""

    changed = Signal()
    export_requested = Signal()

    def __init__(self, vehicle_types: list[str], parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)

        row1 = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search by ID (e.g. 42) or type (e.g. truck, person)…")
        self.search.setClearButtonEnabled(True)
        row1.addWidget(self.search, 1)
        self.export_btn = QPushButton("Export")
        self.export_btn.setToolTip("Export the current results to CSV or Excel")
        row1.addWidget(self.export_btn)
        lay.addLayout(row1)

        row2 = QHBoxLayout()
        self.type_combo = QComboBox()
        self.type_combo.addItem("All types", None)
        for t in vehicle_types:
            self.type_combo.addItem(t, t)
        self.dir_combo = QComboBox()
        self.dir_combo.addItem("Any direction", None)
        self.dir_combo.addItem("↓ IN", "IN")
        self.dir_combo.addItem("↑ OUT", "OUT")
        self.scope_combo = QComboBox()
        self.scope_combo.setMinimumWidth(170)
        self.scope_combo.addItem("Current session", SCOPE_CURRENT)
        self.scope_combo.addItem("All sessions", SCOPE_ALL)
        row2.addWidget(self.type_combo, 1)
        row2.addWidget(self.dir_combo, 1)
        row2.addWidget(self.scope_combo, 1)
        lay.addLayout(row2)

        row3 = QHBoxLayout()
        self.counted_only = QCheckBox("Crossed line only")
        self.live_only = QCheckBox("In frame now")
        row3.addWidget(self.counted_only)
        row3.addWidget(self.live_only)
        row3.addStretch()
        self.result_label = QLabel("0 records")
        self.result_label.setObjectName("SectionHint")
        row3.addWidget(self.result_label)
        lay.addLayout(row3)

        self._debounce = QTimer(self, singleShot=True, interval=250)
        self._debounce.timeout.connect(self.changed)
        self.search.textChanged.connect(self._debounce.start)
        for combo in (self.type_combo, self.dir_combo, self.scope_combo):
            combo.currentIndexChanged.connect(self.changed)
        for box in (self.counted_only, self.live_only):
            box.toggled.connect(self.changed)
        self.export_btn.clicked.connect(self.export_requested)

    # ---------- sessions in scope combo ----------
    def set_sessions(self, sessions: list[dict]) -> None:
        current = self.scope_combo.currentData()
        self.scope_combo.blockSignals(True)
        while self.scope_combo.count() > 2:
            self.scope_combo.removeItem(2)
        for s in sessions:
            name = s["source"].replace("\\", "/").split("/")[-1]
            date = s["started_at"].replace("T", " ")[:16]
            self.scope_combo.addItem(f"S{s['id']} · {name} · {date}", s["id"])
        idx = self.scope_combo.findData(current)
        self.scope_combo.setCurrentIndex(max(0, idx))
        self.scope_combo.blockSignals(False)

    def filters(self) -> dict:
        return {
            "text": self.search.text(),
            "vehicle_type": self.type_combo.currentData(),
            "direction": self.dir_combo.currentData(),
            "counted_only": self.counted_only.isChecked(),
            "scope": self.scope_combo.currentData(),
            "live_only": self.live_only.isChecked(),
        }

    def set_result_count(self, n: int) -> None:
        self.result_label.setText(f"{n:,} record{'s' if n != 1 else ''}")

    def focus_search(self) -> None:
        self.search.setFocus(Qt.FocusReason.ShortcutFocusReason)
        self.search.selectAll()
