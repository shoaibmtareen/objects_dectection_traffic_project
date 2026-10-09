from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from core.detector import TrackedObjects


@dataclass
class VehicleRecord:
    track_id: int
    first_seen: float
    first_frame: int
    last_seen: float = 0.0
    last_frame: int = 0
    frames_seen: int = 0
    best_conf: float = 0.0
    class_votes: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    direction: str | None = None
    counted: bool = False
    crossed_at: float | None = None
    snapshot_path: str | None = None
    registered: bool = False
    dirty: bool = True
    bbox: tuple[float, float, float, float] = (0, 0, 0, 0)
    trail: deque = field(default_factory=lambda: deque(maxlen=30))
    # best crop waiting to be written to disk
    _crop: np.ndarray | None = None
    _crop_score: float = 0.0
    _crop_saved_score: float = 0.0
    # second-stage (CLIP) checks of the best crop
    clip_probs: dict[str, float] = field(default_factory=lambda: defaultdict(float))  # size-weighted sums
    clip_weight: float = 0.0
    clip_checks: int = 0
    clip_crop_score: float = 0.0   # crop score at the last check
    clip_min_prob: float = 0.6
    # motion: recent (time, x, y, box height) and the fastest speed seen, in box-heights per second
    motion: deque = field(default_factory=lambda: deque(maxlen=60))
    max_speed: float = 0.0
    merged: bool = False  # a rider whose motorcycle/bicycle has its own track: not counted separately

    @property
    def yolo_type(self) -> str:
        if not self.class_votes:
            return "Unknown"
        return max(self.class_votes.items(), key=lambda kv: kv[1])[0]

    def clip_avg(self) -> dict[str, float]:
        """Size-weighted average CLIP probabilities (bigger, closer views count more)."""
        if not self.clip_weight:
            return {}
        return {k: v / self.clip_weight for k, v in self.clip_probs.items()}

    @property
    def observed_still(self) -> bool:
        """Watched for 1.5 s+ and never moved: parked / standing."""
        return bool(self.motion) and self.motion[-1][0] - self.motion[0][0] >= 1.5 and self.max_speed < 0.5

    @property
    def vehicle_type(self) -> str:
        """CLIP's verdict when it clearly wins, otherwise YOLO's vote."""
        avg = self.clip_avg()
        if avg and self.yolo_type == "Person":
            # rider whose bike YOLO missed: CLIP says riding, and it moves (or is not seen standing still)
            for label in ("Motorcycle", "Bicycle"):
                p = avg.get(label, 0.0)
                if ((p >= 0.6 and self.max_speed >= 0.5) or (p >= 0.8 and not self.observed_still)
                        or p >= 0.97):
                    return label
            # faster than any pedestrian (walking ~1, running ~3 body-heights/s): riding something
            if self.max_speed >= 3.0:
                ride = max(("Motorcycle", "Bicycle"), key=lambda k: avg.get(k, 0.0))
                if avg.get(ride, 0.0) >= 0.3:
                    return ride
            return "Person"
        if avg:
            from core.classifier import CANDIDATES  # only labels that make sense for YOLO's class
            allowed = CANDIDATES.get(self.yolo_type, set()) | {self.yolo_type}
            avg = {k: v for k, v in avg.items() if k in allowed}
            if not avg:
                return self.yolo_type
            ranked = sorted(avg.items(), key=lambda kv: -kv[1])
            top, p1 = ranked[0]
            p2 = ranked[1][1] if len(ranked) > 1 else 0.0
            if top == self.yolo_type:
                return top
            # override YOLO only with a clear winner. The relaxed margin rule is only for
            # labels YOLO cannot produce (Rickshaw, not-a-vehicle); car <-> truck <-> bus swaps
            # and two-wheeler changes need real confidence.
            clear = p1 >= self.clip_min_prob
            if top in ("Rickshaw", "Other") and self.yolo_type not in ("Motorcycle", "Bicycle"):
                clear = clear or (p1 >= 0.45 and p1 - p2 >= 0.15)
            if clear and p1 - p2 >= 0.1:
                return top
        return self.yolo_type

    def add_clip_result(self, probs: dict[str, float], weight: float = 1.0) -> None:
        for label, p in probs.items():
            self.clip_probs[label] += p * weight
        self.clip_weight += weight
        self.clip_checks += 1
        self.clip_crop_score = self._crop_score
        self.dirty = True

    def to_row(self) -> dict:
        return {
            "track_id": self.track_id,
            "vehicle_type": self.vehicle_type,
            "confidence": round(self.best_conf, 3),
            "first_seen": round(self.first_seen, 2),
            "last_seen": round(self.last_seen, 2),
            "frames_seen": self.frames_seen,
            "direction": self.direction,
            "counted": int(self.counted),
            "crossed_at": None if self.crossed_at is None else round(self.crossed_at, 2),
            "snapshot_path": self.snapshot_path,
        }


