import re
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_settings(path: str | Path = PROJECT_ROOT / "config" / "settings.yaml") -> dict:
    """Load settings.yaml and resolve relative paths against the project root."""
    with open(path, "r", encoding="utf-8") as f:
        settings = yaml.safe_load(f)
    settings["model"]["weights"] = str(PROJECT_ROOT / settings["model"]["weights"])
    settings["video"]["default_source"] = str(PROJECT_ROOT / settings["video"]["default_source"])
    settings["tracking"]["tracker_config"] = str(PROJECT_ROOT / settings["tracking"]["tracker_config"])
    for key, value in settings["storage"].items():
        settings["storage"][key] = str(PROJECT_ROOT / value)
    if "classifier" in settings:
        settings["classifier"]["model_dir"] = str(PROJECT_ROOT / settings["classifier"]["model_dir"])
    settings["classes"] = {int(k): v for k, v in settings["classes"].items()}
    return settings


def hex_to_bgr(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return b, g, r


def format_seconds(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


_CREDENTIALS = re.compile(r"^([a-zA-Z][\w+.-]*://[^:/@]+):[^@/]*@")


def mask_credentials(url: str) -> str:
    """Hide the password in stream URLs: rtsp://user:secret@host -> rtsp://user:***@host."""
    return _CREDENTIALS.sub(lambda m: f"{m.group(1)}:***@", url)
