import numpy as np

from core.detector import TrackedObjects


class LineCounter:
    """Counts each track ID once when its bottom-centre point crosses a line.

    The line is stored in normalised coordinates (0..1) so it survives
    resolution changes and can be edited from the UI. Direction is "IN" when
    crossing from the left side of the start->end vector to the right side,
    otherwise "OUT" (for a left-to-right horizontal line, IN = moving down).
    """

    def __init__(self, start: tuple[float, float], end: tuple[float, float]):
        self.start = tuple(start)
        self.end = tuple(end)
        self.reset()

    def reset(self) -> None:
        self._last_side: dict[int, float] = {}
        self.crossed: dict[int, str] = {}  # track_id -> "IN"/"OUT"
        self.in_count = 0
        self.out_count = 0

    def set_line(self, start, end) -> None:
        self.start, self.end = tuple(start), tuple(end)
        self._last_side.clear()  # avoid false crossings when the line moves

    @property
    def total(self) -> int:
        return self.in_count + self.out_count

    def pixel_line(self, width: int, height: int) -> tuple[tuple[int, int], tuple[int, int]]:
        return ((int(self.start[0] * width), int(self.start[1] * height)),
                (int(self.end[0] * width), int(self.end[1] * height)))

    def update(self, objects: TrackedObjects, width: int, height: int) -> list[tuple[int, str]]:
        """Process one frame. Returns [(track_id, direction)] for new crossings."""
        if len(objects) == 0:
            return []
        (x1, y1), (x2, y2) = self.pixel_line(width, height)
        line_vec = np.array([x2 - x1, y2 - y1], dtype=float)
        seg_len_sq = float(line_vec @ line_vec) or 1.0

        events = []
        for box, tid in zip(objects.xyxy, objects.track_id):
            tid = int(tid)
            px, py = (box[0] + box[2]) / 2, box[3]  # bottom-centre anchor
            rel = np.array([px - x1, py - y1])
            side = float(line_vec[0] * rel[1] - line_vec[1] * rel[0])
            if side == 0:  # exactly on the line: decide on the next frame
                continue
            # only count crossings that happen within the segment's extent
            t = float(rel @ line_vec) / seg_len_sq
            prev = self._last_side.get(tid)
            self._last_side[tid] = side

            if tid in self.crossed or prev is None or not (0.0 <= t <= 1.0):
                continue
            if (prev < 0) != (side < 0):
                direction = "IN" if prev < 0 else "OUT"
                self.crossed[tid] = direction
                if direction == "IN":
                    self.in_count += 1
                else:
                    self.out_count += 1
                events.append((tid, direction))
        return events
