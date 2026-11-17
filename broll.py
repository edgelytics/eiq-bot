"""
broll.py — real background footage from Pexels (free, commercial use allowed).
Get a free key at https://www.pexels.com/api/ and set PEXELS_API_KEY.
"""
import os
import subprocess
import requests
import numpy as np
from config import PEXELS_KEY

W, H, FPS = 1080, 1920, 30


def fetch_clips(query, n=3, folder="cache/broll"):
    if not PEXELS_KEY:
        return []
    os.makedirs(folder, exist_ok=True)
    try:
        r = requests.get("https://api.pexels.com/videos/search",
                         params={"query": query, "orientation": "portrait", "per_page": 15, "size": "medium"},
                         headers={"Authorization": PEXELS_KEY}, timeout=20)
        r.raise_for_status()
        vids = r.json().get("videos", [])
    except Exception as e:
        print(f"[broll] search failed: {e}")
        return []
    paths = []
    for v in vids:
        if v.get("duration", 0) < 5:
            continue
        files = [f for f in v.get("video_files", []) if f.get("height") and f["height"] >= 1280 and f.get("file_type") == "video/mp4"]
        if not files:
            continue
        f = min(files, key=lambda f: abs(f["height"] - 1920))
        p = os.path.join(folder, f"{v['id']}.mp4")
        if not os.path.exists(p):
            try:
                with requests.get(f["link"], stream=True, timeout=60) as d:
                    d.raise_for_status()
                    with open(p, "wb") as out:
                        for chunk in d.iter_content(1 << 20):
                            out.write(chunk)
            except Exception as e:
                print(f"[broll] download failed: {e}")
                continue
        paths.append(p)
        if len(paths) >= n:
            break
    return paths


class ClipReader:
    """Streams a clip as 1080x1920 darkened frames, looping forever."""
    def __init__(self, path):
        self.p = subprocess.Popen(
            ["ffmpeg", "-loglevel", "error", "-stream_loop", "-1", "-i", path, "-an",
             "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS},"
                    "eq=brightness=-0.18:saturation=0.55:contrast=1.05",
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
