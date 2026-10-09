from dataclasses import dataclass
from pathlib import Path

import numpy as np
import supervision as sv
from ultralytics import YOLO


@dataclass
class TrackedObjects:
    """Vehicles found in one frame. All arrays share the same length N."""
    xyxy: np.ndarray        # (N, 4) float boxes
    confidence: np.ndarray  # (N,) float
    class_id: np.ndarray    # (N,) int, COCO ids
    track_id: np.ndarray    # (N,) int

    def __len__(self) -> int:
        return len(self.track_id)

    @classmethod
    def empty(cls) -> "TrackedObjects":
        return cls(np.empty((0, 4)), np.empty(0), np.empty(0, dtype=int), np.empty(0, dtype=int))


class VehicleDetector:
    """YOLO wrapper restricted to vehicle classes, with optional ByteTrack tracking."""

    def __init__(self, weights: str, classes: dict[int, str], device: str = "cpu",
                 imgsz: int = 640, conf: float = 0.35, iou: float = 0.5,
                 tracker_config: str | None = None, class_conf: dict[int, float] | None = None):
        # Ultralytics downloads the weights by name if the file doesn't exist yet
        weights_path = Path(weights)
        if not weights_path.exists():
            weights_path.parent.mkdir(parents=True, exist_ok=True)
            model = YOLO(weights_path.name)
            Path(model.ckpt_path).replace(weights_path)
        self.model = YOLO(str(weights_path))

        self.classes = classes
        self.class_ids = list(classes.keys())
        self.device = device
        self.imgsz = imgsz
        self.conf = conf
        self.iou = iou
        self.tracker_config = tracker_config or "bytetrack.yaml"
        # lower thresholds for hard classes (e.g. thin, partly hidden bicycles)
        self.class_conf = class_conf or {}
        self._tracker_ready = False

    def detect(self, frame: np.ndarray) -> sv.Detections:
        result = self.model.predict(
            frame, classes=self.class_ids, conf=self.conf, iou=self.iou,
            imgsz=self.imgsz, device=self.device, verbose=False,
        )[0]
        detections = sv.Detections.from_ultralytics(result)
        detections.data["class_name"] = np.array(
            [self.classes[int(c)] for c in detections.class_id], dtype=object
        )
        return detections

    def reset_tracker(self) -> None:
        """Start fresh track IDs on the next call to track() (e.g. new video source)."""
        self._tracker_ready = False

    def _threshold(self, class_id: int) -> float:
        return min(self.conf, self.class_conf.get(class_id, self.conf))

    def track(self, frame: np.ndarray) -> TrackedObjects:
        floor = min([self.conf] + [self._threshold(c) for c in self.class_ids])
        result = self.model.track(
            frame, classes=self.class_ids, conf=floor, iou=self.iou,
            imgsz=self.imgsz, device=self.device, verbose=False, agnostic_nms=True,  # one box per object
            tracker=self.tracker_config, persist=self._tracker_ready,
        )[0]
        self._tracker_ready = True

        boxes = result.boxes
        if boxes is None or boxes.id is None or len(boxes) == 0:
            return TrackedObjects.empty()
        conf = boxes.conf.cpu().numpy()
        cls = boxes.cls.cpu().numpy().astype(int)
        keep = np.array([c >= self._threshold(k) for c, k in zip(conf, cls)], dtype=bool)
        return TrackedObjects(
            xyxy=boxes.xyxy.cpu().numpy()[keep],
            confidence=conf[keep],
            class_id=cls[keep],
            track_id=boxes.id.cpu().numpy().astype(int)[keep],
        )

    def label(self, class_id: int) -> str:
        return self.classes.get(int(class_id), "Unknown")
