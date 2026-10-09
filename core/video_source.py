import sys
import time

import cv2
import numpy as np

# DirectShow opens USB/built-in cameras much faster than the default backend on Windows
CAMERA_BACKEND = cv2.CAP_DSHOW if sys.platform == "win32" else cv2.CAP_ANY


def list_cameras(max_index: int = 5) -> list[tuple[int, str]]:
    """Probe camera indices and return [(index, "Camera 0 · 1280×720")] for working ones."""
    found = []
    cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)  # empty indices warn otherwise
    for idx in range(max_index):
        cap = cv2.VideoCapture(idx, CAMERA_BACKEND)
        if cap.isOpened():
            ok, frame = cap.read()
            if ok and frame is not None:
                h, w = frame.shape[:2]
                found.append((idx, f"Camera {idx}  ·  {w}×{h}"))
        cap.release()
    return found


class VideoSource:
    """Reads frames from a video file, webcam index or stream URL (RTSP/HTTP).

    Frames wider than `max_width` are downscaled so processing speed does not
    depend on the camera resolution.
    """

    def __init__(self, source: str | int, max_width: int = 1280):
        if isinstance(source, str) and source.strip().isdigit():
            source = int(source)
        self.source = source
        self.is_live = not isinstance(source, str) or source.lower().startswith(("rtsp://", "http://", "https://"))
        self.cap = (cv2.VideoCapture(source, CAMERA_BACKEND) if isinstance(source, int)
                    else cv2.VideoCapture(source))
        if not self.cap.isOpened():
            raise IOError(f"Could not open video source: {source}")

        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 25.0
        if self.fps > 240 or self.fps < 1:
            self.fps = 25.0
        self.total_frames = 0 if self.is_live else int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        src_w = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        src_h = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.scale = min(1.0, max_width / src_w) if src_w else 1.0
        self.width = int(src_w * self.scale)
        self.height = int(src_h * self.scale)
        self.frame_index = -1
        self._start = time.perf_counter()

    def read(self) -> tuple[bool, np.ndarray | None]:
        ok, frame = self.cap.read()
        if not ok:
            return False, None
        self.frame_index += 1
        if self.scale < 1.0:
            frame = cv2.resize(frame, (self.width, self.height), interpolation=cv2.INTER_AREA)
        return True, frame

    def skip(self, n: int) -> None:
        """Discard the next n frames quickly (used for 2x / 4x processing speed)."""
        for _ in range(n):
            if not self.cap.grab():
                break
            self.frame_index += 1

    def seek(self, frame: int) -> None:
        """Jump to a frame number (files only). The next read() returns that frame."""
        if self.is_live:
            return
        frame = max(0, min(frame, max(0, self.total_frames - 1)))
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame)
        self.frame_index = frame - 1

    @property
    def timestamp(self) -> float:
        """Seconds since the start: video time for files, wall time for live sources."""
        if self.is_live:
            return time.perf_counter() - self._start
        return self.frame_index / self.fps

    @property
    def progress(self) -> float:
        if not self.total_frames:
            return 0.0
        return min(1.0, (self.frame_index + 1) / self.total_frames)

    def release(self) -> None:
        self.cap.release()
