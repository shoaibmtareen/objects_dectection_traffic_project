import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from core.annotator import FrameAnnotator
from core.counter import LineCounter
from core.detector import TrackedObjects, VehicleDetector
from core.registry import VehicleRegistry
from storage.database import Database

FLUSH_EVERY = 15  # frames between database writes


@dataclass
class FrameResult:
    frame: np.ndarray
    frame_index: int
    timestamp: float
    progress: float
    fps: float
    in_frame_ids: list[int]
    in_frame_by_type: dict[str, int]
    total: int          # vehicles counted (people excluded)
    in_count: int       # vehicles counted IN
    out_count: int      # vehicles counted OUT
    people_counted: int
    counted_by_type: dict[str, int]   # crossed the counting line
    unique_by_type: dict[str, int]    # every distinct ID seen this session
    tracked: int
    crossings: list[tuple[int, str, str]] = field(default_factory=list)  # (id, dir, type)
    # (track_id, x1, y1, x2, y2) with coordinates normalised to 0..1
    in_frame_boxes: list[tuple[int, float, float, float, float]] = field(default_factory=list)
    # what the UI draws on top of the raw frame (kept crisp at any zoom)
    overlay: dict = field(default_factory=dict)

    @property
    def in_frame(self) -> int:
        return len(self.in_frame_ids)


