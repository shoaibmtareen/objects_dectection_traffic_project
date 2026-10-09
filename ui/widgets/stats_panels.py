from PySide6.QtCore import QEasingCurve, Qt, QTimer, QVariantAnimation, Signal
from PySide6.QtWidgets import QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from ui import theme
from ui.widgets.common import icon_pixmap


class AnimatedNumber(QLabel):
    """Label that counts smoothly to each new value."""

    def __init__(self, parent=None):
        super().__init__("0", parent)
        self._value = 0
        self._anim = QVariantAnimation(self, duration=300)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.valueChanged.connect(lambda v: self.setText(f"{round(v):,}"))

    def set_value(self, n: int) -> None:
        if n == self._value:
            return
        self._anim.stop()
        self._anim.setStartValue(self._value)
        self._anim.setEndValue(n)
        self._value = n
        self._anim.start()

    def reset(self) -> None:
        self._anim.stop()
        self._value = 0
        self.setText("0")


class ClassTile(QFrame):
    """One object class. Fills with the class gradient when it has objects; click to drill down."""

    clicked = Signal(str)

    def __init__(self, name: str, color: str, parent=None):
        super().__init__(parent)
        self.name, self.color = name, color
        self.setObjectName("Tile")
        self.setMinimumHeight(70)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip(f"Show every {name.lower()} in Records")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        lay.setSpacing(0)

        top = QHBoxLayout()
        top.setSpacing(4)
        self.icon = QLabel()
        self.icon.setFixedSize(18, 18)
        self.icon.setStyleSheet("background:transparent;")
        top.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignTop)
        top.addStretch()
        self.value = AnimatedNumber()
        self.value.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        top.addWidget(self.value)
        lay.addLayout(top)
        self.label = QLabel(name)
        lay.addWidget(self.label)
        self._active: bool | None = None
        self.set_value(0)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.name)
        super().mouseReleaseEvent(event)

    def set_value(self, n: int) -> None:
        self.value.set_value(n)
        active = n > 0
        if active == self._active:
            return
        self._active = active
        if active:
            self.setStyleSheet(
                f"QFrame#Tile {{ background:{theme.gradient(self.color)}; border:1px solid {self.color};"
                f" border-radius:10px; }}"
                f"QFrame#Tile:hover {{ border:2px solid {theme.TEXT}; }}")
            self.icon.setPixmap(icon_pixmap(self.name, "#FFFFFF", 18))
            self.label.setStyleSheet("color:rgba(255,255,255,0.92); font-size:11px; font-weight:700;"
                                     " background:transparent;")
            self.value.setStyleSheet("color:#FFFFFF; font-size:24px; font-weight:800; background:transparent;")
        else:
            self.setStyleSheet(
                f"QFrame#Tile {{ background:{theme.SURFACE_2}; border:1px solid {theme.BORDER};"
                f" border-radius:10px; }}"
                f"QFrame#Tile:hover {{ border:1px solid {self.color}; }}")
            self.icon.setPixmap(icon_pixmap(self.name, self.color, 18))
            self.label.setStyleSheet(f"color:{theme.MUTED}; font-size:11px; font-weight:600; background:transparent;")
            self.value.setStyleSheet(f"color:{theme.SUBTLE}; font-size:24px; font-weight:800; background:transparent;")

    def reset(self) -> None:
        self.value.reset()
        self._active = None
        self.set_value(0)


