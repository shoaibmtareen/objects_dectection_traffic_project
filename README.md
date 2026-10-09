# Vehicle Analytics System

Desktop application that **detects, classifies, tracks and counts vehicles and people** in
video files, webcams/USB cameras and IP-camera streams, with a searchable record of every object.

- **Detection & classification** — YOLO11 (car, truck, bus, motorcycle, bicycle, person) plus a
  second-stage CLIP crop classifier that recognises **rickshaws** (auto / cycle) and fixes
  car / truck / bus mix-ups; riders are merged into their motorcycle or bicycle
- **Tracking** — ByteTrack gives each object a persistent ID
- **Counting** — each ID is counted once when it crosses a counting line (IN / OUT direction);
  people are counted separately from the vehicle total
- **Records** — every object is stored in SQLite with type, confidence, timings and a snapshot
- **UI** — PySide6, three pages: source selection → live analytics ↔ records & search

## Setup

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu   # CPU build
pip install -r requirements.txt
```

With an NVIDIA GPU, install the CUDA build of PyTorch instead and set `model.device: "0"`
in `config/settings.yaml`.

## Run

```powershell
python main.py
```

### Page 1 — Start a new analysis

1. **Video source** — choose one:
   - **Video file**: *Browse…* for a file, or *Use the sample highway video*
   - **Webcam / USB camera**: connected cameras are detected automatically (*Detect cameras* to rescan)
   - **IP camera**: paste an RTSP or HTTP stream URL (passwords are masked wherever the URL is shown or saved)
2. **Detection settings** — model (Nano / Small / Medium), minimum confidence, and which object
   types to detect.
3. **Start analysis** — opens the analytics page.

*View saved records* (top right) opens the Records page to browse earlier sessions.

### Page 2 — Live analytics

| Area | Shows |
|---|---|
| Left | Live annotated video and controls (pause, stop, confidence, draw/reset counting line, trails, record) |
| Top right — **Current frame** | Objects in view right now, per class (car, truck, bus, motorcycle, bicycle, person), and the selected object |
| Bottom right — **Total this session** | Every distinct object detected so far (each ID counted once), per class, plus counting-line crossings (↓ IN / ↑ OUT) |

**Playback controls** (video files): drag or click the timeline to jump anywhere, Play/Pause,
back/forward 5 s, step one frame, restart, speed 1× / 2× / 4× (processes every 2nd / 4th frame),
**Screenshot** (saved to `data/screenshots/` and copied to the clipboard) and **Focus mode** (bigger video).
At the end of a file the video pauses on the last frame so you can review; **Stop** finishes the session.

**Zoom:** mouse wheel or touchpad pinch zooms around the cursor (up to 8×), drag to move around,
double-click (or `0`) to reset. Boxes and labels stay sharp and small at any zoom.

| Key | Action |
|---|---|
| `Space` | Play / pause |
| `+` / `-` / `0` | Zoom in / out / reset |
| `←` / `→` | Back / forward 5 seconds |
| `.` | Next frame (while paused) |
| `Home` | Restart |
| `S` | Screenshot |
| `F` | Focus mode |

Click an object in the video to select it; **Details** opens it on the Records page.
Click any class tile (e.g. *Truck*) to open Records filtered to that class.

### Page 3 — Records & search

Search every object by ID (`42` / `#42`) or type (`truck`, `person`); filter by type, direction,
session, *Crossed line only*, *In frame now*; select a row for its snapshot and details;
**Export** to CSV or Excel.

| Shortcut | Action |
|---|---|
| `Ctrl+F` | Open Records / focus search |
| `Esc` | Cancel drawing the line; leave the Records page |

## Project layout

```
main.py                 app entry point
config/settings.yaml    model, classes, colours, tracking, counting line, paths
config/bytetrack.yaml   tracker parameters
core/                   vision engine (no UI code)
  detector.py           YOLO wrapper (detect + track)
  video_source.py       file / camera / stream reader, camera discovery
  registry.py           per-ID records, type voting, snapshots
  counter.py            line-crossing counter
  annotator.py          drawing boxes, IDs, trails, line
  pipeline.py           ties everything together, one frame at a time
storage/database.py     SQLite: sessions + records, search
ui/                     PySide6 application
  main_window.py        page navigation, model loading
  pages/source_page.py  page 1: source + detection settings
  pages/analytics_page.py  page 2: live video, current frame, session totals
  pages/records_page.py    page 3: search, details, export
  worker.py             background processing thread
  widgets/              video view, stats panels, table, search, details, controls
  theme.py              colour themes (traffic_pro, graphite, smart_city)
  styles/theme.qss      stylesheet (uses the active theme's colours)
scripts/                stand-alone test scripts (no UI)
data/                   videos, database, snapshots, exports, recordings
```

## Command-line scripts

```powershell
python scripts/step2_detect.py                 # detection only
python scripts/step3_5_pipeline.py --no-show   # full pipeline without the UI
```

## How objects are recognised

1. **YOLO11** (COCO classes) finds every car, truck, bus, motorcycle, bicycle and person,
   at 960 px by default ("High" detail; 1280 "Maximum" finds more distant motorbikes).
2. **BoT-SORT** tracks each object with appearance re-identification, and **track stitching**
   re-uses an ID when an object reappears where it vanished moments earlier (behind a pole,
   tree or vehicle), so it is not counted twice.
3. **CLIP** checks each object's crop (more often when a closer, clearer view appears; bigger
   views count more):
   - car / truck / bus → can become **Rickshaw** (YOLO has no rickshaw class) or be hidden
     as **not a vehicle** (road signs, poles)
   - a "person" → becomes **Motorcycle** / **Bicycle** when CLIP sees them riding *and* they
     move like a vehicle (someone standing next to a parked bike stays a person)
4. People sitting on a detected motorcycle / bicycle are merged into it (riders are not pedestrians).

**Measured on the included test video** (every object checked by eye on two 20-second clips):
about 92–97 % of objects correctly classified. Remaining errors are mostly heavily blurred,
distant objects and the odd duplicate ID. For higher accuracy, train a custom YOLO model on
South-Asian traffic (needs a GPU, e.g. Google Colab).

## Tuning

All in `config/settings.yaml`:

- `ui.theme` — `traffic_pro` (default, charcoal & blue), `graphite` (dark) or `smart_city` (charcoal & green);
  screenshots of each are in `data/theme_previews/`
- `model.weights` — `yolo11s.pt` (default, accurate) or `yolo11n.pt` (faster, but misses many bicycles)
- `model.conf` — default confidence (also adjustable in the app)
- `model.imgsz` — 640 / 960 (default) / 1280; also selectable on the start page
- `model.class_conf` — lower thresholds for hard classes (bicycle 0.10, motorcycle 0.20)
- `tracking.tracker_config` — `botsort.yaml` (default, re-identification) or `bytetrack.yaml` (lighter)
- `classifier.*` — enable/disable the CLIP classifier, checks per vehicle, confidence needed
- `tracking.hold_seconds` — keep showing an object this long after a missed detection
- `processing.max_width` — lower (e.g. 960) for more speed on CPU
- `tracking.min_hits` — frames before a track is registered (filters flicker)
- `counting.line_start / line_end` — default line position (fractions of width/height)
- `counting.show_line` — show the counting line at start (default `false`; the **Line** checkbox
  under the video toggles it). The line counts vehicles crossing it as IN / OUT (traffic flow);
  the class totals do not depend on it.
- `counting.non_vehicle_classes` — classes counted separately from the vehicle total
