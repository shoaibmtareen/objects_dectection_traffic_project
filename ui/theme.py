"""UI colour themes.

Each preset is modelled on a real product in the traffic-analytics field
(colours sampled from their live stylesheets) and selected in
config/settings.yaml -> ui.theme. Call `apply(name)` before any widget is built.
"""
from pathlib import Path

# Class colours, validated (lightness, contrast, colour-blind separation) per surface type
CLASS_COLORS_LIGHT = {"Car": "#2563EB", "Truck": "#059669", "Bus": "#D97706", "Motorcycle": "#DB2777",
                      "Rickshaw": "#65A30D", "Bicycle": "#7C3AED", "Person": "#0891B2"}
CLASS_COLORS_DARK = {"Car": "#2F7FF0", "Truck": "#0FA97A", "Bus": "#CF7A06", "Motorcycle": "#E8436A",
                     "Rickshaw": "#6E9E12", "Bicycle": "#8B5CF6", "Person": "#0899B5"}

PRESETS = {
    # Miovision-style: charcoal bar, soft grey workspace, white panels, one strong blue
    "traffic_pro": {
        "label": "Traffic Pro — charcoal & blue (light)",
        "NAVY": "#1C2025", "NAVY_2": "#262B31",
        "BG": "#F0F3F7", "SURFACE": "#FFFFFF", "SURFACE_2": "#F6F8FB",
        "BORDER": "#E1E6EC", "BORDER_STRONG": "#C9D1DB",
        "TEXT": "#1C2025", "MUTED": "#3F5060", "SUBTLE": "#7A8796",
        "ACCENT": "#0F75DB", "ACCENT_2": "#0F75DB", "ACCENT_HOVER": "#0065ED",
        "ACCENT_SOFT": "#E3EFFC", "ACCENT_TEXT": "#0F75DB", "LINK": "#0F75DB",
        "HOVER": "#EEF4FB", "ALT_ROW": "#F7F9FB", "ROW_HOVER": "#EEF4FB",
        "SUCCESS": "#15803D", "WARNING": "#B45309", "DANGER": "#C62828",
        "VIDEO_BG": "#1C2025", "classes": CLASS_COLORS_LIGHT,
    },
    # Rekor / Miovision dark ops-centre: neutral graphite (no blue tint), same blue
    "graphite": {
        "label": "Graphite — neutral dark & blue",
        "NAVY": "#15181C", "NAVY_2": "#1B1F24",
        "BG": "#1B1F24", "SURFACE": "#23282F", "SURFACE_2": "#2B3139",
        "BORDER": "#333A43", "BORDER_STRONG": "#434B56",
        "TEXT": "#E6EAEF", "MUTED": "#A3ADB8", "SUBTLE": "#6E7A87",
        "ACCENT": "#0F75DB", "ACCENT_2": "#0F75DB", "ACCENT_HOVER": "#2B8AF0",
        "ACCENT_SOFT": "#1B3550", "ACCENT_TEXT": "#7DB8F7", "LINK": "#4FA3F7",
        "HOVER": "#2F363F", "ALT_ROW": "#262B32", "ROW_HOVER": "#2F363F",
        "SUCCESS": "#22C55E", "WARNING": "#F59E0B", "DANGER": "#F04452",
        "VIDEO_BG": "#111316", "classes": CLASS_COLORS_DARK,
    },
    # Vivacity / GoodVision smart-city: charcoal bar, warm light grey, teal-green accent
    "smart_city": {
        "label": "Smart City — charcoal & green (light)",
        "NAVY": "#323A45", "NAVY_2": "#3A4350",
        "BG": "#ECEFEA", "SURFACE": "#FFFFFF", "SURFACE_2": "#F4F6F2",
        "BORDER": "#D9DED5", "BORDER_STRONG": "#C5CCC0",
        "TEXT": "#2B2F33", "MUTED": "#444341", "SUBTLE": "#7D7B6D",
        "ACCENT": "#008B6F", "ACCENT_2": "#008B6F", "ACCENT_HOVER": "#007A61",
        "ACCENT_SOFT": "#E1F2EC", "ACCENT_TEXT": "#007A61", "LINK": "#008B6F",
        "HOVER": "#EEF6F2", "ALT_ROW": "#F8FAF6", "ROW_HOVER": "#EEF6F2",
        "SUCCESS": "#15803D", "WARNING": "#B45309", "DANGER": "#C62828",
        "VIDEO_BG": "#2B2F33", "classes": CLASS_COLORS_LIGHT,
    },
}
DEFAULT = "traffic_pro"

# Module-level tokens (filled by apply)
NAVY = NAVY_2 = BG = SURFACE = SURFACE_2 = BORDER = BORDER_STRONG = ""
TEXT = MUTED = SUBTLE = ACCENT = ACCENT_2 = ACCENT_HOVER = ACCENT_SOFT = ACCENT_TEXT = LINK = ""
HOVER = ALT_ROW = ROW_HOVER = SUCCESS = WARNING = DANGER = VIDEO_BG = ACCENT_GRADIENT = ""
CLASS_COLORS: dict[str, str] = {}
NAME = DEFAULT
FONT_FAMILY = "Segoe UI"


def apply(name: str | None) -> str:
    """Activate a preset (falls back to the default). Returns the active name."""
    global NAME, CLASS_COLORS, ACCENT_GRADIENT
    NAME = name if name in PRESETS else DEFAULT
    preset = PRESETS[NAME]
    for key, value in preset.items():
        if key.isupper():
            globals()[key] = value
    CLASS_COLORS = dict(preset["classes"])
    ACCENT_GRADIENT = ACCENT  # solid: the reference products use flat brand colour
    return NAME


apply(DEFAULT)


def shade(hex_color: str, factor: float) -> str:
    """factor < 1 darkens, > 1 lightens (mixes towards white)."""
    h = hex_color.lstrip("#")
    rgb = [int(h[i:i + 2], 16) for i in (0, 2, 4)]
    if factor < 1:
        rgb = [int(c * factor) for c in rgb]
    else:
        rgb = [int(c + (255 - c) * (factor - 1)) for c in rgb]
    return "#" + "".join(f"{max(0, min(255, c)):02X}" for c in rgb)


def gradient(hex_color: str) -> str:
    """Fill for an active class tile: flat class colour, like the reference products."""
    return hex_color


def load_stylesheet() -> str:
    styles = Path(__file__).parent / "styles"
    qss = (styles / "theme.qss").read_text(encoding="utf-8")
    tokens = {"@STYLES": styles.as_posix(), "@ACCENT_GRADIENT": ACCENT_GRADIENT}
    for key in ("NAVY_2", "NAVY", "BG", "SURFACE_2", "SURFACE", "BORDER_STRONG", "BORDER",
                "TEXT", "MUTED", "SUBTLE", "LINK", "ACCENT_HOVER", "ACCENT_SOFT", "ACCENT_TEXT",
                "ACCENT_2", "ACCENT", "HOVER", "ALT_ROW", "ROW_HOVER",
                "SUCCESS", "WARNING", "DANGER"):
        tokens["@" + key] = globals()[key]
    # replace longer tokens first so e.g. @SURFACE_2 isn't clobbered by @SURFACE
    for key in sorted(tokens, key=len, reverse=True):
        qss = qss.replace(key, tokens[key])
    return qss
