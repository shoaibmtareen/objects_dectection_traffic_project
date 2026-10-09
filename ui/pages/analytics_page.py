from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMessageBox, QPushButton, QVBoxLayout, QWidget

from core.pipeline import FrameResult, Pipeline
from storage.database import Database
from ui.widgets.common import icon, top_bar
from ui.widgets.control_bar import ControlBar
from ui.widgets.stats_panels import CurrentFramePanel, TotalsPanel
from ui.widgets.video_view import VideoView
from ui.worker import ProcessingWorker
from utils.helpers import PROJECT_ROOT, format_seconds


class AnalyticsPage(QWidget):
    """Live view: video on the left, current-frame and session totals on the right."""

    back_requested = Signal()
    # None, ("select", (session_id, track_id)) or ("type", class_name)
    records_requested = Signal(object)
    status_message = Signal(str, int)   # text, timeout ms

    def __init__(self, settings: dict, db: Database, pipeline: Pipeline, parent=None):
        super().__init__(parent)
        self.setObjectName("Page")
        self.settings = settings
        self.db = db
        self.pipeline = pipeline
        self.colors: dict[str, str] = settings["colors"]
        self.worker = ProcessingWorker(pipeline, settings["processing"]["max_width"])

        self.state = "idle"
        self.session_id: int | None = None
        self.source_info: dict = {}
        self._kind = ""
        self._source_name = ""
        self.last_result: FrameResult | None = None
        self.live_keys: set[tuple[int, int]] = set()
        self.selected_id: int | None = None
        self.at_end = False

        self._build_ui()
        self._connect()
        self._set_state("idle")

    # ================================================================== UI
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        bar, bl = top_bar()
        self.back_btn = QPushButton("  New analysis")
        self.back_btn.setIcon(icon("back", "#FFFFFF"))
        self.back_btn.setToolTip("Stop and choose another source")
        bl.addWidget(self.back_btn)
        bl.addSpacing(10)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        self.source_title = QLabel("")
        self.source_title.setObjectName("BrandTitle")
        self.source_meta = QLabel("")
        self.source_meta.setObjectName("TopMeta")
        titles.addStretch()
        titles.addWidget(self.source_title)
        titles.addWidget(self.source_meta)
        titles.addStretch()
        bl.addLayout(titles)
        bl.addStretch()
        self.records_btn = QPushButton("  Records && search")
        self.records_btn.setIcon(icon("records", "#FFFFFF"))
        self.records_btn.setToolTip("Search every object by ID or type (Ctrl+F)")
        bl.addWidget(self.records_btn)
        bl.addSpacing(6)
        self.status_pill = QLabel("IDLE")
        self.status_pill.setObjectName("StatusPill")
        bl.addWidget(self.status_pill, 0, Qt.AlignmentFlag.AlignVCenter)
        self.top = bar
        root.addWidget(bar)

        body = QHBoxLayout()
        body.setContentsMargins(16, 16, 16, 12)
        body.setSpacing(14)
        root.addLayout(body, 1)

        left = QVBoxLayout()
        left.setSpacing(12)
        self.video = VideoView()
        self.video.colors = self.colors
        left.addWidget(self.video, 1)
        self.controls = ControlBar()
        self.controls.set_conf(self.settings["model"]["conf"])
        left.addWidget(self.controls)
        show_line = bool(self.settings["counting"].get("show_line", False))
        body.addLayout(left, 1)

        right = QVBoxLayout()
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(14)
        non_vehicle = self.settings["counting"].get("non_vehicle_classes", [])
        self.frame_panel = CurrentFramePanel(self.colors, non_vehicle)
        self.totals_panel = TotalsPanel(self.colors, non_vehicle)
        right.addWidget(self.frame_panel, 1)
        right.addWidget(self.totals_panel, 1)
        self.side = QWidget()
        self.side.setLayout(right)
        self.side.setFixedWidth(430)
        body.addWidget(self.side)
        self.controls.line_box.setChecked(show_line)
        self.video.show_line = show_line
        self.controls.reset_line_btn.setVisible(show_line)
        self.totals_panel.line_strip.setVisible(show_line)

    def _connect(self) -> None:
        self.back_btn.clicked.connect(self._on_back)
        self.records_btn.clicked.connect(lambda: self.records_requested.emit(None))
        self.frame_panel.details_requested.connect(
            lambda: self.records_requested.emit(("select", (self.session_id, self.selected_id))))
        for panel in (self.frame_panel, self.totals_panel):
            panel.class_clicked.connect(lambda name: self.records_requested.emit(("type", name)))

        c = self.controls
        c.play_pause_clicked.connect(self.toggle_play)
        c.restart_clicked.connect(lambda: self.seek_frame(0))
        c.jump_requested.connect(self.jump)
        c.step_clicked.connect(self.step)
        c.seek_requested.connect(self.seek_frame)
        c.speed_changed.connect(lambda n: self.running and self.worker.send("speed", n))
        c.stop_clicked.connect(self.stop)
        c.conf_changed.connect(lambda v: self._command("conf", v, self.pipeline.set_confidence))
        c.draw_line_toggled.connect(self.video.set_draw_mode)
        c.reset_line_clicked.connect(self.on_reset_line)
        c.line_toggled.connect(self.set_line_visible)
        c.draw_line_toggled.connect(lambda on: on and c.line_box.setChecked(True))
        c.trails_toggled.connect(
            lambda on: self._command("trails", on, lambda v: setattr(self.pipeline.annotator, "show_trails", v)))
        c.screenshot_clicked.connect(self.screenshot)
        c.record_toggled.connect(self.on_record)
        c.focus_toggled.connect(self.set_focus_mode)

        self.video.line_drawn.connect(self.on_line_drawn)
        self.video.clicked.connect(self.on_video_clicked)

        self.worker.session_started.connect(self.on_session_started)
        self.worker.frame_ready.connect(self.on_frame)
        self.worker.playback_ended.connect(self.on_playback_ended)
        self.worker.session_finished.connect(self.on_session_finished)
        self.worker.error.connect(self.on_error)

        # keyboard shortcuts (active while this page is shown)
        for keys, slot in (("Space", self.toggle_play), ("Left", lambda: self.jump(-5)),
                           ("Right", lambda: self.jump(5)), (".", self.step), ("Home", lambda: self.seek_frame(0)),
                           ("S", self.screenshot), ("F", self.controls.focus_btn.toggle),
                           ("+", lambda: self.video.zoom_by(1.25)), ("=", lambda: self.video.zoom_by(1.25)),
                           ("-", lambda: self.video.zoom_by(0.8)), ("0", self.video.reset_zoom)):
            sc = QShortcut(QKeySequence(keys), self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(slot)

    # ================================================================ state
    def _set_state(self, state: str) -> None:
        self.state = state
        labels = {"idle": "IDLE", "live": "● LIVE", "paused": "PAUSED", "completed": "END OF VIDEO",
                  "stopped": "STOPPED", "error": "ERROR", "loading": "CONNECTING…"}
        self.status_pill.setText(labels.get(state, state.upper()))
        self.status_pill.setProperty("state", "completed" if state == "stopped" else state)
        self.status_pill.style().unpolish(self.status_pill)
        self.status_pill.style().polish(self.status_pill)
        self.controls.set_running(state in ("live", "paused", "loading", "completed"))
        self.controls.set_playing(state == "live")
        self.frame_panel.set_status(state)

    @property
    def running(self) -> bool:
        return self.worker.isRunning()

    def _command(self, name: str, value, direct) -> None:
        """Send a setting to the worker while running, else apply it to the pipeline directly."""
        if self.running:
            self.worker.send(name, value)
        else:
            direct(value)

    # ============================================================ public API
    def start(self, config: dict) -> None:
        """Begin analysing `config["source"]` (called from the source page)."""
        self.stop(wait=True)
        self._source_name = str(config["label"]).replace("\\", "/").split("/")[-1]
        self.source_title.setText(self._source_name)
        self._kind = {"file": "Video file", "camera": "Local camera",
                      "ip": "IP camera stream"}.get(config.get("kind"), "")
        self.source_meta.setText(self._kind)
        self.controls.set_conf(config["conf"])
        self.controls.speed.setCurrentIndex(0)
        self.frame_panel.reset()
        self.totals_panel.reset()
        self.selected_id = None
        self.last_result = None
        self.at_end = False
        self.worker.skip = 0
        self.worker.configure(config["source"], config["label"])
        self.video.clear()
        self.video.placeholder = "Connecting to source…"
        self._set_state("loading")
        self.worker.start()

    def stop(self, wait: bool = False) -> None:
        if self.running:
            self.worker.stop()
            if wait:
                self.worker.wait(5000)

    def highlight(self, track_id: int | None) -> None:
        """Mark an object in the video (also used by the records page)."""
        self.selected_id = track_id
        if self.running:
            self.worker.send("highlight", track_id)
        self._update_selected_text()

    def _on_back(self) -> None:
        if self.running:
            answer = QMessageBox.question(
                self, "Stop analysis",
                "The analysis is still running. Stop it and choose a new source?\n\n"
                "Everything detected so far is saved.")
            if answer != QMessageBox.StandardButton.Yes:
                return
            self.stop(wait=True)
        self.back_requested.emit()

    # ============================================================ playback
    def toggle_play(self) -> None:
        if not self.running or self.state == "loading":
            return
        if self.at_end:  # play again from the start
            self.seek_frame(0)
            self.worker.pause(False)
            self._set_state("live")
            return
        paused = not self.worker.paused
        self.worker.pause(paused)
        self._set_state("paused" if paused else "live")

    def seek_frame(self, frame: int) -> None:
        if not self.running or not self.source_info.get("total_frames"):
            return
        self.worker.send("seek", frame)
        if self.at_end:
            self.at_end = False
            self._set_state("paused")

    def jump(self, seconds: float) -> None:
        if self.last_result is None:
            return
        fps = self.source_info.get("fps", 25.0)
        self.seek_frame(int(self.last_result.frame_index + seconds * fps))

    def step(self) -> None:
        if not self.running or self.at_end:
            return
        if not self.worker.paused:
            self.worker.pause(True)
            self._set_state("paused")
        self.worker.send("step")

    def screenshot(self) -> None:
        image = self.video.current_image()
        if image is None:
            self.status_message.emit("Nothing to capture yet", 3000)
            return
        out_dir = PROJECT_ROOT / "data" / "screenshots"
        out_dir.mkdir(parents=True, exist_ok=True)
        t = format_seconds(self.last_result.timestamp).replace(":", "-") if self.last_result else "frame"
        stem = Path(self._source_name).stem or "capture"
        path = out_dir / f"{stem}_S{self.session_id}_{t}_{datetime.now():%H%M%S}.png"
        image.save(str(path))
        QGuiApplication.clipboard().setImage(image)
        self.status_message.emit(f"Screenshot saved to {path} (also copied to the clipboard)", 6000)

    def set_line_visible(self, on: bool) -> None:
        """Counting line + its IN / OUT numbers: shown only when wanted."""
        self._command("show_line", on, lambda v: setattr(self.pipeline.annotator, "show_line", v))
        self.totals_panel.line_strip.setVisible(on)
        self.video.show_line = on
        self.video.update()

    def set_focus_mode(self, on: bool) -> None:
        """Bigger video: hide the side panels and the top bar."""
        self.side.setHidden(on)
        self.top.setHidden(on)
        if on:
            self.status_message.emit("Focus mode — press F to show the panels again", 4000)

    # ============================================================ controls
    def on_line_drawn(self, start: tuple, end: tuple) -> None:
        self.controls.draw_btn.blockSignals(True)
        self.controls.draw_btn.setChecked(False)
        self.controls.draw_btn.blockSignals(False)
        if start:
            self._apply_line(start, end)
            self.status_message.emit("Counting line updated", 3000)

    def on_reset_line(self) -> None:
        c = self.settings["counting"]
        self._apply_line(tuple(c["line_start"]), tuple(c["line_end"]))
        self.status_message.emit("Counting line reset", 3000)

    def _apply_line(self, start, end) -> None:
        if self.running:
            self.worker.send("line", start, end)
        else:
            self.pipeline.set_line(start, end)

    def on_record(self, on: bool) -> None:
        if not self.running:
            return
        if on:
            out_dir = Path(self.settings["storage"]["recordings_dir"])
            path = out_dir / f"session_{self.session_id}_{datetime.now():%Y%m%d_%H%M%S}.mp4"
            self.worker.send("record", str(path))
            self.status_message.emit(f"Recording to {path}", 5000)
        else:
            self.worker.send("stop_record")
            self.status_message.emit("Recording saved", 4000)

    # ======================================================= worker signals
    def on_session_started(self, session_id: int, info: dict) -> None:
        self.session_id = session_id
        self.source_info = info
        self.live_keys = set()
        self.controls.set_source(info["fps"], info["total_frames"])
        self._set_state("live")
        self.source_meta.setText(f"{self._kind}  ·  {info['width']}×{info['height']} @ {info['fps']:.0f} fps"
                                 f"  ·  Session S{session_id}")

    def on_frame(self, result: FrameResult, image) -> None:
        self.last_result = result
        self.video.set_frame(image, result.overlay)
        self.frame_panel.update_from(result)
        self.totals_panel.update_from(result, f"⏱ {format_seconds(result.timestamp)}")
        self.controls.set_position(result.frame_index, result.timestamp)

        self.live_keys = {(self.session_id, tid) for tid in result.in_frame_ids}
        if self.selected_id is not None:
            self._update_selected_text()
        if result.crossings:
            tid, direction, vtype = result.crossings[-1]
            self.status_message.emit(
                f"{vtype} #{tid} crossed the line ({direction}) at {format_seconds(result.timestamp)}", 3000)

    def on_playback_ended(self) -> None:
        self.at_end = True
        self._set_state("completed")
        n = self.last_result.tracked if self.last_result else 0
        self.status_message.emit(f"End of video — {n:,} objects detected. Drag the timeline to review, "
                                 "press Play to watch again, or Stop to finish.", 10000)

    def on_session_finished(self, session_id: int, reached_end: bool) -> None:
        self.live_keys = set()
        self.at_end = False
        self.frame_panel.update_counts({})  # nothing is in view once the source stops
        self._set_state("stopped")
        n = self.last_result.tracked if self.last_result else 0
        self.status_message.emit(f"Session S{session_id} finished — {n:,} objects detected and saved", 8000)
        self._update_selected_text()

    def on_error(self, message: str) -> None:
        self._set_state("error")
        self.video.placeholder = "Could not open the source"
        self.video.update()
        QMessageBox.critical(self, "Source error",
                             f"{message}\n\nCheck the file, camera or stream URL and try again.")

    # ============================================================ selection
    def on_video_clicked(self, x: float, y: float) -> None:
        r = self.last_result
        if r is None:
            return
        hits = [(abs((x2 - x1) * (y2 - y1)), tid) for tid, x1, y1, x2, y2 in r.in_frame_boxes
                if x1 <= x <= x2 and y1 <= y <= y2]
        self.highlight(min(hits)[1] if hits else None)

    def _update_selected_text(self) -> None:
        tid = self.selected_id
        if tid is None or self.session_id is None:
            self.frame_panel.show_selected(None)
            return
        rec = self.pipeline.registry.records.get(tid)
        if rec is not None:
            live = (self.session_id, tid) in self.live_keys
            where = "in view" if live else "left the scene"
            text = (f"<b>Selected:</b> {rec.vehicle_type} #{tid}  ·  {rec.best_conf:.0%}  ·  "
                    f"{where}  ·  {rec.last_seen - rec.first_seen:.1f} s")
        else:
            text = f"<b>Selected:</b> #{tid}"
        self.frame_panel.show_selected(text)
