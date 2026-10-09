from pathlib import Path

import cv2
from PySide6.QtCore import QSize, Qt, QThread, Signal
from PySide6.QtGui import QColor, QImage, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QComboBox, QFileDialog, QFrame, QGraphicsDropShadowEffect,
                               QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea,
                               QSizePolicy, QSlider, QStackedWidget, QVBoxLayout, QWidget)

from core.video_source import list_cameras
from ui import theme
from ui.widgets.common import brand_block, icon, icon_pixmap, top_bar
from utils.helpers import PROJECT_ROOT, format_seconds, mask_credentials

VIDEO_EXTS = {".mp4", ".avi", ".mov", ".mkv", ".wmv", ".m4v", ".webm", ".mpg", ".mpeg"}
VIDEO_FILTER = "Videos (*.mp4 *.avi *.mov *.mkv *.wmv *.m4v *.webm *.mpg *.mpeg);;All files (*)"
MODELS = [("YOLO11 Small — accurate (recommended)", "models/yolo11s.pt"),
          ("YOLO11 Nano — fastest, may miss bicycles", "models/yolo11n.pt"),
          ("YOLO11 Medium — most accurate, needs a GPU", "models/yolo11m.pt")]
SOURCES = [("file", "upload", "Upload video"), ("camera", "camera", "Webcam / USB"),
           ("ip", "network", "IP camera")]


# ------------------------------------------------------------------ helpers
def _shadow(widget: QWidget) -> None:
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(24)
    effect.setOffset(0, 4)
    effect.setColor(QColor(16, 24, 40, 28))
    widget.setGraphicsEffect(effect)


def _frame_to_pixmap(frame, width: int) -> QPixmap:
    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]
    img = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
    return QPixmap.fromImage(img).scaledToWidth(width, Qt.TransformationMode.SmoothTransformation)


def probe_video(path: str) -> dict | None:
    """First frame + basic facts about a video file (None if unreadable)."""
    cap = cv2.VideoCapture(path)
    ok, frame = cap.read()
    if not ok:
        cap.release()
        return None
    fps = cap.get(cv2.CAP_PROP_FPS) or 25
    frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    info = {"frame": frame, "width": frame.shape[1], "height": frame.shape[0], "fps": fps,
            "duration": frames / fps if frames > 0 else 0, "size_mb": Path(path).stat().st_size / 1e6}
    cap.release()
    return info


