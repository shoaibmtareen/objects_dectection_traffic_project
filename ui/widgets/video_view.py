from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget

from ui import theme

MAX_ZOOM = 8.0


class VideoView(QWidget):
    """Shows the annotated video, letterboxed, with rounded corners.

    - Mouse wheel / touchpad pinch zooms around the cursor; drag pans while zoomed;
      double-click resets the zoom.
    - Draw mode: drag to define the counting line -> `line_drawn(start, end)`
      in normalised (0..1) image coordinates.
    - Otherwise a click emits `clicked(x, y)` in normalised coordinates.
    """

    line_drawn = Signal(tuple, tuple)
    clicked = Signal(float, float)
    zoom_changed = Signal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(480, 270)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_AcceptTouchEvents, True)
        self._image: QImage | None = None
        self._draw_mode = False
        self._drag_start: QPointF | None = None
        self._drag_end: QPointF | None = None
        # zoom state: factor and the fraction of the zoomed image hidden left / above the view
        self._zoom = 1.0
        self._fx = 0.0
        self._fy = 0.0
        self._press: QPointF | None = None
        self._panning = False
        self.placeholder = "No video source\nOpen a video, webcam or stream to begin"
        self.colors: dict[str, str] = {}
        self._overlay: dict = {}
        self.show_line = False  # counting line is drawn only when switched on

    # ---------- public ----------
    def set_image(self, image: QImage) -> None:
        self._image = image
        self.update()

    def set_frame(self, image: QImage, overlay: dict) -> None:
        self._image, self._overlay = image, overlay or {}
        self.update()

    def current_image(self) -> QImage | None:
        """Full-resolution frame with boxes and labels drawn on (for screenshots)."""
        if self._image is None:
            return None
        out = self._image.convertToFormat(QImage.Format.Format_RGB32)
        p = QPainter(out)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        self._paint_overlay(p, QRectF(0, 0, out.width(), out.height()), max(1.0, out.width() / 1280))
        p.end()
        return out

    def clear(self) -> None:
        self._image = None
        self.reset_zoom()

    def set_draw_mode(self, enabled: bool) -> None:
        self._draw_mode = enabled
        self._drag_start = self._drag_end = None
        self._update_cursor()
        if enabled:
            self.setFocus(Qt.FocusReason.OtherFocusReason)  # so Esc can cancel
        self.update()

    @property
    def zoom(self) -> float:
        return self._zoom

    def reset_zoom(self) -> None:
        self._zoom, self._fx, self._fy = 1.0, 0.0, 0.0
        self._update_cursor()
        self.zoom_changed.emit(self._zoom)
        self.update()

    def zoom_by(self, factor: float, anchor: QPointF | None = None) -> None:
        """Zoom keeping the image point under `anchor` (default: view centre) fixed."""
        if self._image is None:
            return
        base = self._fit_rect()
        anchor = anchor if anchor is not None else base.center()
        old = self._image_rect()
        rel_x = (anchor.x() - old.x()) / old.width()
        rel_y = (anchor.y() - old.y()) / old.height()
        self._zoom = min(MAX_ZOOM, max(1.0, self._zoom * factor))
        w, h = base.width() * self._zoom, base.height() * self._zoom
        left = anchor.x() - rel_x * w
        top = anchor.y() - rel_y * h
        self._fx = (base.x() - left) / w
        self._fy = (base.y() - top) / h
        self._clamp()
        self._update_cursor()
        self.zoom_changed.emit(self._zoom)
        self.update()

    # ---------- geometry ----------
    def _fit_rect(self) -> QRectF:
        if self._image is None:
            return QRectF(self.rect())
        iw, ih = self._image.width(), self._image.height()
        s = min(self.width() / iw, self.height() / ih)
        w, h = iw * s, ih * s
        return QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)

    def _image_rect(self) -> QRectF:
        """Where the (possibly zoomed) image is drawn, in widget coordinates."""
        base = self._fit_rect()
        w, h = base.width() * self._zoom, base.height() * self._zoom
        return QRectF(base.x() - self._fx * w, base.y() - self._fy * h, w, h)

    def _clamp(self) -> None:
        limit = 1.0 - 1.0 / self._zoom
        self._fx = min(max(self._fx, 0.0), limit)
        self._fy = min(max(self._fy, 0.0), limit)

    def _to_norm(self, p: QPointF) -> tuple[float, float]:
        r = self._image_rect()
        x = min(max((p.x() - r.x()) / r.width(), 0.0), 1.0)
        y = min(max((p.y() - r.y()) / r.height(), 0.0), 1.0)
        return round(x, 4), round(y, 4)

    def _update_cursor(self) -> None:
        if self._draw_mode:
            shape = Qt.CursorShape.CrossCursor
        elif self._panning:
            shape = Qt.CursorShape.ClosedHandCursor
        elif self._zoom > 1.0:
            shape = Qt.CursorShape.OpenHandCursor
        else:
            shape = Qt.CursorShape.ArrowCursor
        self.setCursor(shape)

    # ---------- painting ----------
    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        bg = QPainterPath()
        bg.addRoundedRect(QRectF(self.rect()), 12, 12)
        painter.fillPath(bg, QColor(theme.VIDEO_BG))

        if self._image is None:
            painter.setPen(QColor("#8A9BB8"))
            painter.setFont(QFont(theme.FONT_FAMILY, 11))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.placeholder)
            return

        base = self._fit_rect()
        clip = QPainterPath()
        clip.addRoundedRect(base, 10, 10)
        painter.setClipPath(clip)
        painter.drawImage(self._image_rect(), self._image)
        try:
            self._paint_overlay(painter, self._image_rect(), 1.0)
        except Exception as exc:  # noqa: BLE001 - never let a drawing bug take down the app
            print(f"[video_view] overlay error: {exc}")
        painter.setClipping(False)

        if self._zoom > 1.01:
            self._draw_zoom_badge(painter, base)

        if self._draw_mode:
            painter.fillRect(base, QColor(11, 18, 32, 90))
            painter.setPen(QColor("#FFFFFF"))
            painter.setFont(QFont(theme.FONT_FAMILY, 11, QFont.Weight.DemiBold))
            painter.drawText(base.adjusted(0, 14, 0, 0), Qt.AlignmentFlag.AlignHCenter,
                             "Drag across the road to draw the counting line  ·  Esc to cancel")
            if self._drag_start and self._drag_end:
                painter.setPen(QPen(QColor("#FACC15"), 3, Qt.PenStyle.DashLine))
                painter.drawLine(self._drag_start, self._drag_end)
                painter.setBrush(QColor("#FACC15"))
                for p in (self._drag_start, self._drag_end):
                    painter.drawEllipse(p, 5, 5)

    def _paint_overlay(self, p: QPainter, r: QRectF, scale: float) -> None:
        """Boxes, labels and the counting line, mapped onto image rect `r`.
        Line widths and fonts use screen pixels, so they stay small when zoomed."""
        ov = self._overlay
        if not ov:
            return

        def pt(nx, ny):
            return QPointF(r.x() + nx * r.width(), r.y() + ny * r.height())

        font = QFont(theme.FONT_FAMILY, 8)
        font.setPixelSize(max(9, int(11 * scale)))
        font.setBold(True)
        p.setFont(font)

        # counting line: white with a dark outline, small label at its left end
        if self.show_line and "line" in ov:
            a, b = pt(*ov["line"][0]), pt(*ov["line"][1])
            for color, width in ((QColor(15, 23, 42, 200), 5 * scale), (QColor("#FFFFFF"), 2.5 * scale)):
                pen = QPen(color, width)
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                p.setPen(pen)
                p.drawLine(a, b)
            left = a if a.x() <= b.x() else b
            self._pill(p, QPointF(left.x() + 8 * scale, left.y() - 8 * scale), ov.get("line_text", ""),
                       QColor(15, 23, 42, 215), scale, anchor_bottom=True)

        for o in ov.get("boxes", []):
            color = QColor(self.colors.get(o["type"], "#94A3B8"))
            x1, y1 = pt(o["box"][0], o["box"][1]).x(), pt(o["box"][0], o["box"][1]).y()
            x2, y2 = pt(o["box"][2], o["box"][3]).x(), pt(o["box"][2], o["box"][3]).y()
            box = QRectF(QPointF(x1, y1), QPointF(x2, y2))
            if len(o.get("trail", [])) > 1:
                p.setPen(QPen(color, 2 * scale))
                pts = [pt(*q) for q in o["trail"]]
                for i in range(1, len(pts)):
                    p.drawLine(pts[i - 1], pts[i])
            highlighted = o["id"] == ov.get("highlight")
            if highlighted:
                p.setPen(QPen(QColor("#FACC15"), 3.5 * scale))
            else:
                p.setPen(QPen(color, 2 * scale))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(box, 3 * scale, 3 * scale)
            if o.get("counted"):
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(QColor("#22C55E"))
                p.drawEllipse(QPointF(x2 - 6 * scale, y2 - 6 * scale), 4 * scale, 4 * scale)
            if box.width() >= 14 * scale:  # skip labels on tiny far-away boxes
                self._pill(p, QPointF(x1, y1 - 2 * scale), o["label"],
                           QColor("#FACC15") if highlighted else color, scale, anchor_bottom=True,
                           text_color=QColor("#111827") if highlighted else QColor("#FFFFFF"))

    @staticmethod
    def _pill(p: QPainter, at: QPointF, text: str, bg: QColor, scale: float, anchor_bottom: bool = False,
              text_color: QColor = QColor("#FFFFFF")) -> None:
        if not text:
            return
        fm = p.fontMetrics()
        w, h = fm.horizontalAdvance(text) + 10 * scale, fm.height() + 2 * scale
        top = at.y() - h if anchor_bottom else at.y()
        rect = QRectF(at.x(), top, w, h)
        path = QPainterPath()
        path.addRoundedRect(rect, 3 * scale, 3 * scale)
        p.fillPath(path, bg)
        p.setPen(text_color)
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    def _draw_zoom_badge(self, painter: QPainter, base: QRectF) -> None:
        text = f"{self._zoom * 100:.0f}%   ·   drag to move   ·   double-click to reset"
        painter.setFont(QFont(theme.FONT_FAMILY, 9, QFont.Weight.DemiBold))
        fm = painter.fontMetrics()
        w, h = fm.horizontalAdvance(text) + 20, fm.height() + 10
        box = QRectF(base.right() - w - 12, base.top() + 12, w, h)
        path = QPainterPath()
        path.addRoundedRect(box, h / 2, h / 2)
        painter.fillPath(path, QColor(17, 20, 24, 200))
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)

    # ---------- zoom input ----------
    def wheelEvent(self, e):
        """Mouse wheel and touchpad (two-finger scroll / pinch, which Windows sends as
        Ctrl+wheel) zoom around the cursor."""
        if self._image is None or self._draw_mode:
            return
        delta = e.angleDelta().y() or e.pixelDelta().y()
        if delta:
            self.zoom_by(1.0015 ** delta, e.position())
        e.accept()

    def event(self, e):
        # native pinch gestures (precision touchpads / macOS)
        if e.type() == QEvent.Type.NativeGesture and e.gestureType() == Qt.NativeGestureType.ZoomNativeGesture:
            self.zoom_by(1.0 + e.value(), e.position())
            return True
        return super().event(e)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and not self._draw_mode:
            self.reset_zoom()

    # ---------- mouse ----------
    def mousePressEvent(self, e):
        if self._image is None:
            return
        if self._draw_mode:
            if e.button() == Qt.MouseButton.LeftButton:
                self._drag_start = self._drag_end = e.position()
            return
        if e.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton):
            self._press = e.position()
            self._panning = e.button() == Qt.MouseButton.MiddleButton and self._zoom > 1.0
            self._update_cursor()

    def mouseMoveEvent(self, e):
        if self._draw_mode:
            if self._drag_start is not None:
                self._drag_end = e.position()
                self.update()
            return
        if self._press is None or self._zoom <= 1.0:
            return
        delta = e.position() - self._press
        if not self._panning and abs(delta.x()) + abs(delta.y()) > 4:
            self._panning = True
            self._update_cursor()
        if self._panning:
            r = self._image_rect()
            self._fx -= delta.x() / r.width()
            self._fy -= delta.y() / r.height()
            self._clamp()
            self._press = e.position()
            self.update()

    def mouseReleaseEvent(self, e):
        if self._draw_mode:
            if self._drag_start is None:
                return
            start, end = self._to_norm(self._drag_start), self._to_norm(e.position())
            if abs(start[0] - end[0]) + abs(start[1] - end[1]) > 0.02:  # ignore tiny drags
                self.line_drawn.emit(start, end)
            self.set_draw_mode(False)
            return
        was_panning = self._panning
        self._press, self._panning = None, False
        self._update_cursor()
        if (not was_panning and e.button() == Qt.MouseButton.LeftButton
                and self._fit_rect().contains(e.position())):
            self.clicked.emit(*self._to_norm(e.position()))

    def keyPressEvent(self, e):
        if e.key() == Qt.Key.Key_Escape and self._draw_mode:
            self.set_draw_mode(False)
            self.line_drawn.emit((), ())  # signals cancel
        else:
            super().keyPressEvent(e)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._clamp()
