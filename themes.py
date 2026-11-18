"""
themes.py — the looks a reel can have. The bot rotates through them (least recently used first)
unless the dashboard pins one (repo variable EIQ_THEME).

Each theme sets:
  accent   main highlight color (bars, labels, best-price row, logo glow)
  cap_hi   color of the word being spoken in the captions
  bg       dark base color (cards, gradient background)
  head     headline / caption font (in fonts/; falls back to Inter Black)
  caption  "stroke" (outlined words) | "box" (dark pill behind words) | "box_white" (white pill, black words)
  cap_size caption font size
  hook     "left" or "center" aligned opening title
  shade    how much to darken background footage (0-255)
  tint     color grade laid over the footage (r, g, b, alpha) or None
"""

THEMES = {
    "eiq": {
        "name": "EIQ Classic (green)", "accent": (22, 163, 74), "cap_hi": (22, 163, 74), "bg": (7, 7, 7),
        "head": "Inter-Black.otf", "caption": "stroke", "cap_size": 92, "hook": "left", "shade": 105, "tint": None,
    },
    "neon": {
        "name": "Neon Night (cyan/yellow)", "accent": (34, 211, 238), "cap_hi": (250, 204, 21), "bg": (6, 8, 22),
        "head": "Anton-Regular.ttf", "caption": "stroke", "cap_size": 104, "hook": "center", "shade": 120,
        "tint": (30, 10, 70, 70),
    },
    "gold": {
        "name": "Gold Rush (black & gold)", "accent": (250, 204, 21), "cap_hi": (250, 204, 21), "bg": (12, 10, 5),
        "head": "ArchivoBlack-Regular.ttf", "caption": "box", "cap_size": 80, "hook": "left", "shade": 115,
        "tint": (45, 28, 0, 45),
    },
    "heat": {
        "name": "Heat Check (orange)", "accent": (249, 115, 22), "cap_hi": (250, 204, 21), "bg": (14, 7, 4),
        "head": "BebasNeue-Regular.ttf", "caption": "stroke", "cap_size": 124, "hook": "center", "shade": 110,
        "tint": (70, 15, 0, 50),
    },
    "clean": {
        "name": "Clean Card (white captions)", "accent": (22, 163, 74), "cap_hi": (22, 163, 74), "bg": (7, 7, 7),
        "head": "Inter-Black.otf", "caption": "box_white", "cap_size": 80, "hook": "left", "shade": 150, "tint": None,
    },
}
DEFAULT = "eiq"


def get(key):
    return THEMES.get(key) or THEMES[DEFAULT]
