"""
config.py — every knob in one place.
"""
import os

# ---------- schedule (local time) ----------
TIMEZONE = "America/Chicago"
SCAN_LEAD_MINUTES = 20            # start scanning/building this long before post time
SLOTS = [
    {"name": "midday",    "post": "11:30",
     "angle": "Teach ONE betting concept (key numbers, line shopping, vig, closing line value) using a real game on today's slate as the example."},
    {"name": "afternoon", "post": "16:30",
     "angle": "Matchup breakdown: what the number implies and where casual bettors get this game wrong."},
    {"name": "primetime", "post": "19:30",
     "angle": "Tonight's biggest game: the number, the public trap, and the disciplined way to approach it."},
]

# ---------- leagues to scan ----------
LEAGUES = ["NFL", "NBA", "CFB", "NHL"]

# ---------- brand ----------
HANDLE = "@edgelytics.iq"
BG = (7, 7, 7)
GREEN = (22, 163, 74)
DISCLAIMER = "21+ · Gambling problem? Call 1-800-GAMBLER"

# ---------- voice (Kokoro, free & local) ----------
KOKORO_MODEL = os.environ.get("KOKORO_MODEL", "models/kokoro-v1.0.int8.onnx")
KOKORO_VOICES = os.environ.get("KOKORO_VOICES", "models/voices-v1.0.bin")
VOICE = os.environ.get("EIQ_VOICE", "am_michael")   # try am_fenrir, am_puck, af_heart
VOICE_SPEED = 1.2

# ---------- Instagram music (attached at post time via the Audio API) ----------
IG_MUSIC_VOLUME = 22     # 1-100, how loud the Instagram track sits under the voice
IG_VIDEO_VOLUME = 100    # 1-100, your voiceover/SFX track

# ---------- optional services ----------
CLAUDE_MODEL = "claude-sonnet-5-5"
PEXELS_KEY = os.environ.get("PEXELS_API_KEY")          # free at pexels.com/api — real B-roll footage
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL")  # post notifications
IG_USER_ID = os.environ.get("IG_USER_ID")
IG_TOKEN = os.environ.get("IG_ACCESS_TOKEN")
GRAPH_VERSION = "v22.0"

# Safety switches
AUTOPOST = os.environ.get("AUTOPOST", "true").lower() == "true"   # set false = build + notify only
DRY_RUN = os.environ.get("DRY_RUN", "false").lower() == "true"
