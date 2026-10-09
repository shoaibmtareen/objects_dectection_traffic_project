from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QPushButton, QSlider,
                               QStyle, QStyleOptionSlider, QVBoxLayout)

from ui import theme
from ui.widgets.common import icon
from utils.helpers import format_seconds


class TimelineSlider(QSlider):
    """Horizontal slider that jumps straight to the clicked position."""

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            opt = QStyleOptionSlider()
            self.initStyleOption(opt)
            groove = self.style().subControlRect(QStyle.ComplexControl.CC_Slider, opt,
                                                 QStyle.SubControl.SC_SliderGroove, self)
            value = QStyle.sliderValueFromPosition(self.minimum(), self.maximum(),
                                                   int(event.position().x()) - groove.x(), groove.width())
            self.setValue(value)
        super().mousePressEvent(event)


def _tool(icon_name: str, tip: str) -> QPushButton:
    b = QPushButton()
    b.setObjectName("ToolButton")
    b.setIcon(icon(icon_name, theme.TEXT, 18))
    b.setIconSize(QSize(18, 18))
    b.setFixedSize(38, 36)
    b.setToolTip(tip)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    return b


def _action(icon_name: str, text: str, tip: str) -> QPushButton:
    b = QPushButton(f"  {text}")
    b.setIcon(icon(icon_name, theme.TEXT, 16))
    b.setToolTip(tip)
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    return b


