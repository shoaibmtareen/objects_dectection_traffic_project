from datetime import datetime
from pathlib import Path

import pandas as pd
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget

from storage.database import Database
from ui.widgets.common import Card, icon, top_bar
from ui.widgets.detail_panel import DetailPanel
from ui.widgets.search_panel import SCOPE_ALL, SCOPE_CURRENT, SearchPanel
from ui.widgets.vehicle_table import VehicleTable


class RecordsPage(QWidget):
    """Search every detected object by ID or type, inspect it, export the results."""

    back_requested = Signal()
    status_message = Signal(str, int)

    def __init__(self, settings: dict, db: Database, live, parent=None):
        """`live` is the AnalyticsPage: it provides the running session and in-frame IDs."""
        super().__init__(parent)
        self.setObjectName("Page")
        self.settings = settings
        self.db = db
        self.live = live
        self.colors = settings["colors"]
        self.selected: tuple[int, int] | None = None
        self._build_ui()

        self.search.changed.connect(self.refresh)
        self.search.export_requested.connect(self.export_results)
        self.table.vehicle_selected.connect(self.on_selected)
        self.back_btn.clicked.connect(self.back_requested)

        self.timer = QTimer(self, interval=1000)
        self.timer.timeout.connect(self._tick)
        self.timer.start()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        bar, bl = top_bar()
        self.back_btn = QPushButton("  Back")
        self.back_btn.setIcon(icon("back", "#FFFFFF"))
        bl.addWidget(self.back_btn)
        bl.addSpacing(10)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        t = QLabel("Records & search")
        t.setObjectName("BrandTitle")
        self.subtitle = QLabel("Every object detected, saved with its snapshot")
        self.subtitle.setObjectName("TopMeta")
        titles.addStretch()
        titles.addWidget(t)
        titles.addWidget(self.subtitle)
        titles.addStretch()
        bl.addLayout(titles)
        bl.addStretch()
        root.addWidget(bar)

        body = QHBoxLayout()
        body.setContentsMargins(16, 16, 16, 12)
        body.setSpacing(14)
        root.addLayout(body, 1)

        table_card = Card("Detected objects")
        self.search = SearchPanel(list(self.colors.keys()))
        table_card.body.addWidget(self.search)
        self.table = VehicleTable(self.colors)
        table_card.body.addWidget(self.table, 1)
        body.addWidget(table_card, 1)

        detail_card = Card("Object details")
        self.detail = DetailPanel(self.colors)
        detail_card.body.addWidget(self.detail, 1)
        detail_card.setFixedWidth(400)
        body.addWidget(detail_card)

    # ------------------------------------------------------------ navigation
    def open(self, request, back_label: str) -> None:
        """request: None, ("select", (session_id, track_id)) or ("type", class_name)."""
        self.back_btn.setText(f"  {back_label}")
        self.search.set_sessions(self.db.list_sessions())
        has_live = self.live.session_id is not None
        self.search.scope_combo.setCurrentIndex(0 if has_live else 1)  # current / all sessions
        self.search.live_only.setEnabled(self.live.running)
        if not self.live.running:
            self.search.live_only.setChecked(False)
        kind, value = request if request else (None, None)
        self.search.search.clear()
        idx = self.search.type_combo.findData(value if kind == "type" else None)
        self.search.type_combo.setCurrentIndex(max(0, idx))
        self.refresh()
        if kind == "select" and value[1] is not None:
            sid, tid = value
            if not self.table.select_vehicle(sid, tid):
                self.on_selected(sid, tid)
        else:
            self.table.clearSelection()
            self.selected = None
            self.detail.show_empty()
        self.search.focus_search()

    def _tick(self) -> None:
        if self.isVisible() and self.live.running:
            self.refresh()
            if self.selected and self.selected[0] == self.live.session_id:
                self.on_selected(*self.selected, highlight=False)

    # ------------------------------------------------------------ data
    def _scope_session(self) -> int | None:
        scope = self.search.filters()["scope"]
        if scope == SCOPE_ALL:
            return None
        if scope == SCOPE_CURRENT:
            if self.live.session_id is not None:
                return self.live.session_id
            sessions = self.db.list_sessions()
            return sessions[0]["id"] if sessions else -1
        return int(scope)

    def _rows(self) -> list[dict]:
        f = self.search.filters()
        rows = self.db.search_vehicles(text=f["text"], vehicle_type=f["vehicle_type"],
                                       direction=f["direction"], counted_only=f["counted_only"],
                                       session_id=self._scope_session())
        if f["live_only"]:
            rows = [r for r in rows if (r["session_id"], r["track_id"]) in self.live.live_keys]
        return rows

    def refresh(self) -> None:
        rows = self._rows()
        self.table.set_rows(rows)
        self.table.set_live(self.live.live_keys)
        self.search.set_result_count(len(rows))

    def on_selected(self, session_id: int, track_id: int, highlight: bool = True) -> None:
        self.selected = (session_id, track_id)
        rec = self.db.get_vehicle(session_id, track_id)
        if rec is None:
            self.detail.show_empty()
            return
        self.detail.show_vehicle(rec, (session_id, track_id) in self.live.live_keys)
        if highlight and session_id == self.live.session_id:
            self.live.highlight(track_id)

    # ------------------------------------------------------------ export
    def export_results(self) -> None:
        rows = self._rows()
        if not rows:
            QMessageBox.information(self, "Export", "There are no records to export for the current filters.")
            return
        out_dir = Path(self.settings["storage"]["exports_dir"])
        out_dir.mkdir(parents=True, exist_ok=True)
        default = out_dir / f"records_{datetime.now():%Y%m%d_%H%M%S}.csv"
        path, selected = QFileDialog.getSaveFileName(self, "Export records", str(default),
                                                     "CSV (*.csv);;Excel (*.xlsx)")
        if not path:
            return
        df = pd.DataFrame(rows)[["session_id", "track_id", "vehicle_type", "confidence", "counted",
                                 "direction", "crossed_at", "first_seen", "last_seen", "frames_seen",
                                 "source", "snapshot_path", "created_at"]]
        df["counted"] = df["counted"].map({1: "Yes", 0: "No"})
        df = df.rename(columns={"session_id": "Session", "track_id": "ID", "vehicle_type": "Type",
                                "confidence": "Best confidence", "counted": "Crossed line",
                                "direction": "Direction", "crossed_at": "Crossed at (s)",
                                "first_seen": "First seen (s)", "last_seen": "Last seen (s)",
                                "frames_seen": "Frames tracked", "source": "Source",
                                "snapshot_path": "Snapshot", "created_at": "Recorded at"})
        try:
            if path.lower().endswith(".xlsx") or "xlsx" in selected:
                if not path.lower().endswith(".xlsx"):
                    path += ".xlsx"
                df.to_excel(path, index=False, sheet_name="Records")
            else:
                df.to_csv(path, index=False)
        except OSError as exc:
            QMessageBox.critical(self, "Export failed", str(exc))
            return
        self.status_message.emit(f"Exported {len(df):,} records to {path}", 6000)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.back_requested.emit()
        else:
            super().keyPressEvent(event)
