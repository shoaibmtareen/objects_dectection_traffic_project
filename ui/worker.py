import queue
import time

import cv2
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

from core.pipeline import Pipeline
from core.video_source import VideoSource


class ProcessingWorker(QThread):
    """Runs the vision pipeline off the UI thread.

    The UI never touches the pipeline directly while a session runs; it sends
    commands through a queue that the worker applies between frames.
    For video files the worker pauses on the last frame instead of finishing,
    so the user can still seek back and review; Stop ends the session.
    """

    session_started = Signal(int, dict)   # session_id, source info
    frame_ready = Signal(object, QImage)  # FrameResult, rendered frame
    playback_ended = Signal()             # reached the end of a video file (now paused)
    session_finished = Signal(int, bool)  # session_id, reached end of source
    error = Signal(str)

    def __init__(self, pipeline: Pipeline, max_width: int):
        super().__init__()
        self.pipeline = pipeline
        self.max_width = max_width
        self.source = None
        self.label = ""
        self.realtime = True
        self.skip = 0  # extra frames dropped after each processed frame (speed 2x -> 1, 4x -> 3)
        self._commands: queue.Queue = queue.Queue()
        self._paused = False
        self._stop = False
        self._at_end = False

    # ---------- control from UI thread ----------
    def configure(self, source, label: str) -> None:
        self.source, self.label = source, label
        self._paused = self._stop = self._at_end = False
        while not self._commands.empty():
            self._commands.get_nowait()

    def pause(self, paused: bool) -> None:
        self._paused = paused

    def stop(self) -> None:
        self._stop = True

    @property
    def paused(self) -> bool:
        return self._paused

    def send(self, name: str, *args) -> None:
        """Queue a command: conf, line, highlight, trails, record, stop_record, seek, step, speed."""
        self._commands.put((name, args))

    # ---------- worker thread ----------
    def _apply_commands(self, src: VideoSource) -> bool:
        """Apply queued commands. Returns True when one frame should be processed now
        even if paused (after a seek or a single-step request)."""
        show_one = False
        while not self._commands.empty():
            name, args = self._commands.get_nowait()
            p = self.pipeline
            if name == "conf":
                p.set_confidence(*args)
            elif name == "line":
                p.set_line(*args)
            elif name == "highlight":
                p.annotator.highlight_id = args[0]
            elif name == "show_line":
                p.annotator.show_line = args[0]
            elif name == "trails":
                p.annotator.show_trails = args[0]
            elif name == "record":
                p.start_recording(args[0], src.fps, (src.width, src.height))
            elif name == "stop_record":
                p.stop_recording()
            elif name == "speed":
                self.skip = max(0, int(args[0]) - 1)
            elif name == "seek":
                src.seek(int(args[0]))
                p.on_seek()
                self._at_end = False
                show_one = True
            elif name == "step":
                show_one = not self._at_end
        return show_one

    def _process_one(self, src: VideoSource) -> bool:
        ok, frame = src.read()
        if not ok:
            return False
        result = self.pipeline.process(frame, src.timestamp, src.frame_index, src.progress)
        rgb = cv2.cvtColor(result.frame, cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        image = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
        self.frame_ready.emit(result, image)
        return True

    def run(self) -> None:
        try:
            src = VideoSource(self.source, self.max_width)
        except Exception as exc:  # noqa: BLE001 - surface any open error to the UI
            self.error.emit(str(exc))
            return

        session_id = self.pipeline.start_session(self.label)
        self.session_started.emit(session_id, {
            "fps": src.fps, "width": src.width, "height": src.height,
            "is_live": src.is_live, "total_frames": src.total_frames,
        })
        frame_period = 1.0 / src.fps
        try:
            while not self._stop:
                show_one = self._apply_commands(src)
                if (self._paused or self._at_end) and not show_one:
                    self.msleep(30)
                    continue
                t0 = time.perf_counter()
                if not self._process_one(src):
                    if src.is_live:
                        break  # camera/stream disconnected
                    self._at_end = True
                    self._paused = True
                    self.playback_ended.emit()
                    continue
                if show_one:
                    continue  # a seek/step while paused shows exactly one frame
                if self.skip:
                    src.skip(self.skip)

                # don't play files faster than the chosen speed (matters on fast GPUs)
                if self.realtime and not src.is_live:
                    remaining = frame_period * (self.skip + 1) - (time.perf_counter() - t0)
                    if remaining > 0:
                        time.sleep(remaining)
        except Exception as exc:  # noqa: BLE001
            self.error.emit(f"Processing error: {exc}")
        finally:
            self.pipeline.end_session()
            src.release()
            self.session_finished.emit(session_id, self._at_end)
