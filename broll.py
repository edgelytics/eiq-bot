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
    "NHL": ["ice hockey", "hockey game", "hockey player", "ice hockey puck", "hockey arena", "hockey",
            "hockey stick", "hockey goalie", "ice hockey game", "hockey match"],
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
                     params={"key": PIXABAY_KEY, "q": query, "per_page": 120, "safesearch": "true",
                             "video_type": "film"}, timeout=20)   # tag filter below keeps it on-topic
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
            # quality: what Pixabay users liked/downloaded, sharper files, and vertical clips (no heavy crop)
            q = (h.get("likes", 0) * 3 + h.get("downloads", 0) / 40 + h.get("views", 0) / 3000
                 + (40 if (f.get("height") or 0) >= 1080 else 0)
                 + (120 if (f.get("height") or 0) > (f.get("width") or 0) else 0)
                 + (20 if 8 <= h.get("duration", 0) <= 40 else 0))
            out.append((f"px{h['id']}", f["url"], q))
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
            out.append((f"pe{v['id']}", f["link"], 0))
    return out


def _search(queries, n, used, league):
    pool = []
    for q in queries:
        try:
            got = _pixabay(q, used, league) if PIXABAY_KEY else _pexels(q, used)
            print(f"[broll] '{q}': {len(got)} on-topic clips")
            pool += [c for c in got if c[0] not in {x[0] for x in pool}]
        except Exception as e:
            print(f"[broll] search '{q}' failed: {e}")
        if len(pool) >= n * 3:
            break
    return pool


def _download_pool(pool, n, folder):
    # best-quality clips first, then shuffle the top group so videos still look different
    pool = sorted(pool, key=lambda c: c[2], reverse=True)
    top = pool[:max(n * 3, 10)]
    random.shuffle(top)
    paths, ids = [], []
    for cid, url, _q in top:
        if cid in ids:
            continue
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


def fetch_clips(query, n=3, folder="cache/broll", league=None, used=()):
    """Returns (paths, clip_ids). Only on-topic clips for the game's sport; empty -> branded background.
    query may hold several searches separated by '|' (used when there's no league)."""
    if not (PIXABAY_KEY or PEXELS_KEY):
        return [], []
    os.makedirs(folder, exist_ok=True)
    used = set(used)
    queries = list(SPORT_QUERIES.get(league, []))
    random.shuffle(queries)
    if not queries:
        queries = [q.strip() for q in (query or "stadium lights").split("|") if q.strip()]
    pool = _search(queries, n, used, league)
    if len(pool) < n and used:
        # not enough fresh on-topic clips: top up with ones used before rather than go off-topic
        have = {c[0] for c in pool}
        older = [c for c in _search(queries, n, set(), league) if c[0] not in have]
        older.sort(key=lambda c: c[2], reverse=True)
        print(f"[broll] only {len(pool)} fresh clips — adding {min(len(older), n - len(pool))} reused")
        fresh_paths, fresh_ids = _download_pool(pool, n, folder) if pool else ([], [])
        old_paths, old_ids = _download_pool(older[:max(n - len(fresh_ids), 0) * 2], n - len(fresh_ids), folder)
        return fresh_paths + old_paths, fresh_ids + old_ids
    return _download_pool(pool, n, folder)


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