class VehicleRegistry:
    """Keeps one record per track ID: stable type, timing, best snapshot, trail."""

    def __init__(self, class_names: dict[int, str], snapshots_dir: str,
                 min_hits: int = 5, trail_length: int = 30, stale_frames: int = 90):
        self.class_names = class_names
        self.snapshots_root = Path(snapshots_dir)
        self.min_hits = min_hits
        self.trail_length = trail_length
        self.stale_frames = stale_frames
        self.reset(session_id=0)

    def reset(self, session_id: int) -> None:
        self.records: dict[int, VehicleRecord] = {}
        self.active_ids: list[int] = []
        self.snapshot_dir = self.snapshots_root / f"session_{session_id}"

    @property
    def registered_count(self) -> int:
        return sum(1 for r in self.records.values() if r.registered)

    def type_map(self) -> dict[int, str]:
        return {tid: r.vehicle_type for tid, r in self.records.items()}

    def update(self, objects: TrackedObjects, frame: np.ndarray,
               timestamp: float, frame_index: int) -> list[int]:
        """Update records from one frame. Returns IDs that just became registered."""
        newly_registered = []
        self.active_ids = []
        h, w = frame.shape[:2]

        for box, conf, cls, tid in zip(objects.xyxy, objects.confidence,
                                       objects.class_id, objects.track_id):
            tid, conf = int(tid), float(conf)
            rec = self.records.get(tid)
            if rec is None:
                rec = VehicleRecord(tid, timestamp, frame_index,
                                    trail=deque(maxlen=self.trail_length))
                self.records[tid] = rec

            rec.last_seen, rec.last_frame = timestamp, frame_index
            rec.frames_seen += 1
            rec.best_conf = max(rec.best_conf, conf)
            rec.class_votes[self.class_names.get(int(cls), "Unknown")] += conf
            rec.bbox = tuple(float(v) for v in box)
            rec.trail.append((int((box[0] + box[2]) / 2), int(box[3])))
            bh = max(1.0, float(box[3] - box[1]))
            cx, cy = float((box[0] + box[2]) / 2), float(box[3])
            rec.motion.append((timestamp, cx, cy, bh))
            # speed over roughly the last second, in box-heights per second (scale-free)
            old = next((m for m in rec.motion if timestamp - m[0] <= 1.2), None)
            if old is not None and timestamp - old[0] >= 0.4:
                dist = ((cx - old[1]) ** 2 + (cy - old[2]) ** 2) ** 0.5
                rec.max_speed = max(rec.max_speed, dist / ((bh + old[3]) / 2) / (timestamp - old[0]))
            rec.dirty = True
            self.active_ids.append(tid)

            # keep the sharpest/largest, fully-visible view as the snapshot
            x1, y1, x2, y2 = (int(v) for v in box)
            touches_edge = x1 <= 2 or y1 <= 2 or x2 >= w - 2 or y2 >= h - 2
            score = conf * (x2 - x1) * (y2 - y1) * (0.3 if touches_edge else 1.0)
            if score > rec._crop_score:
                pad = int(0.08 * max(x2 - x1, y2 - y1))
                crop = frame[max(0, y1 - pad):min(h, y2 + pad), max(0, x1 - pad):min(w, x2 + pad)]
                if crop.size:
                    rec._crop, rec._crop_score = crop.copy(), score

            if not rec.registered and rec.frames_seen >= self.min_hits:
                rec.registered = True
                newly_registered.append(tid)

        return newly_registered

    def mark_crossed(self, track_id: int, direction: str, timestamp: float) -> None:
        rec = self.records.get(track_id)
        if rec:
            rec.direction, rec.counted, rec.crossed_at = direction, True, timestamp
            rec.registered = True  # a counted vehicle is always kept
            rec.dirty = True

    def flush(self, frame_index: int | None = None) -> list[dict]:
        """Write pending snapshots and return rows that changed since the last flush.

        Records unseen for `stale_frames` release their in-memory crop and trail.
        """
        rows = []
        for rec in self.records.values():
            if not rec.registered:
                continue
            if rec._crop is not None and rec._crop_score > rec._crop_saved_score:
                self.snapshot_dir.mkdir(parents=True, exist_ok=True)
                path = self.snapshot_dir / f"vehicle_{rec.track_id}.jpg"
                cv2.imwrite(str(path), rec._crop, [cv2.IMWRITE_JPEG_QUALITY, 90])
                rec.snapshot_path, rec._crop_saved_score = str(path), rec._crop_score
                rec.dirty = True
            if rec.dirty and not rec.merged:
                rows.append(rec.to_row())
                rec.dirty = False
            if frame_index is not None and frame_index - rec.last_frame > self.stale_frames:
                rec._crop = None
                rec.trail.clear()
        # forget unregistered noise tracks that disappeared
        if frame_index is not None:
            for tid in [t for t, r in self.records.items()
                        if not r.registered and frame_index - r.last_frame > self.stale_frames]:
                del self.records[tid]
        return rows
