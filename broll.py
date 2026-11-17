"""
broll.py — real background footage, different every video.

Sources (first one with a key wins):
  Pixabay  (PIXABAY_API_KEY, free, commercial use OK)  pixabay.com/api/docs
  Pexels   (PEXELS_API_KEY, if you ever get one)
The bot remembers clip IDs it already used (state file) so footage doesn't repeat.
"""
import os
import random
import subprocess
import requests
import numpy as np
from config import PEXELS_KEY

PIXABAY_KEY = os.environ.get("PIXABAY_API_KEY")
W, H, FPS = 1080, 1920, 30

FALLBACK_QUERIES = {
    "NFL": ["american football stadium", "football field night", "stadium lights", "football crowd", "american football"],
    "CFB": ["college football", "football stadium crowd", "marching band stadium", "stadium lights"],
    "NBA": ["basketball arena", "basketball court", "basketball hoop", "basketball game", "arena crowd"],
    "NHL": ["ice hockey", "hockey arena", "ice rink", "hockey game", "arena crowd"],
    "_":   ["stadium lights", "sports crowd cheering", "city night lights", "money counting", "scoreboard"],
}


def _download(url, path):
    with requests.get(url, stream=True, timeout=90) as d:
        d.raise_for_status()
        with open(path, "wb") as out:
            for chunk in d.iter_content(1 << 20):
                out.write(chunk)


def _pixabay(query, used):
    r = requests.get("https://pixabay.com/api/videos/",
                     params={"key": PIXABAY_KEY, "q": query, "per_page": 50, "safesearch": "true",
                             "video_type": "film", "order": "popular"}, timeout=20)
    r.raise_for_status()
    out = []
    for h in r.json().get("hits", []):
        if h.get("duration", 0) < 6 or f"px{h['id']}" in used:
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
    """Returns (paths, clip_ids). Empty if no key or nothing found."""
    if not (PIXABAY_KEY or PEXELS_KEY):
        return [], []
    os.makedirs(folder, exist_ok=True)
    used = set(used)
    queries = [query] + random.sample(FALLBACK_QUERIES.get(league, FALLBACK_QUERIES["_"]),
                                      k=min(3, len(FALLBACK_QUERIES.get(league, FALLBACK_QUERIES["_"]))))
    pool = []
    for q in queries:
        try:
            pool += _pixabay(q, used) if PIXABAY_KEY else _pexels(q, used)
        except Exception as e:
            print(f"[broll] search '{q}' failed: {e}")
        if len(pool) >= n * 4:
            break
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
