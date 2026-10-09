"""Step 2 — vehicle detection + classification on a video (no tracking yet).

Usage:
    python scripts/step2_detect.py                      # default sample video
    python scripts/step2_detect.py --source 0           # webcam
    python scripts/step2_detect.py --save out.mp4       # also save annotated video
Press Q or Esc to quit.
"""
import argparse
import sys
import time
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
import supervision as sv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.detector import VehicleDetector  # noqa: E402
from utils.helpers import load_settings  # noqa: E402


def parse_args(settings):
    p = argparse.ArgumentParser()
    p.add_argument("--source", default=settings["video"]["default_source"])
    p.add_argument("--conf", type=float, default=settings["model"]["conf"])
    p.add_argument("--save", default=None, help="path to save annotated mp4")
    p.add_argument("--no-show", action="store_true", help="don't open a window")
    p.add_argument("--max-frames", type=int, default=0, help="stop after N frames (0 = all)")
    return p.parse_args()


def draw_hud(frame, counts: Counter, fps: float, scale: float):
    lines = [f"FPS: {fps:.1f}", f"In frame: {sum(counts.values())}"]
    lines += [f"{name}: {n}" for name, n in sorted(counts.items())]
    pad, lh, m = int(10 * scale), int(26 * scale), int(10 * scale)
    w, h = int(220 * scale), pad * 2 + lh * len(lines)
    overlay = frame.copy()
    cv2.rectangle(overlay, (m, m), (m + w, m + h), (23, 15, 15), -1)
    cv2.addWeighted(overlay, 0.65, frame, 0.35, 0, frame)
    for i, text in enumerate(lines):
        cv2.putText(frame, text, (m + pad, m + pad + lh * (i + 1) - int(6 * scale)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6 * scale, (255, 255, 255),
                    max(1, int(scale)), cv2.LINE_AA)


def main():
    settings = load_settings()
    args = parse_args(settings)
    m = settings["model"]
    detector = VehicleDetector(m["weights"], settings["classes"], m["device"],
                               m["imgsz"], args.conf, m["iou"])

    source = int(args.source) if str(args.source).isdigit() else args.source
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        sys.exit(f"Could not open source: {args.source}")

    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    scale = max(1.0, w / 1280)  # keep text/lines readable on high-res video

    writer = None
    if args.save:
        fps_in = cap.get(cv2.CAP_PROP_FPS) or 25
        writer = cv2.VideoWriter(args.save, cv2.VideoWriter_fourcc(*"mp4v"), fps_in, (w, h))

    palette = sv.ColorPalette.from_hex([settings["colors"][n] for n in settings["classes"].values()])
    box_annotator = sv.BoxAnnotator(color=palette, thickness=int(2 * scale))
    label_annotator = sv.LabelAnnotator(color=palette, text_scale=0.5 * scale,
                                        text_thickness=max(1, int(scale)),
                                        text_padding=int(4 * scale))

    class_order = list(settings["classes"].keys())
    frames, fps, t_prev = 0, 0.0, time.perf_counter()
    while True:
        ok, frame = cap.read()
        if not ok:
            break

        detections = detector.detect(frame)
        # map class id -> palette index so each type always gets the same color
        color_idx = [class_order.index(int(c)) for c in detections.class_id]
        labels = [f"{n} {c:.2f}" for n, c in zip(detections.data["class_name"], detections.confidence)]

        draw_dets = detections[:]  # copy so original class ids stay intact
        draw_dets.class_id = np.array(color_idx, dtype=int)
        annotated = box_annotator.annotate(frame.copy(), draw_dets)
        annotated = label_annotator.annotate(annotated, draw_dets, labels=labels)

        now = time.perf_counter()
        fps = 0.9 * fps + 0.1 * (1 / (now - t_prev)) if fps else 1 / (now - t_prev)
        t_prev = now
        draw_hud(annotated, Counter(detections.data["class_name"]), fps, scale)

        if writer:
            writer.write(annotated)
        if not args.no_show:
            cv2.imshow("Vehicle Detection - Step 2", cv2.resize(annotated, (1280, int(1280 * h / w))))
            if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                break

        frames += 1
        if frames % 50 == 0:
            print(f"frame {frames}  fps {fps:.1f}  in-frame {len(detections)}")
        if args.max_frames and frames >= args.max_frames:
            break

    cap.release()
    if writer:
        writer.release()
    cv2.destroyAllWindows()
    print(f"Done. Processed {frames} frames.")


if __name__ == "__main__":
    main()
