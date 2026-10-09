from pathlib import Path

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ui import theme
from ui.widgets.common import divider
from utils.helpers import format_seconds


class DetailPanel(QWidget):
    """Selected object: large snapshot, ID, type chip and all stored fields (vertical layout)."""

    FIELDS = [("status", "Status"), ("counted", "Counting line"), ("confidence", "Best confidence"),
              ("first_seen", "First seen"), ("last_seen", "Last seen"), ("duration", "Visible for"),
              ("frames", "Frames tracked"), ("session", "Session")]

    def __init__(self, colors: dict[str, str], parent=None):
        super().__init__(parent)
        self.colors = colors
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(12)

        self.snapshot = QLabel()
        self.snapshot.setMinimumHeight(210)
        self.snapshot.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.snapshot.setStyleSheet(
            f"background:{theme.SURFACE_2}; border:1px solid {theme.BORDER}; border-radius:8px;"
            f"color:{theme.SUBTLE}; font-size:12px;")
        lay.addWidget(self.snapshot)

        head = QHBoxLayout()
        self.id_label = QLabel()
        self.type_chip = QLabel()
        self.type_chip.setObjectName("TypeChip")
        head.addWidget(self.id_label)
        head.addWidget(self.type_chip, 0, Qt.AlignmentFlag.AlignVCenter)
        head.addStretch()
        lay.addLayout(head)
        lay.addWidget(divider())

        grid = QGridLayout()
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(9)
        self.values: dict[str, QLabel] = {}
        for i, (key, title) in enumerate(self.FIELDS):
            t = QLabel(title)
            t.setStyleSheet(f"color:{theme.MUTED}; font-size:12px;")
            v = QLabel("—")
            v.setStyleSheet(f"font-size:13px; font-weight:600; color:{theme.TEXT};")
            v.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(t, i, 0)
            grid.addWidget(v, i, 1, Qt.AlignmentFlag.AlignRight)
            self.values[key] = v
        grid.setColumnStretch(1, 1)
        lay.addLayout(grid)
        lay.addStretch()
        self._pix = QPixmap()
        self.show_empty()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit_snapshot()

    def _fit_snapshot(self) -> None:
        if not self._pix.isNull():
            self.snapshot.setPixmap(self._pix.scaled(self.snapshot.size() - QSize(8, 8),
                                                     Qt.AspectRatioMode.KeepAspectRatio,
                                                     Qt.TransformationMode.SmoothTransformation))

    def show_empty(self) -> None:
        self.id_label.setText("No object selected")
        self.id_label.setStyleSheet(f"font-size:15px; font-weight:600; color:{theme.SUBTLE};")
        self.type_chip.hide()
        self._pix = QPixmap()
        self.snapshot.setPixmap(QPixmap())
        self.snapshot.setText("Select a record in the table\nto see its snapshot and details")
        for v in self.values.values():
            v.setText("—")
            v.setStyleSheet(f"font-size:13px; font-weight:600; color:{theme.TEXT};")

    def show_vehicle(self, rec: dict, live: bool) -> None:
        self.id_label.setText(f"ID #{rec['track_id']}")
        self.id_label.setStyleSheet(f"font-size:22px; font-weight:800; color:{theme.TEXT};")
        color = self.colors.get(rec["vehicle_type"], theme.MUTED)
        self.type_chip.setText(rec["vehicle_type"].upper())
        self.type_chip.setStyleSheet(f"background:{color};")
        self.type_chip.show()

        path = rec.get("snapshot_path")
        self._pix = QPixmap(path) if path and Path(path).exists() else QPixmap()
        if self._pix.isNull():
            self.snapshot.setPixmap(QPixmap())
            self.snapshot.setText("No snapshot available")
        else:
            self._fit_snapshot()

        if rec["counted"]:
            arrow = "↓" if rec["direction"] == "IN" else "↑"
            counted = f"{arrow} {rec['direction']} at {format_seconds(rec['crossed_at'] or 0)}"
        else:
            counted = "Not crossed"
        status = self.values["status"]
        status.setText("● In frame" if live else "Left scene")
        status.setStyleSheet(f"font-size:13px; font-weight:700; color:{theme.SUCCESS if live else theme.MUTED};")
        self.values["counted"].setText(counted)
        self.values["confidence"].setText(f"{rec['confidence']:.1%}")
        self.values["first_seen"].setText(format_seconds(rec["first_seen"]))
        self.values["last_seen"].setText(format_seconds(rec["last_seen"]))
        self.values["duration"].setText(f"{max(0.0, rec['last_seen'] - rec['first_seen']):.1f} s")
        self.values["frames"].setText(f"{rec['frames_seen']:,}")
        source = rec.get("source", "").replace("\\", "/").split("/")[-1]
        self.values["session"].setText(f"S{rec['session_id']} · {source}")
        self.values["session"].setToolTip(rec.get("source", ""))
