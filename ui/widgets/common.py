from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ui import theme

# 24px stroke icons (Lucide-style), coloured at render time
ICON_PATHS = {
    "file": '<rect x="2" y="4" width="20" height="16" rx="2"/><path d="M7 4v16M17 4v16M2 9h5M2 15h5M17 9h5M17 15h5"/>',
    "camera": '<path d="M23 7l-7 5 7 5V7z"/><rect x="1" y="5" width="15" height="14" rx="2"/>',
    "network": '<circle cx="12" cy="12" r="10"/><path d="M2 12h20"/><path d="M12 2a15 15 0 0 1 4 10 15 15 0 0 1-4 10 15 15 0 0 1-4-10 15 15 0 0 1 4-10z"/>',
    "back": '<path d="M19 12H5M12 19l-7-7 7-7"/>',
    "records": '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
    "arrow": '<path d="M5 12h14M12 5l7 7-7 7"/>',
    "refresh": '<path d="M23 4v6h-6M1 20v-6h6"/><path d="M3.5 9a9 9 0 0 1 14.9-3.4L23 10M1 14l4.6 4.4A9 9 0 0 0 20.5 15"/>',
    "folder": '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>',
    # object classes
    "Car": '<path d="M5 17H3v-4l2-5h14l2 5v4h-2"/><path d="M3 13h18"/><circle cx="7.5" cy="17" r="2"/><circle cx="16.5" cy="17" r="2"/><path d="M9.5 17h5"/>',
    "Truck": '<path d="M1 4h14v12H1z"/><path d="M15 8h4l4 4v4h-8V8z"/><circle cx="5.5" cy="18" r="2"/><circle cx="18.5" cy="18" r="2"/>',
    "Bus": '<rect x="4" y="3" width="16" height="15" rx="2"/><path d="M4 11h16M12 3v8"/><circle cx="8" cy="15" r="1"/><circle cx="16" cy="15" r="1"/><path d="M6 18v3M18 18v3"/>',
    "Motorcycle": '<circle cx="5" cy="17" r="3"/><circle cx="19" cy="17" r="3"/><path d="M8 17h5l4-6h-5l-2-3H7"/><path d="M15 6h3l1 5"/>',
    "Bicycle": '<circle cx="5.5" cy="17.5" r="3.5"/><circle cx="18.5" cy="17.5" r="3.5"/><circle cx="15" cy="5" r="1"/><path d="M12 17.5V14l-3-3 4-3 2 3h2"/>',
    "Rickshaw": '<path d="M3 17V10a6 6 0 0 1 6-6h5l5 6v7"/><path d="M3 11h16M10 4v7"/><circle cx="6" cy="17" r="2"/><circle cx="17" cy="17" r="2"/><path d="M8 17h7"/>',
    "Person": '<circle cx="12" cy="4.5" r="2.5"/><path d="M12 8v7M7 11h10M12 15l-3.5 6.5M12 15l3.5 6.5"/>',
    "play": '<path d="M7 4l13 8-13 8V4z"/>',
    "pause": '<path d="M7 4h3v16H7zM14 4h3v16h-3z"/>',
    "stop": '<rect x="5" y="5" width="14" height="14" rx="2"/>',
    "rewind": '<path d="M11 19l-9-7 9-7v14zM22 19l-9-7 9-7v14z"/>',
    "forward": '<path d="M13 19l9-7-9-7v14zM2 19l9-7-9-7v14z"/>',
    "step": '<path d="M5 4l10 8-10 8V4zM19 5v14"/>',
    "restart": '<path d="M1 4v6h6"/><path d="M3.5 15a9 9 0 1 0 2.1-9.4L1 10"/>',
    "screenshot": '<path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/>',
    "expand": '<path d="M15 3h6v6M9 21H3v-6M21 3l-7 7M3 21l7-7"/>',
    "shrink": '<path d="M4 14h6v6M20 10h-6V4M14 10l7-7M3 21l7-7"/>',
    "line": '<path d="M4 18L20 6"/><circle cx="4" cy="18" r="2"/><circle cx="20" cy="6" r="2"/>',
    "record": '<circle cx="12" cy="12" r="7"/><circle cx="12" cy="12" r="3"/>',
    "upload":'<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M17 8l-5-5-5 5M12 3v12"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "close": '<path d="M18 6 6 18M6 6l12 12"/>',
    "plug": '<path d="M9 2v6M15 2v6M6 8h12v4a6 6 0 0 1-12 0V8zM12 18v4"/>',
    "eye":'<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>',
    "sum": '<path d="M18 4H6l6 8-6 8h12"/>',
}


def icon_pixmap(name: str, color: str, size: int = 24) -> QPixmap:
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
           f'stroke="{color}" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
           f'{ICON_PATHS[name]}</svg>')
    renderer = QSvgRenderer(QByteArray(svg.encode()))
    pix = QPixmap(size * 2, size * 2)  # 2x for crisp rendering on high-DPI screens
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    renderer.render(p, QRectF(0, 0, size * 2, size * 2))
    p.end()
    pix.setDevicePixelRatio(2)
    return pix


def icon(name: str, color: str = theme.TEXT, size: int = 18) -> QIcon:
    return QIcon(icon_pixmap(name, color, size))


class Card(QFrame):
    """White rounded panel with optional title row; add content to `self.body` (a QVBoxLayout)."""

    def __init__(self, title: str = "", hint: str = "", margins: int = 16, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(margins, margins - 2, margins, margins)
        outer.setSpacing(12)
        if title:
            head = QHBoxLayout()
            t = QLabel(title)
            t.setObjectName("SectionTitle")
            head.addWidget(t)
            head.addStretch()
            self.hint = QLabel(hint)
            self.hint.setObjectName("SectionHint")
            head.addWidget(self.hint)
            outer.addLayout(head)
        self.body = QVBoxLayout()
        self.body.setSpacing(10)
        outer.addLayout(self.body, 1)


def divider() -> QFrame:
    line = QFrame()
    line.setObjectName("Divider")
    return line


def brand_block() -> QWidget:
    """Logo mark + product name for the navy top bar."""
    w = QWidget()
    lay = QHBoxLayout(w)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(12)
    mark = QLabel("VA")
    mark.setFixedSize(34, 34)
    mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
    mark.setStyleSheet(f"background:{theme.ACCENT_GRADIENT}; color:#FFFFFF; border-radius:9px;"
                       "font-weight:800; font-size:13px;")
    lay.addWidget(mark)
    text = QVBoxLayout()
    text.setSpacing(0)
    title = QLabel("Vehicle Analytics System")
    title.setObjectName("BrandTitle")
    sub = QLabel("Detection · Classification · Tracking · Counting")
    sub.setObjectName("BrandSub")
    text.addWidget(title)
    text.addWidget(sub)
    lay.addLayout(text)
    return w


def top_bar() -> tuple[QFrame, QHBoxLayout]:
    bar = QFrame()
    bar.setObjectName("TopBar")
    bar.setFixedHeight(64)
    lay = QHBoxLayout(bar)
    lay.setContentsMargins(20, 0, 20, 0)
    lay.setSpacing(12)
    return bar, lay


def color_dot(color: str, size: int = 10) -> QLabel:
    dot = QLabel()
    dot.setFixedSize(size, size)
    dot.setStyleSheet(f"background:{color}; border-radius:{size // 2}px;")
    return dot
