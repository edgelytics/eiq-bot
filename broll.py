"""
broll.py — real background footage, different every video.

Sources (first one with a key wins):
  Pixabay  (PIXABAY_API_KEY, free, commercial use OK)  pixabay.com/api/docs
  Pexels   (PEXELS_API_KEY, if you ever get one)
The bot remembers clip IDs it already used (state file) so footage doesn't repeat.
"""
import os
import random
import re
import subprocess
import requests
import numpy as np
from config import PEXELS_KEY

PIXABAY_KEY = os.environ.get("PIXABAY_API_KEY")
W, H, FPS = 1080, 1920, 30

# Searches per sport (all on-topic). The bot rotates through these.
SPORT_QUERIES = {
    "NFL": ["american football", "american football game", "football stadium", "quarterback", "touchdown", "american football field"],
    "CFB": ["american football", "college football", "football stadium", "american football game", "touchdown"],
    "NBA": ["basketball", "basketball game", "basketball dunk", "basketball court", "basketball player", "basketball hoop"],
    "NHL": ["ice hockey", "hockey game", "hockey player", "ice hockey puck", "hockey arena"],
}
# A clip must carry at least one of these tags to be used...
REQUIRED_TAGS = {
    "NFL": ["american football", "nfl", "quarterback", "touchdown", "gridiron", "football helmet"],
    "CFB": ["american football", "quarterback", "touchdown", "gridiron", "football helmet", "college football"],
    "NBA": ["basketball", "nba", "dunk", "slam dunk"],
    "NHL": ["hockey", "ice hockey", "nhl", "puck"],
}
# ...and none of these.
BANNED_TAGS = {
    "NFL": ["soccer", "rugby", "futsal", "fifa", "messi", "goalkeeper"],
    "CFB": ["soccer", "rugby", "futsal", "fifa", "goalkeeper"],
    "NBA": ["netball", "volleyball"],
    "NHL": ["field hockey", "figure skating"],
}
ALWAYS_BANNED = ["wedding", "christmas", "baby", "cat", "dog", "food", "nature", "beach", "flower", "concert",
                 "dance", "yoga", "fitness", "gym", "kids", "children", "toy", "cartoon", "animation", "3d"]


def _on_topic(tags, league):
    t = " " + re.sub(r"[^a-z0-9 ]+", " ", (tags or "").lower()) + " "
    has = lambda w: f" {w} " in t          # whole-word / whole-phrase match
    if any(has(b) for b in ALWAYS_BANNED + BANNED_TAGS.get(league, [])):
        return False
    req = REQUIRED_TAGS.get(league)
    return any(has(r) for r in req) if req else True


def _download(url, path):
    with requests.get(url, stream=True, timeout=90) as d:
        d.raise_for_status()
        with open(path, "wb") as out:
            for chunk in d.iter_content(1 << 20):
                out.write(chunk)


def _pixabay(query, used, league=None):
    r = requests.get("https://pixabay.com/api/videos/",
                     params={"key": PIXABAY_KEY, "q": query, "per_page": 80, "safesearch": "true",
                             "video_type": "film", "category": "sports"}, timeout=20)
    r.raise_for_status()
    out = []
    for h in r.json().get("hits", []):
        if h.get("duration", 0) < 5 or f"px{h['id']}" in used:
            continue
        if not _on_topic(h.get("tags"), league):
            continue
        v = h.get("videos", {})
        f = v.get("large") if (v.get("large") or {}).get("url") else v.get("medium")
        if f and f.get("url") and (f.get("height") or 0) >= 720:
            out.append((f"px{h['id']}", f["url"]))
    return out


def _pexels(query, used):
    r = requests.get("https://api.pexels.com/videos/search",
                     params={"query": query, "orientation": "portrait", "per_page": 40, "size": "medium"},
                     headers={"Authorization": PEXELS_KEY}, timeout=20)
    r.raise_for_status()
    out = []
    for v in r.json().get("videos", []):
        if v.get("duration", 0) < 5 or f"pe{v['id']}" in used:
            continue
        files = [f for f in v.get("video_files", []) if (f.get("height") or 0) >= 1280 and f.get("file_type") == "video/mp4"]
        if files:
            f = min(files, key=lambda f: abs(f["height"] - 1920))
            out.append((f"pe{v['id']}", f["link"]))
    return out


def fetch_clips(query, n=3, folder="cache/broll", league=None, used=()):
    """Returns (paths, clip_ids). Only on-topic clips for the game's sport; empty -> branded background."""
    if not (PIXABAY_KEY or PEXELS_KEY):
        return [], []
    os.makedirs(folder, exist_ok=True)
    used = set(used)
    queries = list(SPORT_QUERIES.get(league, []))
    random.shuffle(queries)
    if not queries:
        queries = [query]
    pool = []
    for q in queries:
        try:
            got = _pixabay(q, used, league) if PIXABAY_KEY else _pexels(q, used)
            print(f"[broll] '{q}': {len(got)} on-topic clips")
            pool += got
        except Exception as e:
            print(f"[broll] search '{q}' failed: {e}")
        if len(pool) >= n * 3:
            break
    if not pool and used:
        # every on-topic clip has been used before: allow repeats rather than go off-topic
        return fetch_clips(query, n, folder, league, used=())
    random.shuffle(pool)
    paths, ids, seen = [], [], set()
    for cid, url in pool:
        if cid in seen:
            continue
        seen.add(cid)
        p = os.path.join(folder, f"{cid}.mp4")
        try:
            if not os.path.exists(p):
                _download(url, p)
            paths.append(p); ids.append(cid)
        except Exception as e:
            print(f"[broll] download failed: {e}")
        if len(paths) >= n:
            break
    return paths, ids


class ClipReader:
    """Streams a clip as 1080x1920 darkened frames (center-cropped), looping forever."""
    def __init__(self, path):
        self.p = subprocess.Popen(
            ["ffmpeg", "-loglevel", "error", "-stream_loop", "-1", "-i", path, "-an",
             "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS},"
                    "eq=brightness=-0.22:saturation=0.6:contrast=1.08",
             "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
            stdout=subprocess.PIPE)
        self.size = W * H * 3

    def next(self):
        buf = self.p.stdout.read(self.size)
        if len(buf) < self.size:
            return None
        return np.frombuffer(buf, np.uint8).reshape(H, W, 3)

    def close(self):
        self.p.kill()
