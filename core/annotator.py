import cv2
import numpy as np

from core.detector import TrackedObjects
from utils.helpers import hex_to_bgr

FONT = cv2.FONT_HERSHEY_SIMPLEX
WHITE = (255, 255, 255)
LINE = (250, 250, 250)
NAVY = (61, 30, 15)  # #0F1E3D in BGR
HIGHLIGHT = (21, 204, 250)  # #FACC15 in BGR — selected vehicle


class FrameAnnotator:
    """Draws boxes, IDs, trails and the counting line onto a frame."""

    def __init__(self, colors: dict[str, str]):
        self.colors = {name: hex_to_bgr(c) for name, c in colors.items()}
        self.show_trails = False
        self.show_labels = True
        self.highlight_id: int | None = None
        self.show_line = False

    def color_for(self, vehicle_type: str) -> tuple[int, int, int]:
        return self.colors.get(vehicle_type, (200, 200, 200))

    def annotate(self, frame: np.ndarray, objects: TrackedObjects, records: dict,
                 line: tuple[tuple[int, int], tuple[int, int]],
                 in_count: int, out_count: int) -> np.ndarray:
        out = frame.copy()
        # frames are shown scaled down in the UI, so draw a bit larger than 1:1
        scale = max(0.8, out.shape[1] / 820)

        if self.show_line:
            self._draw_line(out, line, in_count, out_count, scale)

        for box, tid in zip(objects.xyxy, objects.track_id):
            rec = records.get(int(tid))
            if rec is None:
                continue
            color = self.color_for(rec.vehicle_type)
            if self.show_trails and len(rec.trail) > 1:
                pts = np.array(rec.trail, dtype=np.int32)
                for i in range(1, len(pts)):
                    alpha_thick = max(1, int(3 * scale * i / len(pts)))
                    cv2.line(out, tuple(pts[i - 1]), tuple(pts[i]), color, alpha_thick, cv2.LINE_AA)
            self._draw_box(out, box, color, int(tid) == self.highlight_id, rec.counted, scale)
            if self.show_labels:
                text = f"#{int(tid)} {rec.vehicle_type}"
                self._draw_label(out, box, text, color, scale)
        return out

    def _draw_box(self, img, box, color, highlighted, counted, scale):
        x1, y1, x2, y2 = (int(v) for v in box)
        t = max(1, int((3 if highlighted else 2) * scale))
        cv2.rectangle(img, (x1, y1), (x2, y2), HIGHLIGHT if highlighted else color, t, cv2.LINE_AA)
        # corner accents
        k = max(6, int(min(x2 - x1, y2 - y1) * 0.2))
        ct = t + 1
        for (cx, cy, dx, dy) in ((x1, y1, 1, 1), (x2, y1, -1, 1), (x1, y2, 1, -1), (x2, y2, -1, -1)):
            cv2.line(img, (cx, cy), (cx + dx * k, cy), color, ct, cv2.LINE_AA)
            cv2.line(img, (cx, cy), (cx, cy + dy * k), color, ct, cv2.LINE_AA)
        if counted:
            r = max(4, int(5 * scale))
            cv2.circle(img, (x2 - r - 3, y2 - r - 3), r, (94, 197, 34), -1, cv2.LINE_AA)

    def _draw_label(self, img, box, text, color, scale):
        x1, y1 = int(box[0]), int(box[1])
        fs, th = 0.5 * scale, max(1, int(scale))
        (tw, tht), base = cv2.getTextSize(text, FONT, fs, th)
        pad = int(4 * scale)
        y_top = y1 - tht - 2 * pad
        if y_top < 0:
            y_top = y1
        cv2.rectangle(img, (x1, y_top), (x1 + tw + 2 * pad, y_top + tht + 2 * pad), color, -1)
        cv2.putText(img, text, (x1 + pad, y_top + tht + pad), FONT, fs, WHITE, th, cv2.LINE_AA)

    def _draw_line(self, img, line, in_count, out_count, scale):
        (x1, y1), (x2, y2) = line
        overlay = img.copy()
        cv2.line(overlay, (x1, y1), (x2, y2), NAVY, max(4, int(6 * scale)), cv2.LINE_AA)
        cv2.line(overlay, (x1, y1), (x2, y2), LINE, max(2, int(3 * scale)), cv2.LINE_AA)
        cv2.addWeighted(overlay, 0.85, img, 0.15, 0, img)
        for p in ((x1, y1), (x2, y2)):
            cv2.circle(img, p, max(4, int(6 * scale)), LINE, -1, cv2.LINE_AA)
            cv2.circle(img, p, max(4, int(6 * scale)), NAVY, 2, cv2.LINE_AA)

        text = f"VEHICLES  IN {in_count}   OUT {out_count}"
        fs, th = 0.55 * scale, max(1, int(scale))
        (tw, tht), _ = cv2.getTextSize(text, FONT, fs, th)
        pad = int(6 * scale)
        mx = int((x1 + x2) / 2 - tw / 2)
        my = int((y1 + y2) / 2 - tht - 3 * pad)
        mx = min(max(pad, mx), img.shape[1] - tw - 3 * pad)
        my = max(pad, my)
        cv2.rectangle(img, (mx - pad, my - pad), (mx + tw + pad, my + tht + pad), NAVY, -1)
        cv2.putText(img, text, (mx, my + tht), FONT, fs, WHITE, th, cv2.LINE_AA)