def _label(text: str, style: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(style + " background:transparent;")
    return lbl


def _field_label(text: str) -> QLabel:
    return _label(text, f"color:{theme.MUTED}; font-size:12px; font-weight:700;")


class CameraProbe(QThread):
    found = Signal(list)

    def run(self):
        self.found.emit(list_cameras())


class StreamTest(QThread):
    """Try to read one frame from a stream URL."""
    done = Signal(bool, object)  # ok, frame

    def __init__(self, url: str, parent=None):
        super().__init__(parent)
        self.url = url

    def run(self):
        cap = cv2.VideoCapture(self.url)
        ok, frame = cap.read() if cap.isOpened() else (False, None)
        cap.release()
        self.done.emit(bool(ok), frame if ok else None)


# ------------------------------------------------------------------ widgets
class DropZone(QFrame):
    """Dashed upload area: drag a video in or click Browse."""

    browse = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DropZone")
        self.setMinimumHeight(250)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        lay.addStretch()
        badge = QLabel()
        badge.setFixedSize(60, 60)
        badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        badge.setStyleSheet(f"background:{theme.SURFACE}; border:1px solid {theme.BORDER}; border-radius:30px;")
        badge.setPixmap(icon_pixmap("upload", theme.ACCENT, 26))
        lay.addWidget(badge, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(_label("Drag and drop a video here", f"color:{theme.TEXT}; font-size:16px; font-weight:700;"),
                      0, Qt.AlignmentFlag.AlignHCenter)
        lay.addWidget(_label("MP4, AVI, MOV, MKV, WMV or WEBM", f"color:{theme.SUBTLE}; font-size:12px;"),
                      0, Qt.AlignmentFlag.AlignHCenter)
        btn = QPushButton("  Browse files")
        btn.setObjectName("Primary")
        btn.setIcon(icon("folder", "#FFFFFF"))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(self.browse)
        lay.addWidget(btn, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addStretch()
        self.set_hover(False)

    def set_hover(self, on: bool) -> None:
        border = theme.ACCENT if on else theme.BORDER_STRONG
        bg = theme.ACCENT_SOFT if on else theme.SURFACE_2
        self.setStyleSheet(f"QFrame#DropZone {{ background:{bg}; border:2px dashed {border}; border-radius:12px; }}")

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.browse.emit()


class FileCard(QFrame):
    """Selected video: thumbnail, name and facts, with Change / Remove."""

    change = Signal()
    remove = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("FileCard")
        self.setStyleSheet(f"QFrame#FileCard {{ background:{theme.SURFACE}; border:1px solid {theme.BORDER};"
                           " border-radius:12px; }")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(16)
        self.thumb = QLabel()
        self.thumb.setFixedSize(256, 144)
        self.thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumb.setStyleSheet(f"background:{theme.VIDEO_BG}; border-radius:8px;")
        lay.addWidget(self.thumb)

        info = QVBoxLayout()
        info.setSpacing(6)
        ready = QHBoxLayout()
        ready.setSpacing(6)
        tick = QLabel()
        tick.setPixmap(icon_pixmap("check", theme.SUCCESS, 16))
        tick.setStyleSheet("background:transparent;")
        ready.addWidget(tick)
        ready.addWidget(_label("Video ready", f"color:{theme.SUCCESS}; font-size:12px; font-weight:700;"))
        ready.addStretch()
        info.addLayout(ready)
        self.name = _label("", f"color:{theme.TEXT}; font-size:16px; font-weight:700;")
        self.name.setWordWrap(True)
        info.addWidget(self.name)
        self.facts = _label("", f"color:{theme.MUTED}; font-size:13px;")
        info.addWidget(self.facts)
        self.path = _label("", f"color:{theme.SUBTLE}; font-size:11px;")
        self.path.setWordWrap(True)
        info.addWidget(self.path)
        info.addStretch()
        btns = QHBoxLayout()
        change = QPushButton("  Choose another")
        change.setIcon(icon("folder", theme.TEXT))
        change.clicked.connect(self.change)
        remove = QPushButton("  Remove")
        remove.setIcon(icon("close", theme.TEXT))
        remove.clicked.connect(self.remove)
        btns.addWidget(change)
        btns.addWidget(remove)
        btns.addStretch()
        info.addLayout(btns)
        lay.addLayout(info, 1)

    def show_file(self, path: str, meta: dict) -> None:
        self.thumb.setPixmap(_frame_to_pixmap(meta["frame"], 256))
        self.name.setText(Path(path).name)
        dur = format_seconds(meta["duration"]) if meta["duration"] else "live/unknown length"
        self.facts.setText(f"{meta['width']}×{meta['height']}   ·   {meta['fps']:.0f} fps   ·   "
                           f"{dur}   ·   {meta['size_mb']:.1f} MB")
        self.path.setText(str(Path(path).parent))


class ClassToggle(QPushButton):
    """Object-type toggle: colour dot + name, outlined in the class colour when on."""

    def __init__(self, name: str, color: str, parent=None):
        super().__init__(parent)
        self.name, self.color = name, color
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(40)
        self.toggled.connect(self._restyle)
        self.setChecked(True)
        self._restyle(True)

    def _restyle(self, on: bool) -> None:
        self.setText(f"  {self.name}")
        self.setIcon(icon(self.name, self.color if on else theme.SUBTLE, 18))
        if on:  # one calm accent style for every class; the icon carries the class colour
            self.setStyleSheet(
                f"QPushButton {{ text-align:left; padding:8px 12px; border-radius:8px; font-weight:700;"
                f" color:{theme.TEXT}; background:{theme.ACCENT_SOFT}; border:1px solid {theme.ACCENT}; }}")
        else:
            self.setStyleSheet(
                f"QPushButton {{ text-align:left; padding:8px 12px; border-radius:8px; font-weight:600;"
                f" color:{theme.SUBTLE}; background:{theme.SURFACE_2}; border:1px dashed {theme.BORDER_STRONG}; }}"
                f"QPushButton:hover {{ border-color:{theme.ACCENT}; color:{theme.TEXT}; }}")


def _card(title_number: int, title: str, hint: str) -> tuple[QFrame, QVBoxLayout, QHBoxLayout]:
    card = QFrame()
    card.setObjectName("Card")
    _shadow(card)
    lay = QVBoxLayout(card)
    lay.setContentsMargins(22, 18, 22, 22)
    lay.setSpacing(16)
    head = QHBoxLayout()
    head.setSpacing(10)
    badge = QLabel(str(title_number))
    badge.setObjectName("StepBadge")
    badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
    head.addWidget(badge)
    head.addWidget(_label(title, f"color:{theme.TEXT}; font-size:16px; font-weight:700;"))
    if hint:
        head.addSpacing(6)
        head.addWidget(_label(hint, f"color:{theme.SUBTLE}; font-size:12px;"))
    head.addStretch()
    lay.addLayout(head)
    return card, lay, head


# ------------------------------------------------------------------ page
class SourcePage(QWidget):
    """Step 1 of the app: choose the source and detection settings, then start."""

    start_requested = Signal(dict)
    view_records = Signal()

    def __init__(self, settings: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("Page")
        self.setAcceptDrops(True)
        self.settings = settings
        self.file_path: str | None = None
        self._probe: CameraProbe | None = None
        self._stream_test: StreamTest | None = None
        self._stream_ok_url: str | None = None
        self._cameras_probed = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        bar, bl = top_bar()
        bl.addWidget(brand_block())
        bl.addStretch()
        self.records_btn = QPushButton("  View saved records")
        self.records_btn.setIcon(icon("records", "#FFFFFF"))
        self.records_btn.clicked.connect(self.view_records)
        bl.addWidget(self.records_btn)
        root.addWidget(bar)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        holder = QWidget()
        holder.setObjectName("Page")
        hl = QHBoxLayout(holder)
        hl.setContentsMargins(28, 24, 28, 24)
        hl.addStretch()
        content = QWidget()
        content.setMaximumWidth(1320)
        hl.addWidget(content, 30)
        hl.addStretch()
        scroll.setWidget(holder)
        root.addWidget(scroll, 1)

        cl = QVBoxLayout(content)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(20)
        cl.addLayout(self._build_header())
        cols = QHBoxLayout()
        cols.setSpacing(20)
        cols.addWidget(self._build_source_card(), 1)
        settings_card = self._build_settings_card()
        settings_card.setFixedWidth(380)
        cols.addWidget(settings_card, 0, Qt.AlignmentFlag.AlignTop)
        cl.addLayout(cols)
        cl.addStretch()

        self.group.button(0).setChecked(True)
        self._on_kind(0)

    # ------------------------------------------------------------ builders
    def _build_header(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(16)
        titles = QVBoxLayout()
        titles.setSpacing(4)
        titles.addWidget(_label("New analysis", f"color:{theme.TEXT}; font-size:26px; font-weight:800;"))
        self.summary = _label("", f"color:{theme.MUTED}; font-size:13px;")
        titles.addWidget(self.summary)
        row.addLayout(titles, 1)
        self.start_btn = QPushButton("Start analysis  ")
        self.start_btn.setObjectName("Primary")
        self.start_btn.setIcon(icon("arrow", "#FFFFFF"))
        self.start_btn.setIconSize(QSize(16, 16))
        self.start_btn.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.start_btn.setMinimumSize(200, 48)
        self.start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.start_btn.setToolTip("Start detecting, tracking and counting (Enter)")
        self.start_btn.clicked.connect(self._start)
        row.addWidget(self.start_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        return row

    def _build_source_card(self) -> QFrame:
        card, lay, head = _card(1, "Video source", "")
        # segmented tabs in the card header
        seg = QFrame()
        seg.setObjectName("Segmented")
        seg.setStyleSheet(f"QFrame#Segmented {{ background:{theme.SURFACE_2}; border:1px solid {theme.BORDER};"
                          " border-radius:9px; }")
        sl = QHBoxLayout(seg)
        sl.setContentsMargins(3, 3, 3, 3)
        sl.setSpacing(2)
        self.group = QButtonGroup(self)
        for i, (_, icon_name, text) in enumerate(SOURCES):
            b = QPushButton(f"  {text}")
            b.setObjectName("SegButton")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setProperty("icon_name", icon_name)
            self.group.addButton(b, i)
            sl.addWidget(b)
        head.addWidget(seg)
        self.group.idClicked.connect(self._on_kind)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._file_page())
        self.stack.addWidget(self._camera_page())
        self.stack.addWidget(self._ip_page())
        lay.addWidget(self.stack)
        return card

    def _file_page(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        self.file_stack = QStackedWidget()
        self.drop = DropZone()
        self.drop.browse.connect(self._browse)
        self.file_card = FileCard()
        self.file_card.change.connect(self._browse)
        self.file_card.remove.connect(self._clear_file)
        self.file_stack.addWidget(self.drop)
        self.file_stack.addWidget(self.file_card)
        lay.addWidget(self.file_stack)
        row = QHBoxLayout()
        row.addWidget(_label("No video handy?", f"color:{theme.SUBTLE}; font-size:12px;"))
        sample = QPushButton("Use the sample highway video")
        sample.setObjectName("Link")
        sample.setCursor(Qt.CursorShape.PointingHandCursor)
        sample.clicked.connect(lambda: self._set_file(self.settings["video"]["default_source"]))
        row.addWidget(sample)
        row.addStretch()
        lay.addLayout(row)
        return w

    def _camera_page(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        lay.addWidget(_field_label("Camera"))
        row = QHBoxLayout()
        self.camera_combo = QComboBox()
        self.camera_combo.currentIndexChanged.connect(self._validate)
        row.addWidget(self.camera_combo, 1)
        self.refresh_btn = QPushButton("  Detect cameras")
        self.refresh_btn.setIcon(icon("refresh", theme.TEXT))
        self.refresh_btn.clicked.connect(self._probe_cameras)
        row.addWidget(self.refresh_btn)
        lay.addLayout(row)
        self.camera_status = _label("", f"color:{theme.SUBTLE}; font-size:12px;")
        lay.addWidget(self.camera_status)
        lay.addWidget(_label("The camera turns on when you press Start analysis.",
                             f"color:{theme.SUBTLE}; font-size:12px;"))
        lay.addStretch()
        return w

    def _ip_page(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        lay.addWidget(_field_label("Stream URL"))
        row = QHBoxLayout()
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("rtsp://username:password@192.168.1.64:554/stream1")
        self.url_edit.textChanged.connect(self._on_url_changed)
        row.addWidget(self.url_edit, 1)
        self.test_btn = QPushButton("  Test connection")
        self.test_btn.setIcon(icon("plug", theme.TEXT))
        self.test_btn.clicked.connect(self._test_stream)
        row.addWidget(self.test_btn)
        lay.addLayout(row)
        self.stream_status = _label("", f"color:{theme.SUBTLE}; font-size:12px;")
        lay.addWidget(self.stream_status)
        self.stream_thumb = QLabel()
        self.stream_thumb.setFixedSize(256, 144)
        self.stream_thumb.setStyleSheet(f"background:{theme.VIDEO_BG}; border-radius:8px;")
        self.stream_thumb.hide()
        lay.addWidget(self.stream_thumb)
        hint = _label("Examples:  rtsp://admin:pass@192.168.1.64:554/Streaming/Channels/101   ·   "
                      "http://192.168.1.20:8080/video", f"color:{theme.SUBTLE}; font-size:12px;")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        lay.addStretch()
        return w

    def _build_settings_card(self) -> QFrame:
        card, lay, _ = _card(2, "Settings", "")
        lay.addWidget(_field_label("Detection model"))
        self.model_combo = QComboBox()
        for name, path in MODELS:
            self.model_combo.addItem(name, path)
        lay.addWidget(self.model_combo)

        lay.addWidget(_field_label("Detail level"))
        self.detail_combo = QComboBox()
        self.detail_combo.addItem("Standard — fastest, may miss small or distant vehicles", 640)
        self.detail_combo.addItem("High — recommended, finds small vehicles and motorbikes", 960)
        self.detail_combo.addItem("Maximum — best for distant motorbikes, slowest", 1280)
        self.detail_combo.setCurrentIndex(1)
        self.detail_combo.setToolTip("Larger sizes find small objects more reliably but run slower on a CPU "
                                     "(roughly 7 / 4 / 2 frames per second)")
        lay.addWidget(self.detail_combo)

        conf_head = QHBoxLayout()
        conf_head.addWidget(_field_label("Minimum confidence"))
        conf_head.addStretch()
        self.conf_value = _label("", f"color:{theme.TEXT}; font-weight:800;")
        conf_head.addWidget(self.conf_value)
        lay.addLayout(conf_head)
        self.conf_slider = QSlider(Qt.Orientation.Horizontal)
        self.conf_slider.setRange(10, 90)
        self.conf_slider.valueChanged.connect(lambda v: self.conf_value.setText(f"{v / 100:.2f}"))
        self.conf_slider.setValue(int(self.settings["model"]["conf"] * 100))
        lay.addWidget(self.conf_slider)
        hint = _label("Lower finds more distant objects, but may add false detections.",
                      f"color:{theme.SUBTLE}; font-size:12px;")
        hint.setWordWrap(True)
        lay.addWidget(hint)

        lay.addWidget(_field_label("Objects to detect"))
        grid = QGridLayout()
        grid.setSpacing(8)
        self.class_toggles: dict[str, ClassToggle] = {}
        for i, (name, color) in enumerate(self.settings["colors"].items()):
            t = ClassToggle(name, color)
            t.toggled.connect(self._validate)
            self.class_toggles[name] = t
            grid.addWidget(t, i // 2, i % 2)
        lay.addLayout(grid)
        return card

    # ------------------------------------------------------------- source kind
    def _kind(self) -> str:
        return SOURCES[self.group.checkedId()][0]

    def _on_kind(self, idx: int) -> None:
        for i, b in enumerate(self.group.buttons()):
            on = i == idx
            b.setIcon(icon(b.property("icon_name"), "#FFFFFF" if on else theme.MUTED, 16))
        for i in range(self.stack.count()):
            vertical = QSizePolicy.Policy.Preferred if i == idx else QSizePolicy.Policy.Ignored
            self.stack.widget(i).setSizePolicy(QSizePolicy.Policy.Expanding, vertical)
        self.stack.setCurrentIndex(idx)
        if SOURCES[idx][0] == "camera" and not self._cameras_probed:
            self._probe_cameras()
        self._validate()

    # ------------------------------------------------------------- file
    def _browse(self) -> None:
        start = str(Path(self.file_path).parent) if self.file_path else str(PROJECT_ROOT / "data" / "videos")
        path, _ = QFileDialog.getOpenFileName(self, "Select a video file", start, VIDEO_FILTER)
        if path:
            self._set_file(path)

    def _set_file(self, path: str) -> None:
        meta = probe_video(path)
        if meta is None:
            self.summary.setText(f"⚠  Could not read “{Path(path).name}”. Is it a valid video file?")
            self.summary.setStyleSheet(f"color:{theme.DANGER}; font-size:13px; background:transparent;")
            return
        self.file_path = path
        self.file_card.show_file(path, meta)
        self.file_stack.setCurrentWidget(self.file_card)
        self.group.button(0).setChecked(True)
        self._on_kind(0)

    def _clear_file(self) -> None:
        self.file_path = None
        self.file_stack.setCurrentWidget(self.drop)
        self._validate()

    # drag and drop anywhere on the page
    def _dropped_video(self, event) -> str | None:
        for url in event.mimeData().urls():
            p = url.toLocalFile()
            if p and Path(p).suffix.lower() in VIDEO_EXTS:
                return p
        return None

    def dragEnterEvent(self, event):
        if self._dropped_video(event):
            event.acceptProposedAction()
            self.group.button(0).setChecked(True)
            self._on_kind(0)
            self.file_stack.setCurrentWidget(self.drop)
            self.drop.set_hover(True)

    def dragLeaveEvent(self, event):
        self.drop.set_hover(False)
        if self.file_path:
            self.file_stack.setCurrentWidget(self.file_card)

    def dropEvent(self, event):
        self.drop.set_hover(False)
        path = self._dropped_video(event)
        if path:
            event.acceptProposedAction()
            self._set_file(path)

    # ------------------------------------------------------------- camera
    def _probe_cameras(self) -> None:
        if self._probe and self._probe.isRunning():
            return
        self._cameras_probed = True
        self.camera_combo.clear()
        self.camera_combo.setEnabled(False)
        self.refresh_btn.setEnabled(False)
        self.camera_status.setText("Searching for cameras…")
        self._probe = CameraProbe(self)
        self._probe.found.connect(self._on_cameras)
        self._probe.start()

    def _on_cameras(self, cams: list) -> None:
        self.refresh_btn.setEnabled(True)
        self.camera_combo.setEnabled(bool(cams))
        for idx, label in cams:
            self.camera_combo.addItem(label + ("  (default)" if idx == 0 else ""), idx)
        n = len(cams)
        self.camera_status.setText(f"✓  {n} camera{'s' if n > 1 else ''} found." if cams else
                                   "No camera found. Connect one and click “Detect cameras”.")
        self._validate()

    # ------------------------------------------------------------- IP stream
    def _on_url_changed(self) -> None:
        self._stream_ok_url = None
        self.stream_thumb.hide()
        self.stream_status.setText("")
        self._validate()

    def _valid_url(self) -> str | None:
        url = self.url_edit.text().strip()
        if url.lower().startswith(("rtsp://", "rtsps://", "http://", "https://")) and len(url) > 10:
            return url
        return None

    def _test_stream(self) -> None:
        url = self._valid_url()
        if not url or (self._stream_test and self._stream_test.isRunning()):
            return
        self.test_btn.setEnabled(False)
        self.stream_status.setText("Connecting…")
        self.stream_status.setStyleSheet(f"color:{theme.SUBTLE}; font-size:12px; background:transparent;")
        self._stream_test = StreamTest(url, self)
        self._stream_test.done.connect(lambda ok, frame, u=url: self._on_stream_tested(u, ok, frame))
        self._stream_test.start()

    def _on_stream_tested(self, url: str, ok: bool, frame) -> None:
        self.test_btn.setEnabled(True)
        if url != self._valid_url():
            return  # URL changed while testing
        if ok:
            self._stream_ok_url = url
            self.stream_status.setText("✓  Connected — stream is working.")
            self.stream_status.setStyleSheet(f"color:{theme.SUCCESS}; font-size:12px; font-weight:700; background:transparent;")
            self.stream_thumb.setPixmap(_frame_to_pixmap(frame, 256))
            self.stream_thumb.show()
        else:
            self.stream_status.setText("✗  Could not connect. Check the address, user name and password.")
            self.stream_status.setStyleSheet(f"color:{theme.DANGER}; font-size:12px; font-weight:700; background:transparent;")

    # ------------------------------------------------------------- validation
    def _source(self) -> tuple[object, str] | None:
        kind = self._kind()
        if kind == "file":
            if self.file_path and Path(self.file_path).exists():
                return self.file_path, self.file_path
        elif kind == "camera":
            if self.camera_combo.count() and self.camera_combo.isEnabled():
                idx = self.camera_combo.currentData()
                return idx, f"Camera {idx}"
        else:
            url = self._valid_url()
            if url:
                return url, mask_credentials(url)  # label is shown and stored; never the password
        return None

    def _selected_classes(self) -> list[str]:
        return [n for n, t in self.class_toggles.items() if t.isChecked()]

    def _validate(self, *_):
        src = self._source()
        classes = self._selected_classes()
        ok = src is not None and bool(classes)
        self.start_btn.setEnabled(ok)
        color = theme.MUTED
        if src is None:
            msg = {"file": "Step 1 — drop a video below or browse for one.",
                   "camera": "Step 1 — choose a camera.",
                   "ip": "Step 1 — enter the camera's stream address."}[self._kind()]
        elif not classes:
            msg, color = "Select at least one object type in Settings.", theme.WARNING
        else:
            name = Path(str(src[1])).name if self._kind() == "file" else src[1]
            msg, color = f"✓  Ready to analyse  {name}", theme.SUCCESS
        self.summary.setText(msg)
        self.summary.setStyleSheet(f"color:{color}; font-size:13px; font-weight:600; background:transparent;")

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and self.start_btn.isEnabled():
            self._start()
        else:
            super().keyPressEvent(event)

    def _start(self) -> None:
        src = self._source()
        if src is None:
            return
        self.start_requested.emit({
            "source": src[0],
            "label": src[1],
            "kind": self._kind(),
            "weights": str(PROJECT_ROOT / self.model_combo.currentData()),
            "conf": self.conf_slider.value() / 100,
            "imgsz": self.detail_combo.currentData(),
            "classes": self._selected_classes(),
        })
