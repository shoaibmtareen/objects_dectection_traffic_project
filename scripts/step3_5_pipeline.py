"""Steps 3-5 — tracking + counting + database, without the UI.

Usage:
    python scripts/step3_5_pipeline.py                       # default sample video
    python scripts/step3_5_pipeline.py --max-frames 300 --no-show --save data/out.mp4
Press Q or Esc to quit.
"""
import argparse
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.pipeline import Pipeline  # noqa: E402
from core.video_source import VideoSource  # noqa: E402
from storage.database import Database  # noqa: E402
from utils.helpers import load_settings  # noqa: E402


def main():
    settings = load_settings()
    p = argparse.ArgumentParser()
    p.add_argument("--source", default=settings["video"]["default_source"])
    p.add_argument("--save", default=None)
    p.add_argument("--no-show", action="store_true")
    p.add_argument("--max-frames", type=int, default=0)
    args = p.parse_args()

    db = Database(settings["storage"]["database"])
    pipeline = Pipeline(settings, db)
    src = VideoSource(args.source, settings["processing"]["max_width"])
    session_id = pipeline.start_session(str(args.source))
    if args.save:
        pipeline.start_recording(args.save, src.fps, (src.width, src.height))

    result = None
    try:
        while True:
            ok, frame = src.read()
            if not ok:
                break
            result = pipeline.process(frame, src.timestamp, src.frame_index, src.progress)
            for tid, direction, vtype in result.crossings:
                print(f"  [{result.timestamp:6.2f}s] COUNTED #{tid} {vtype} {direction}  total={result.total}")
            if not args.no_show:
                cv2.imshow("Vehicle Pipeline - Steps 3-5", result.frame)
                if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                    break
            if src.frame_index % 50 == 0:
                print(f"frame {src.frame_index}  fps {result.fps:.1f}  in-frame {result.in_frame}  "
                      f"tracked {result.tracked}  counted {result.total}")
            if args.max_frames and src.frame_index + 1 >= args.max_frames:
                break
    finally:
        pipeline.end_session()
        src.release()
        cv2.destroyAllWindows()

    if result:
        print(f"\nSession {session_id}: counted {result.total} (IN {result.in_count} / OUT {result.out_count})")
        print("By type:", result.counted_by_type)
        print("Rows in DB:", len(db.search_vehicles(session_id=session_id)))


if __name__ == "__main__":
    main()
