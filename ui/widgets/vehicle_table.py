from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QAbstractItemView, QHeaderView, QTableView

from ui import theme
from utils.helpers import format_seconds

COLUMNS = ["", "ID", "Type", "Conf.", "Seen at", "Dir.", "Crossed"]
TOOLTIPS = ["In frame now", "Track ID", "Object type", "Best detection confidence",
            "First seen (video time)", "Direction across the counting line",
            "Crossed the counting line"]


def _dot_icon(color: str) -> QIcon:
    pix = QPixmap(10, 10)
    pix.fill(QColor(0, 0, 0, 0))
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QColor(0, 0, 0, 0))
    p.setBrush(QColor(color))
    p.drawEllipse(1, 1, 8, 8)
    p.end()
    return QIcon(pix)
SORT_ROLE = Qt.ItemDataRole.UserRole + 1


class VehicleTableModel(QAbstractTableModel):
    def __init__(self, colors: dict[str, str], parent=None):
        super().__init__(parent)
        self.icons = {k: _dot_icon(v) for k, v in colors.items()}
        self.rows: list[dict] = []
        self.live_keys: set[tuple[int, int]] = set()  # (session_id, track_id) currently in frame
        self.multi_session = False  # prefix IDs with their session when rows span sessions
        self._bold = QFont(theme.FONT_FAMILY)
        self._bold.setBold(True)

    def set_rows(self, rows: list[dict]) -> bool:
        """Replace rows. Updates in place when the same vehicles are listed in the
        same order; returns True when a full reset was needed."""
        self.multi_session = len({r["session_id"] for r in rows}) > 1
        same_keys = (len(rows) == len(self.rows) and all(
            (a["session_id"], a["track_id"]) == (b["session_id"], b["track_id"])
            for a, b in zip(rows, self.rows)))
        if same_keys:
            self.rows = rows
            if rows:
                self.dataChanged.emit(self.index(0, 0), self.index(len(rows) - 1, len(COLUMNS) - 1))
            return False
        self.beginResetModel()
        self.rows = rows
        self.endResetModel()
        return True

    def set_live(self, keys: set[tuple[int, int]]) -> None:
        if keys == self.live_keys:
            return
        self.live_keys = keys
        if self.rows:
            self.dataChanged.emit(self.index(0, 0), self.index(len(self.rows) - 1, 0))

    def row_key(self, row: int) -> tuple[int, int]:
        r = self.rows[row]
        return r["session_id"], r["track_id"]

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return COLUMNS[section].upper()
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.ToolTipRole:
            return TOOLTIPS[section]
        return None

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        r, col = self.rows[index.row()], index.column()
        live = (r["session_id"], r["track_id"]) in self.live_keys

        if role == Qt.ItemDataRole.DisplayRole:
            if col == 0:
                return "●"
            if col == 1:
                prefix = f"S{r['session_id']} " if self.multi_session else ""
                return f"{prefix}#{r['track_id']}"
            if col == 2:
                return r["vehicle_type"]
            if col == 3:
                return f"{r['confidence']:.2f}"
            if col == 4:
                return format_seconds(r["first_seen"])
            if col == 5:
                return {"IN": "↓ IN", "OUT": "↑ OUT"}.get(r["direction"], "—")
            if col == 6:
                return "Yes" if r["counted"] else "No"
        elif role == SORT_ROLE:
            return [live, r["session_id"] * 1_000_000 + r["track_id"], r["vehicle_type"], r["confidence"], r["first_seen"],
                    r["direction"] or "", r["counted"]][col]
        elif role == Qt.ItemDataRole.ForegroundRole:
            if col == 0:
                return QColor(theme.SUCCESS) if live else QColor(theme.BORDER_STRONG)
            if col == 6:
                return QColor(theme.SUCCESS) if r["counted"] else QColor(theme.SUBTLE)
            if col in (3, 4, 5):
                return QColor(theme.MUTED)
        elif role == Qt.ItemDataRole.DecorationRole and col == 2:
            return self.icons.get(r["vehicle_type"])
        elif role == Qt.ItemDataRole.FontRole and col in (1, 2):
            return self._bold
        elif role == Qt.ItemDataRole.TextAlignmentRole:
            if col == 0:
                return Qt.AlignmentFlag.AlignCenter
            return Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        elif role == Qt.ItemDataRole.ToolTipRole and col == 0:
            return "In frame now" if live else "Not in frame"
        return None


class VehicleTable(QTableView):
    """Sortable vehicle list that keeps the selection across data refreshes."""

    vehicle_selected = Signal(int, int)  # session_id, track_id

    def __init__(self, colors: dict[str, str], parent=None):
        super().__init__(parent)
        self.source_model = VehicleTableModel(colors, self)
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.source_model)
        self.proxy.setSortRole(SORT_ROLE)
        self.setModel(self.proxy)

        self.setSortingEnabled(True)
        self.sortByColumn(1, Qt.SortOrder.DescendingOrder)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.verticalHeader().hide()
        self.verticalHeader().setDefaultSectionSize(34)
        hh = self.horizontalHeader()
        hh.setHighlightSections(False)
        hh.setMinimumSectionSize(28)
        hh.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        hh.setStretchLastSection(True)
        hh.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        for col, width in enumerate([28, 80, 150, 70, 90, 90, 80]):
            if width:
                self.setColumnWidth(col, width)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._selected_key: tuple[int, int] | None = None
        self.selectionModel().selectionChanged.connect(self._on_selection)

    def set_rows(self, rows: list[dict]) -> None:
        if rows == self.source_model.rows:
            return
        key = self._selected_key
        scroll = self.verticalScrollBar().value()
        if not self.source_model.set_rows(rows):
            return  # updated in place: selection and scroll are untouched
        if key:
            self.select_vehicle(*key, emit=False, scroll=False)
        self.verticalScrollBar().setValue(scroll)

    def set_live(self, keys: set[tuple[int, int]]) -> None:
        self.source_model.set_live(keys)

    def select_vehicle(self, session_id: int, track_id: int, emit: bool = True,
                       scroll: bool = True) -> bool:
        for row in range(self.source_model.rowCount()):
            if self.source_model.row_key(row) == (session_id, track_id):
                idx = self.proxy.mapFromSource(self.source_model.index(row, 1))
                self.selectionModel().blockSignals(not emit)
                self.selectRow(idx.row())
                self.selectionModel().blockSignals(False)
                if scroll:
                    self.scrollTo(idx, QAbstractItemView.ScrollHint.EnsureVisible)
                self._selected_key = (session_id, track_id)
                return True
        return False

    def _on_selection(self, *_):
        rows = self.selectionModel().selectedRows()
        if not rows:
            return
        src = self.proxy.mapToSource(rows[0])
        self._selected_key = self.source_model.row_key(src.row())
        self.vehicle_selected.emit(*self._selected_key)