class _StatsCard(QFrame):
    """Shared layout: header (icon, title, right label), headline number, class tile grid."""

    class_clicked = Signal(str)

    def __init__(self, icon_name: str, title: str, caption: str, colors: dict[str, str],
                 non_vehicle: list[str], parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.non_vehicle = set(non_vehicle)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(12)

        head = QHBoxLayout()
        head.setSpacing(10)
        badge = QLabel()
        badge.setFixedSize(32, 32)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(f"background:{theme.ACCENT_GRADIENT}; border-radius:9px;")
        badge.setPixmap(icon_pixmap(icon_name, "#FFFFFF", 18))
        head.addWidget(badge)
        t = QLabel(title)
        t.setStyleSheet(f"font-size:15px; font-weight:700; color:{theme.TEXT};")
        head.addWidget(t)
        head.addStretch()
        self.right_label = QLabel("")
        self.right_label.setStyleSheet(f"color:{theme.MUTED}; font-size:12px; font-weight:600;")
        head.addWidget(self.right_label)
        lay.addLayout(head)

        big = QHBoxLayout()
        big.setSpacing(12)
        self.number = QLabel("0")  # not animated: must always agree with the split below
        self.number.setStyleSheet(f"font-size:42px; font-weight:800; color:{theme.TEXT};")
        big.addWidget(self.number, 0, Qt.AlignmentFlag.AlignBottom)
        cap = QVBoxLayout()
        cap.setSpacing(0)
        cap.addStretch()
        self.caption = QLabel(caption)
        self.caption.setStyleSheet(f"color:{theme.TEXT}; font-size:13px; font-weight:600;")
        self.split = QLabel("")
        self.split.setStyleSheet(f"color:{theme.MUTED}; font-size:12px;")
        cap.addWidget(self.caption)
        cap.addWidget(self.split)
        big.addLayout(cap)
        big.addStretch()
        lay.addLayout(big)

        grid = QGridLayout()
        grid.setSpacing(8)
        self.tiles: dict[str, ClassTile] = {}
        for i, (name, color) in enumerate(colors.items()):
            tile = ClassTile(name, color)
            tile.clicked.connect(self.class_clicked)
            self.tiles[name] = tile
            grid.addWidget(tile, i // 4, i % 4)
        lay.addLayout(grid)
        self.extra = QVBoxLayout()
        self.extra.setSpacing(8)
        lay.addLayout(self.extra)
        lay.addStretch()

    def _set_counts(self, by_type: dict[str, int]) -> None:
        total = sum(by_type.values())
        people = sum(n for t, n in by_type.items() if t in self.non_vehicle)
        self.number.setText(f"{total:,}")
        self.split.setText(f"{total - people:,} vehicles  ·  {people:,} people")
        for name, tile in self.tiles.items():
            tile.set_value(by_type.get(name, 0))

    def _reset_counts(self) -> None:
        self.number.setText("0")
        self.split.setText("0 vehicles  ·  0 people")
        for tile in self.tiles.values():
            tile.reset()


class CurrentFramePanel(_StatsCard):
    """Objects visible right now, plus the object selected in the video."""

    details_requested = Signal()

    def __init__(self, colors: dict[str, str], non_vehicle: list[str], parent=None):
        super().__init__("eye", "Current frame", "objects in view", colors, non_vehicle, parent)
        self.selected = QFrame()
        self.selected.setObjectName("SelectedStrip")
        self.selected.setStyleSheet(
            f"QFrame#SelectedStrip {{ background:{theme.ACCENT_SOFT}; border:1px solid {theme.ACCENT};"
            " border-radius:10px; }")
        sl = QHBoxLayout(self.selected)
        sl.setContentsMargins(12, 6, 6, 6)
        self.selected_text = QLabel("")
        self.selected_text.setStyleSheet(f"color:{theme.TEXT}; font-size:12px; background:transparent;")
        sl.addWidget(self.selected_text, 1)
        btn = QPushButton("Details")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(self.details_requested)
        sl.addWidget(btn)
        self.selected.hide()
        self.extra.addWidget(self.selected)

        # pulsing "Live" indicator
        self._pulse_on = True
        self._state = "idle"
        self._pulse = QTimer(self, interval=650)
        self._pulse.timeout.connect(self._tick_pulse)
        self.set_status("idle")
        self.reset()

    def reset(self) -> None:
        self._reset_counts()
        self.selected.hide()

    def _tick_pulse(self) -> None:
        self._pulse_on = not self._pulse_on
        color = theme.SUCCESS if self._pulse_on else theme.SUBTLE
        self.right_label.setStyleSheet(f"color:{color}; font-size:12px; font-weight:800;")

    def set_status(self, state: str) -> None:
        self._state = state
        text, color = {"live": ("●  LIVE", theme.SUCCESS), "paused": ("❚❚  PAUSED", theme.WARNING),
                       "loading": ("CONNECTING…", theme.MUTED), "completed": ("■  ENDED", theme.MUTED)}.get(state, ("NOT RUNNING", theme.SUBTLE))
        self.right_label.setText(text)
        self.right_label.setStyleSheet(f"color:{color}; font-size:12px; font-weight:800;")
        if state == "live":
            self._pulse.start()
        else:
            self._pulse.stop()

    def update_from(self, result) -> None:
        self._set_counts(result.in_frame_by_type)

    def update_counts(self, by_type: dict[str, int]) -> None:
        self._set_counts(by_type)

    def show_selected(self, text: str | None) -> None:
        self.selected.setVisible(bool(text))
        if text:
            self.selected_text.setText(text)


class TotalsPanel(_StatsCard):
    """Every distinct object seen this session, plus counting-line crossings."""

    def __init__(self, colors: dict[str, str], non_vehicle: list[str], parent=None):
        super().__init__("sum", "Total this session", "objects detected", colors, non_vehicle, parent)
        line = QFrame()
        self.line_strip = line
        line.setObjectName("LineStrip")
        line.setStyleSheet(f"QFrame#LineStrip {{ background:{theme.SURFACE_2}; border:1px solid {theme.BORDER};"
                           " border-radius:10px; }")
        ll = QHBoxLayout(line)
        ll.setContentsMargins(12, 8, 12, 8)
        ll.setSpacing(16)
        t = QLabel("Counting line")
        t.setStyleSheet(f"color:{theme.MUTED}; font-size:12px; font-weight:600; background:transparent;")
        ll.addWidget(t)
        ll.addStretch()
        self.line_in = QLabel()
        self.line_out = QLabel()
        self.line_in.setStyleSheet(f"color:{theme.SUCCESS}; font-size:13px; font-weight:800; background:transparent;")
        self.line_out.setStyleSheet(f"color:{theme.WARNING}; font-size:13px; font-weight:800; background:transparent;")
        self.line_in.setToolTip("Vehicles that crossed the counting line moving down / in")
        self.line_out.setToolTip("Vehicles that crossed the counting line moving up / out")
        ll.addWidget(self.line_in)
        ll.addWidget(self.line_out)
        self.extra.addWidget(line)
        self.reset()

    def reset(self) -> None:
        self._reset_counts()
        self.right_label.setText("")
        self.line_in.setText("↓ IN  0")
        self.line_out.setText("↑ OUT  0")

    def update_from(self, result, elapsed_text: str) -> None:
        self._set_counts(result.unique_by_type)
        self.right_label.setText(elapsed_text)
        self.line_in.setText(f"↓ IN  {result.in_count:,}")
        self.line_out.setText(f"↑ OUT  {result.out_count:,}")