class Pipeline:
    """Detect -> track -> register -> count -> annotate -> store, one frame at a time."""

    def __init__(self, settings: dict, db: Database):
        self.settings = settings
        self.db = db
        m, t, c = settings["model"], settings["tracking"], settings["counting"]
        self.detector = self.make_detector(settings, m["weights"])
        self.counter = LineCounter(c["line_start"], c["line_end"])
        self.registry = VehicleRegistry(settings["classes"], settings["storage"]["snapshots_dir"],
                                        t["min_hits"], t["trail_length"])
        self.annotator = FrameAnnotator(settings["colors"])
        self.annotator.show_line = bool(c.get("show_line", False))
        self.non_vehicle = set(c.get("non_vehicle_classes", []))
        # keep showing an object this long after a missed detection (stops flicker)
        self.hold_seconds = float(t.get("hold_seconds", 0.6))
        self._name_to_id = {name: cid for cid, name in settings["classes"].items()}
        # second-stage crop classifier (recognises rickshaws, fixes car/truck/bus mix-ups)
        k = settings.get("classifier", {})
        self.classifier = None
        self.clip_max_checks = int(k.get("max_checks", 3))
        self.clip_per_frame = int(k.get("per_frame", 2))
        self.clip_min_prob = float(k.get("min_prob", 0.6))
        if k.get("enabled", True):
            try:
                from core.classifier import CropClassifier
                self.classifier = CropClassifier(k.get("model_dir", "models/clip"), k.get("model", "ViT-B/32"),
                                                 m["device"])
            except Exception as exc:  # noqa: BLE001 - app still works with YOLO labels only
                print(f"[classifier] disabled: {exc}")
        self.session_id: int | None = None
        self._processed = 0
        self._alias: dict[int, int] = {}  # new tracker id -> earlier id of the same object
        self.enabled: set[str] = set(settings["colors"]) | set(settings["classes"].values())
        self._fps = 0.0
        self._t_prev: float | None = None
        self._frame_index = 0
        self._writer: cv2.VideoWriter | None = None

    @staticmethod
    def make_detector(settings: dict, weights: str) -> VehicleDetector:
        m = settings["model"]
        name_to_id = {name: cid for cid, name in settings["classes"].items()}
        class_conf = {name_to_id[n]: v for n, v in (m.get("class_conf") or {}).items() if n in name_to_id}
        return VehicleDetector(weights, settings["classes"], m["device"], m["imgsz"], m["conf"],
                               m["iou"], settings["tracking"]["tracker_config"], class_conf)

    # ---------- session ----------
    def start_session(self, source_label: str) -> int:
        self.session_id = self.db.create_session(source_label)
        self.detector.reset_tracker()
        self.counter.reset()
        self.registry.reset(self.session_id)
        self._alias = {}
        self._fps, self._t_prev, self._frame_index, self._processed = 0.0, None, 0, 0
        return self.session_id

    def on_seek(self) -> None:
        """Called after the video jumps: forget line positions and trails so the
        jump is not mistaken for movement."""
        self.counter.set_line(self.counter.start, self.counter.end)
        for rec in self.registry.records.values():
            rec.trail.clear()
        self._t_prev = None

    def end_session(self) -> None:
        if self.session_id is None:
            return
        self._flush(ended=True)
        self.stop_recording()
        self.session_id = None

    # ---------- runtime settings ----------
    def set_confidence(self, conf: float) -> None:
        self.detector.conf = conf

    def set_line(self, start, end) -> None:
        self.counter.set_line(start, end)

    def set_classes(self, names: list[str]) -> None:
        """Detect / show only these class names (e.g. ["Car", "Rickshaw"])."""
        self.enabled = set(names)
        wanted = set(names)
        if "Rickshaw" in wanted:  # rickshaws are first detected as one of these, then reclassified
            wanted |= {"Car", "Truck", "Bus", "Motorcycle", "Bicycle"}
        ids = [cid for cid, name in self.settings["classes"].items() if name in wanted]
        self.detector.class_ids = ids or list(self.settings["classes"].keys())
        if self.classifier is not None:
            # e.g. Rickshaw comes only from the classifier; respect it being switched off
            self.classifier.disabled_labels = {"Rickshaw"} - set(names)

    def _totals(self) -> tuple[int, int, int]:
        """(vehicles IN, vehicles OUT, people counted) from the registry."""
        v_in = v_out = people = 0
        for r in self.registry.records.values():
            if not r.counted or r.merged or r.vehicle_type not in self.enabled:
                continue
            if r.vehicle_type in self.non_vehicle:
                people += 1
            elif r.direction == "IN":
                v_in += 1
            else:
                v_out += 1
        return v_in, v_out, people

    # ---------- recording ----------
    def start_recording(self, path: str, fps: float, size: tuple[int, int]) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._writer = cv2.VideoWriter(path, cv2.VideoWriter_fourcc(*"mp4v"), fps, size)

    def stop_recording(self) -> None:
        if self._writer is not None:
            self._writer.release()
            self._writer = None

    @property
    def is_recording(self) -> bool:
        return self._writer is not None

    # ---------- processing ----------
    @staticmethod
    def _person_crop(frame: np.ndarray, box) -> np.ndarray:
        """Person box padded sideways and downwards so a motorbike / bicycle under them is in view."""
        H, W = frame.shape[:2]
        x1, y1, x2, y2 = (int(v) for v in box)
        h = max(1, y2 - y1)
        pad = int(0.35 * h)
        return frame[max(0, y1 - h // 6):min(H, y2 + pad), max(0, x1 - pad):min(W, x2 + pad)]

    def _classify_some(self, objects: TrackedObjects, frame: np.ndarray) -> None:
        """Run the crop classifier on a few tracked objects that still need a verdict."""
        if self.classifier is None:
            return
        due = []
        for box, tid in zip(objects.xyxy, objects.track_id):
            rec = self.registry.records.get(int(tid))
            if (rec is None or rec.frames_seen < 2 or rec._crop is None
                    or not self.classifier.needs_check(rec.yolo_type)
                    or (rec.yolo_type != "Person" and rec.clip_checks >= self.clip_max_checks
                        and not (rec.clip_checks < 2 * self.clip_max_checks
                                 and rec._crop_score > 1.5 * rec.clip_crop_score))):
                continue
            if rec.yolo_type == "Person":
                # people: need a usable size; re-check every ~8 frames (riders get closer and clearer)
                if (box[3] - box[1] >= 18 and rec.clip_checks < self.clip_max_checks + 2
                        and (rec.clip_checks == 0 or rec.frames_seen - rec.clip_crop_score >= 8)):
                    due.append((rec, box))
            # vehicles: first check straight away, later ones only when a clearly better view exists
            elif rec.clip_checks == 0 or rec._crop_score > 1.5 * rec.clip_crop_score:
                due.append((rec, box))
        due.sort(key=lambda d: d[0].clip_checks)
        for rec, box in due[:self.clip_per_frame]:
            size = float(box[3] - box[1]) ** 2  # weight by area: close-up views dominate
            if rec.yolo_type == "Person":
                rec.add_clip_result(self.classifier.classify_person(self._person_crop(frame, box)), size)
                rec.clip_crop_score = rec.frames_seen  # for people: frame count at the last check
                continue
            # two-wheelers with riders can look boxy: require much stronger evidence to relabel them
            rec.clip_min_prob = (max(self.clip_min_prob, 0.85) if rec.yolo_type in ("Motorcycle", "Bicycle")
                                 else self.clip_min_prob)
            rec.add_clip_result(self.classifier.classify(rec._crop, rec.yolo_type), size)

    def _with_held(self, objects: TrackedObjects, timestamp: float, frame_index: int) -> TrackedObjects:
        """Add objects missed in this frame but seen within `hold_seconds` (last known box)."""
        current = set(int(t) for t in objects.track_id)
        held = [r for r in self.registry.records.values()
                if r.registered and r.track_id not in current and r.last_frame < frame_index
                and 0 < timestamp - r.last_seen <= self.hold_seconds]
        if not held:
            return objects
        return TrackedObjects(
            xyxy=np.vstack([objects.xyxy.reshape(-1, 4), np.array([r.bbox for r in held])]),
            confidence=np.concatenate([objects.confidence, [r.best_conf for r in held]]),
            class_id=np.concatenate([objects.class_id,
                                     [self._name_to_id.get(r.vehicle_type, -1) for r in held]]).astype(int),
            track_id=np.concatenate([objects.track_id, [r.track_id for r in held]]).astype(int),
        )

    def _drop_riders(self, objects: TrackedObjects) -> TrackedObjects:
        """Remove people sitting on a motorcycle / bicycle: they are riders, not pedestrians.
        If such a person already had its own record, it is merged (not counted twice)."""
        if len(objects) == 0:
            return objects
        cls = objects.class_id
        rides = objects.xyxy[(cls == 1) | (cls == 3)]  # COCO bicycle, motorcycle
        if len(rides) == 0:
            return objects
        keep = np.ones(len(objects), dtype=bool)
        for i in np.where(cls == 0)[0]:  # COCO person
            px1, py1, px2, py2 = objects.xyxy[i]
            area = max(1.0, (px2 - px1) * (py2 - py1))
            cx = (px1 + px2) / 2
            for vx1, vy1, vx2, vy2 in rides:
                inter = max(0.0, min(px2, vx2) - max(px1, vx1)) * max(0.0, min(py2, vy2) - max(py1, vy1))
                vh = vy2 - vy1
                # centred over the vehicle, overlapping it, feet/hips inside the vehicle's
                # vertical span (a rider) rather than standing on the road beside it
                if (inter / area >= 0.15 and vx1 <= cx <= vx2
                        and vy1 + 0.2 * vh <= py2 <= vy2 + 0.15 * vh):
                    keep[i] = False
                    break
        if keep.all():
            return objects
        for tid in objects.track_id[~keep]:
            rec = self.registry.records.get(int(tid))
            if rec is not None and not rec.merged:
                rec.merged, rec.dirty = True, True
        return TrackedObjects(objects.xyxy[keep], objects.confidence[keep], objects.class_id[keep],
                              objects.track_id[keep])

    def _stitch(self, objects: TrackedObjects, timestamp: float, w: int, h: int) -> TrackedObjects:
        """Re-use the ID of an object that vanished moments ago where a new ID appears
        (tracker lost it behind a pole / tree / vehicle), so it is not counted twice."""
        if len(objects) == 0:
            return objects
        records = self.registry.records
        ids = objects.track_id.copy()
        current = {int(t) for t in ids}
        taken = set()
        for i, (box, cls, tid) in enumerate(zip(objects.xyxy, objects.class_id, ids)):
            tid = int(tid)
            if tid in self._alias:
                ids[i] = self._alias[tid]
                continue
            if tid in records:
                continue
            name = self.settings["classes"].get(int(cls), "")
            bh = float(box[3] - box[1])
            cx, cy = float(box[0] + box[2]) / 2, float(box[3])
            best, best_d = None, None
            for rec in records.values():
                if (not rec.registered or rec.merged or rec.track_id in current or rec.track_id in taken
                        or not (0 < timestamp - rec.last_seen <= 3.0)):
                    continue
                if (rec.yolo_type == "Person") != (name == "Person"):
                    continue
                x1, y1, x2, y2 = rec.bbox
                if x1 <= 3 or y1 <= 3 or x2 >= w - 3 or y2 >= h - 3:
                    continue  # it left the frame: a new object, not a re-appearance
                rh = max(1.0, y2 - y1)
                if not (0.5 <= bh / rh <= 2.0):
                    continue
                d = ((cx - (x1 + x2) / 2) ** 2 + (cy - y2) ** 2) ** 0.5
                reach = (1.5 if name == "Person" else 1.0) * max(bh, rh)
                if d <= reach and (best_d is None or d < best_d):
                    best, best_d = rec, d
            if best is not None:
                self._alias[tid] = best.track_id
                taken.add(best.track_id)
                ids[i] = best.track_id
        if (ids == objects.track_id).all():
            return objects
        return TrackedObjects(objects.xyxy, objects.confidence, objects.class_id, ids)

    def _overlay(self, shown: TrackedObjects, current: set[int], w: int, h: int, v_in: int, v_out: int) -> dict:
        """Boxes for every object detected now (new ones too, so a paused frame right after
        a seek is not empty) plus held ones; counting still waits for registration."""
        records = self.registry.records
        boxes = []
        for b, tid in zip(shown.xyxy, shown.track_id):
            rec = records.get(int(tid))
            if (rec is None or rec.merged or not (rec.registered or int(tid) in current)
                    or rec.vehicle_type not in self.enabled):
                continue
            trail = ([(x / w, y / h) for x, y in rec.trail] if self.annotator.show_trails else [])
            boxes.append({"id": int(tid), "box": (b[0] / w, b[1] / h, b[2] / w, b[3] / h),
                          "label": f"#{int(tid)} {rec.vehicle_type}", "type": rec.vehicle_type,
                          "counted": rec.counted, "trail": trail})
        (x1, y1), (x2, y2) = self.counter.start, self.counter.end
        return {"boxes": boxes, "line": ((x1, y1), (x2, y2)), "line_text": f"IN {v_in}   OUT {v_out}",
                "highlight": self.annotator.highlight_id}

    def process(self, frame: np.ndarray, timestamp: float, frame_index: int,
                progress: float = 0.0) -> FrameResult:
        h, w = frame.shape[:2]
        objects = self._drop_riders(self._stitch(self.detector.track(frame), timestamp, w, h))
        self.registry.update(objects, frame, timestamp, frame_index)
        self._classify_some(objects, frame)

        crossings = []
        for tid, direction in self.counter.update(objects, w, h):
            self.registry.mark_crossed(tid, direction, timestamp)
            crossings.append((tid, direction, self.registry.records[tid].vehicle_type))

        records = self.registry.records
        shown = self._with_held(objects, timestamp, frame_index)
        v_in, v_out, people = self._totals()
        if self._writer is not None:  # recordings get the annotations burned in
            self._writer.write(self.annotator.annotate(frame, shown, records, self.counter.pixel_line(w, h),
                                                       v_in, v_out))

        self._frame_index = frame_index
        self._processed += 1
        if self._processed % FLUSH_EVERY == 0 or crossings:
            self._flush()

        now = time.perf_counter()
        if self._t_prev is not None:
            inst = 1.0 / max(now - self._t_prev, 1e-6)
            self._fps = inst if self._fps == 0 else 0.9 * self._fps + 0.1 * inst
        self._t_prev = now

        active = [int(t) for t in shown.track_id
                  if records[int(t)].registered and not records[int(t)].merged
                  and records[int(t)].vehicle_type in self.enabled]
        visible = [r for r in records.values()
                   if r.registered and not r.merged and r.vehicle_type in self.enabled]
        return FrameResult(
            frame=frame,
            frame_index=frame_index,
            timestamp=timestamp,
            progress=progress,
            fps=self._fps,
            in_frame_ids=active,
            in_frame_by_type=dict(Counter(records[t].vehicle_type for t in active)),
            total=v_in + v_out,
            in_count=v_in,
            out_count=v_out,
            people_counted=people,
            counted_by_type=dict(Counter(r.vehicle_type for r in visible if r.counted)),
            unique_by_type=dict(Counter(r.vehicle_type for r in visible)),
            tracked=len(visible),
            crossings=crossings,
            in_frame_boxes=[(int(tid), b[0] / w, b[1] / h, b[2] / w, b[3] / h)
                            for b, tid in zip(shown.xyxy, shown.track_id) if int(tid) in active],
            overlay=self._overlay(shown, {int(t) for t in objects.track_id}, w, h, v_in, v_out),
        )

    def _flush(self, ended: bool = False) -> None:
        if self.session_id is None:
            return
        rows = [r for r in self.registry.flush(self._frame_index) if r["vehicle_type"] in self.enabled]
        self.db.upsert_vehicles(self.session_id, rows)
        v_in, v_out, _ = self._totals()
        self.db.update_session(self.session_id, frames=self._frame_index + 1,
                               total=v_in + v_out, in_count=v_in, out_count=v_out, ended=ended)