class ControlBar(QFrame):
    """Media-player style controls: timeline, transport, speed, tools."""

    play_pause_clicked = Signal()
    restart_clicked = Signal()
    jump_requested = Signal(float)      # seconds (+/-)
    step_clicked = Signal()
    seek_requested = Signal(int)        # frame number
    speed_changed = Signal(int)         # 1, 2 or 4
    stop_clicked = Signal()
    conf_changed = Signal(float)
    draw_line_toggled = Signal(bool)
    reset_line_clicked = Signal()
    trails_toggled = Signal(bool)
    line_toggled = Signal(bool)
    screenshot_clicked = Signal()
    record_toggled = Signal(bool)
    focus_toggled = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        self.fps = 25.0
        self.total_frames = 0
        outer = QVBoxLayout(self)
        outer.setContentsMargins(14, 10, 14, 10)
        outer.setSpacing(8)

        # ---- row 1: transport + timeline ----
        r1 = QHBoxLayout()
        r1.setSpacing(6)
        self.restart_btn = _tool("restart", "Restart from the beginning (Home)")
        self.back_btn = _tool("rewind", "Back 5 seconds (←)")
        self.play_btn = QPushButton()
        self.play_btn.setObjectName("PlayButton")
        self.play_btn.setFixedSize(52, 38)
        self.play_btn.setIconSize(QSize(18, 18))
        self.play_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.play_btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.fwd_btn = _tool("forward", "Forward 5 seconds (→)")
        self.step_btn = _tool("step", "Next frame — while paused (.)")
        for b in (self.restart_btn, self.back_btn, self.play_btn, self.fwd_btn, self.step_btn):
            r1.addWidget(b)
        r1.addSpacing(8)
        self.time_now = QLabel("00:00")
        self.time_now.setStyleSheet(f"color:{theme.TEXT}; font-weight:700; font-size:12px;")
        self.time_now.setMinimumWidth(44)
        r1.addWidget(self.time_now)
        self.timeline = TimelineSlider(Qt.Orientation.Horizontal)
        self.timeline.setObjectName("Timeline")
        self.timeline.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.timeline.setCursor(Qt.CursorShape.PointingHandCursor)
        r1.addWidget(self.timeline, 1)
        self.time_total = QLabel("00:00")
        self.time_total.setStyleSheet(f"color:{theme.MUTED}; font-size:12px;")
        self.time_total.setMinimumWidth(44)
        r1.addWidget(self.time_total)
        r1.addSpacing(8)
        self.speed = QComboBox()
        self.speed.addItem("1×", 1)
        self.speed.addItem("2×", 2)
        self.speed.addItem("4×", 4)
        self.speed.setToolTip("Processing speed — 2× / 4× analyse every 2nd / 4th frame")
        self.speed.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.speed.setFixedWidth(70)
        r1.addWidget(self.speed)
        outer.addLayout(r1)

        # ---- row 2: detection + tools ----
        r2 = QHBoxLayout()
        r2.setSpacing(8)
        lbl = QLabel("Confidence")
        lbl.setStyleSheet(f"color:{theme.MUTED}; font-weight:600;")
        r2.addWidget(lbl)
        self.conf_slider = QSlider(Qt.Orientation.Horizontal)
        self.conf_slider.setRange(10, 90)
        self.conf_slider.setFixedWidth(110)
        self.conf_slider.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        r2.addWidget(self.conf_slider)
        self.conf_value = QLabel()
        self.conf_value.setMinimumWidth(32)
        self.conf_value.setStyleSheet(f"color:{theme.TEXT}; font-weight:700;")
        r2.addWidget(self.conf_value)
        r2.addStretch()

        self.draw_btn = _action("line", "Draw line", "Drag on the video to set the counting line")
        self.draw_btn.setCheckable(True)
        self.reset_line_btn = _action("restart", "Reset line", "Put the counting line back to the default")
        self.line_box = QCheckBox("Line")
        self.line_box.setToolTip("Show the counting line (counts vehicles crossing it, IN / OUT)")
        self.line_box.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.trails_box = QCheckBox("Trails")
        self.trails_box.setChecked(False)
        self.trails_box.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.shot_btn = _action("screenshot", "Screenshot", "Save the current frame as an image (S)")
        self.record_btn = _action("record", "Record", "Save the annotated video to data/recordings")
        self.record_btn.setObjectName("Record")
        self.record_btn.setCheckable(True)
        self.focus_btn = _tool("expand", "Focus mode — bigger video (F)")
        self.focus_btn.setCheckable(True)
        self.stop_btn = _action("stop", "Stop", "Stop the analysis (results are saved)")
        self.stop_btn.setObjectName("Danger")
        for w in (self.line_box, self.draw_btn, self.reset_line_btn, self.trails_box, self.shot_btn,
                  self.record_btn, self.focus_btn, self.stop_btn):
            r2.addWidget(w)
        outer.addLayout(r2)

        # ---- wiring ----
        self.play_btn.clicked.connect(self.play_pause_clicked)
        self.restart_btn.clicked.connect(self.restart_clicked)
        self.back_btn.clicked.connect(lambda: self.jump_requested.emit(-5.0))
        self.fwd_btn.clicked.connect(lambda: self.jump_requested.emit(5.0))
        self.step_btn.clicked.connect(self.step_clicked)
        self.timeline.sliderMoved.connect(lambda v: self.time_now.setText(format_seconds(v / self.fps)))
        self.timeline.sliderReleased.connect(lambda: self.seek_requested.emit(self.timeline.value()))
        self.timeline.actionTriggered.connect(self._on_timeline_action)
        self.speed.currentIndexChanged.connect(lambda _: self.speed_changed.emit(self.speed.currentData()))
        self.stop_btn.clicked.connect(self.stop_clicked)
        self.conf_slider.valueChanged.connect(self._on_conf)
        self.draw_btn.toggled.connect(self.draw_line_toggled)
        self.reset_line_btn.clicked.connect(self.reset_line_clicked)
        self.trails_box.toggled.connect(self.trails_toggled)
        self.line_box.toggled.connect(self._on_line_box)
        self.shot_btn.clicked.connect(self.screenshot_clicked)
        self.record_btn.toggled.connect(self.record_toggled)
        self.focus_btn.toggled.connect(self._on_focus)

        self.set_conf(0.3)
        self.set_playing(False)
        self.set_running(False)
        self.set_source(25.0, 0)

    # ------------------------------------------------------------ setters
    def _on_timeline_action(self, action) -> None:
        # page-step clicks on the groove (not drags) seek immediately
        if not self.timeline.isSliderDown() and action in (QSlider.SliderAction.SliderPageStepAdd,
                                                           QSlider.SliderAction.SliderPageStepSub):
            self.seek_requested.emit(self.timeline.sliderPosition())

    def set_source(self, fps: float, total_frames: int) -> None:
        """Configure the timeline: total_frames == 0 means a live source (no seeking)."""
        self.fps, self.total_frames = fps or 25.0, total_frames
        seekable = total_frames > 0
        self.timeline.setRange(0, max(0, total_frames - 1))
        self.timeline.setPageStep(max(1, int(self.fps * 5)))
        self.time_total.setText(format_seconds(total_frames / self.fps) if seekable else "LIVE")
        for w in (self.timeline, self.restart_btn, self.back_btn, self.fwd_btn, self.speed):
            w.setVisible(seekable)

    def set_position(self, frame: int, seconds: float) -> None:
        if not self.timeline.isSliderDown():
            self.timeline.blockSignals(True)
            self.timeline.setValue(frame)
            self.timeline.blockSignals(False)
            self.time_now.setText(format_seconds(seconds))

    def set_conf(self, conf: float) -> None:
        self.conf_slider.blockSignals(True)
        self.conf_slider.setValue(int(conf * 100))
        self.conf_slider.blockSignals(False)
        self.conf_value.setText(f"{conf:.2f}")

    def set_playing(self, playing: bool) -> None:
        self.play_btn.setIcon(icon("pause" if playing else "play", "#FFFFFF", 18))
        self.play_btn.setToolTip("Pause (Space)" if playing else "Play (Space)")

    def _on_line_box(self, on: bool) -> None:
        self.reset_line_btn.setVisible(on)
        self.line_toggled.emit(on)

    def _on_conf(self, v: int) -> None:
        self.conf_value.setText(f"{v / 100:.2f}")
        self.conf_changed.emit(v / 100)

    def _on_focus(self, on: bool) -> None:
        self.focus_btn.setIcon(icon("shrink" if on else "expand", theme.TEXT, 18))
        self.focus_btn.setToolTip("Exit focus mode (F)" if on else "Focus mode — bigger video (F)")
        self.focus_toggled.emit(on)

    def set_running(self, running: bool) -> None:
        for w in (self.play_btn, self.restart_btn, self.back_btn, self.fwd_btn, self.step_btn,
                  self.timeline, self.speed, self.stop_btn, self.record_btn):
            w.setEnabled(running)
        if not running:
            self.record_btn.blockSignals(True)
            self.record_btn.setChecked(False)
            self.record_btn.blockSignals(False)
            self.set_playing(False)
