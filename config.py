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

# Which slots actually post. Owner (Nov 25, 2026): quality over volume, 1 reel a day at primetime.
# Add "midday" / "afternoon" back here to post more often. Forced runs from the dashboard still work for any slot.
ACTIVE_SLOTS = ["primetime"]

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
VOICE = "am_michael"                                  # default / fallback voice
VOICE_SPEED = 1.2
# The bot rotates through these (least recently used first). Name shown on the dashboard.
VOICES = {
    "am_michael": "Michael (deep, confident)",
    "am_fenrir":  "Fenrir (punchy hype)",
    "am_puck":    "Puck (energetic)",
    "am_onyx":    "Onyx (smooth, low)",
    "af_heart":   "Heart (warm female)",
    "af_bella":   "Bella (bright female)",
}
VOICE_CHOICE = os.environ.get("EIQ_VOICE", "auto") or "auto"   # dashboard: "auto" rotates, or pin one voice
THEME_CHOICE = os.environ.get("EIQ_THEME", "auto") or "auto"   # dashboard: "auto" rotates, or pin one design
# Backgrounds: "motion" = the bot's own animated graphics (motion.py, default since Nov 25, 2026),
# "mix" = motion + 1 stock clip, "stock" = Pixabay footage only. Override with repo variable EIQ_BROLL.
BROLL_MODE = (os.environ.get("EIQ_BROLL") or "motion").lower()

# ---------- explainer / promo reels (evergreen "how to" videos that plug Edgelytics IQ) ----------
EXPLAINER_SLOT = "primetime"      # which slot can turn into an explainer
EXPLAINER_EVERY_N_DAYS = 3        # 3 = every third day; 1 = every day; 0 = never (unless forced)
KIND_CHOICE = os.environ.get("EIQ_KIND", "auto") or "auto"     # auto | game | explainer (forced run)
TOPIC_CHOICE = os.environ.get("EIQ_TOPIC", "") or ""            # explainer topic id, blank = next in rotation

# ---------- Instagram music (attached at post time via the Audio API) ----------
IG_MUSIC_VOLUME = 15     # 1-100, how loud the Instagram track sits under the voice (owner: 22 was a bit loud)
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
