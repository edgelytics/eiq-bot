"""
motion.py — original animated backgrounds, drawn by the bot. No stock footage, nothing anyone else owns.

Four looks, all in the two teams' colors (+ EIQ green), picked per scene so every reel looks different:
  surface — the sport's playing surface (court / field / rink) in glowing lines, slow camera drift
  board   — a sportsbook-style odds board built from the game's REAL book lines, scrolling
  chart   — a glowing line chart drawing itself across a grid (trading-terminal look)
  glow    — giant team abbreviations drifting through colored light + particles

Each background behaves like a video clip for render.py: .next() returns a 1080x1920 RGB frame.
"""
import colorsys
import math
import os
import random

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H, FPS = 1080, 1920, 30
HERE = os.path.dirname(os.path.abspath(__file__))
EIQ_GREEN = (22, 163, 74)
BASE = (7, 7, 9)
STYLES = ["surface", "board", "chart", "glow"]


# ---------------- helpers ----------------
def _font(size, mono=False):
    names = ["LiberationMono-Bold.ttf"] if mono else ["LiberationSans-Bold.ttf", "Inter-Bold.ttf"]
    for d in [os.path.join(HERE, "fonts"), "/usr/share/fonts/truetype/liberation", "/usr/share/fonts/opentype/inter",
              "/usr/share/fonts/truetype/inter"]:
        for n in names:
            p = os.path.join(d, n)
            if os.path.exists(p):
                return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def _hex(c, default=EIQ_GREEN):
    try:
        c = (c or "").lstrip("#")
        return tuple(int(c[i:i + 2], 16) for i in (0, 2, 4))
    except Exception:
        return default


def _neon(rgb):
    """Make any team color bright enough to glow on black (dark navy -> electric blue, etc.)."""
    r, g, b = [x / 255 for x in rgb]
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    if s < 0.15:                      # grey/white/black team colors -> clean white-ish
        return (235, 235, 240)
    r, g, b = colorsys.hsv_to_rgb(h, max(s, 0.65), max(v, 0.9))
    return int(r * 255), int(g * 255), int(b * 255)


def _colors(game):
    g = game or {}
    a = _neon(_hex((g.get("away") or {}).get("color"), (59, 130, 246)))
    h = _neon(_hex((g.get("home") or {}).get("color"), (239, 68, 68)))
    if sum(abs(x - y) for x, y in zip(a, h)) < 90:       # same-ish colors: use the alt color for home
        h = _neon(_hex((g.get("home") or {}).get("alt_color"), EIQ_GREEN))
    return a, h


def _glow(img, radius=14, strength=1.6):
    """Neon glow: blurred copy added under the sharp lines."""
    blur = img.filter(ImageFilter.GaussianBlur(radius))
    a = np.asarray(img, np.float32) + np.asarray(blur, np.float32) * strength
    return Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))


def _ease(x):
    return 0.5 - 0.5 * math.cos(math.pi * max(0.0, min(1.0, x)))


class _Base:
    def __init__(self, game, seed):
        self.game = game or {}
        self.rng = random.Random(seed)
        self.ca, self.ch = _colors(game)
        self.fi = 0
        self.grain = np.random.default_rng(seed).integers(-5, 6, (H, W, 1), dtype=np.int16)

    def next(self):
        t = self.fi / FPS
        self.fi += 1
        fr = self.frame(t)
        return np.clip(fr.astype(np.int16) + self.grain, 0, 255).astype(np.uint8)

    def close(self):
        pass


# ---------------- 1) playing surface ----------------
class Surface(_Base):
    def __init__(self, game, seed):
        super().__init__(game, seed)
        lg = self.game.get("league", "NBA")
        BW, BH = 1500, 2700
        img = Image.new("RGB", (BW, BH), BASE)
        d = ImageDraw.Draw(img)
        line = (225, 228, 235)
        cx = BW // 2
        if lg in ("NFL", "CFB"):
            top, bot = 150, BH - 150
            left, right = 170, BW - 170
            span = (bot - top)
            d.rectangle([left, top, right, bot], outline=line, width=7)
            for k in range(0, 21):                         # yard lines every 5
                y = top + span * k / 20
                d.line([(left, y), (right, y)], fill=line, width=7 if k % 2 == 0 else 3)
                for hx in (left + 330, right - 330):        # hash marks
                    d.line([(hx - 18, y), (hx + 18, y)], fill=line, width=3)
            f = _font(110)
            for k, num in enumerate([10, 20, 30, 40, 50, 40, 30, 20, 10], start=1):
                y = top + span * (2 * k) / 20
                d.text((left + 70, y), str(num), font=f, fill=line, anchor="mm")
                d.text((right - 70, y), str(num), font=f, fill=line, anchor="mm")
            d.rectangle([left, top, right, top + span / 20 * 2], fill=tuple(int(c * 0.35) for c in self.ca), outline=line, width=7)
            d.rectangle([left, bot - span / 20 * 2, right, bot], fill=tuple(int(c * 0.35) for c in self.ch), outline=line, width=7)
        elif lg == "NHL":
            top, bot, left, right = 200, BH - 200, 230, BW - 230
            d.rounded_rectangle([left, top, right, bot], radius=330, outline=line, width=8)
            d.line([(left, BH // 2), (right, BH // 2)], fill=(230, 60, 60), width=16)
            for y in (BH // 2 - 520, BH // 2 + 520):
                d.line([(left, y), (right, y)], fill=self.ca if y < BH // 2 else self.ch, width=16)
            for y in (top + 260, bot - 260):
                d.line([(left + 60, y), (right - 60, y)], fill=(230, 60, 60), width=5)
            d.ellipse([cx - 230, BH // 2 - 230, cx + 230, BH // 2 + 230], outline=line, width=6)
            for (fx, fy) in [(cx - 360, BH // 2 - 900), (cx + 360, BH // 2 - 900), (cx - 360, BH // 2 + 900), (cx + 360, BH // 2 + 900)]:
                d.ellipse([fx - 190, fy - 190, fx + 190, fy + 190], outline=(230, 60, 60), width=5)
        else:                                               # basketball
            top, bot, left, right = 200, BH - 200, 200, BW - 200
            d.rectangle([left, top, right, bot], outline=line, width=8)
            d.line([(left, BH // 2), (right, BH // 2)], fill=line, width=8)
            d.ellipse([cx - 200, BH // 2 - 200, cx + 200, BH // 2 + 200], outline=line, width=8)
            for end, col in ((top, self.ca), (bot, self.ch)):
                s = 1 if end == top else -1
                lane = [cx - 260, min(end, end + s * 640), cx + 260, max(end, end + s * 640)]
                d.rectangle(lane, fill=tuple(int(c * 0.30) for c in col), outline=line, width=8)
                fy = end + s * 640
                d.ellipse([cx - 200, fy - 200, cx + 200, fy + 200], outline=line, width=8)
                # three-point arc
                ay = end + s * 170
                d.arc([cx - 880, ay - 880, cx + 880, ay + 880], 0 if s > 0 else 180, 180 if s > 0 else 360, fill=col, width=10)
                d.line([(cx - 880, end), (cx - 880, ay)], fill=col, width=10)
                d.line([(cx + 880, end), (cx + 880, ay)], fill=col, width=10)
                d.ellipse([cx - 30, end + s * 150 - 30, cx + 30, end + s * 150 + 30], outline=(255, 140, 40), width=8)
        f = _font(150)
        ab = (self.game.get("away") or {}).get("abbr", "")
        hb = (self.game.get("home") or {}).get("abbr", "")
        if ab: d.text((cx, BH * 0.28), ab, font=f, fill=self.ca, anchor="mm")
        if hb: d.text((cx, BH * 0.72), hb, font=f, fill=self.ch, anchor="mm")
        self.big = _glow(img, 18, 1.4)
        self.BW, self.BH = BW, BH
        self.dir = self.rng.choice([-1, 1])
        self.z0 = self.rng.uniform(1.0, 1.15)

    def frame(self, t):
        z = self.z0 + 0.012 * t                              # slow push-in
        cw, ch = W / z * 1.25, H / z * 1.25
        cx = self.BW / 2 + self.dir * 60 * math.sin(t * 0.25)
        cy = self.BH / 2 + self.dir * (self.BH - ch) * 0.45 * math.sin(t * 0.12)
        box = (cx - cw / 2, cy - ch / 2, cx + cw / 2, cy + ch / 2)
        im = self.big.transform((W, H), Image.EXTENT, box, Image.BILINEAR)
        return np.asarray(im)


# ---------------- 2) odds board (real lines) ----------------
class Board(_Base):
    @staticmethod
    def rows_for(game):
        f = (game or {}).get("facts") or {}
        lines = (f.get("sportsbook_lines") or {}).get("books") or []
        a = (game.get("away") or {}).get("abbr", "AWAY")
        h = (game.get("home") or {}).get("abbr", "HOME")
        rows = []
        for b in lines:
            hs, as_ = b.get("home_spread"), b.get("away_spread")
            if hs is None:
                continue
            fmt = lambda v: ("+" if v > 0 else "") + (f"{v:g}" if v else "PK")
            pr = lambda p: ("+" if (p or 0) > 0 else "") + str(p) if p is not None else ""
            rows.append((b.get("book", "").upper()[:10], f"{a} {fmt(as_)}", pr(b.get("away_price")),
                         f"{h} {fmt(hs)}", pr(b.get("home_price")), f"O/U {b.get('total'):g}" if b.get("total") else ""))
        return rows

    def __init__(self, game, seed):
        super().__init__(game, seed)
        rows = self.rows_for(self.game)
        self.rows = rows
        rh, pad = 190, 56
        n = max(len(rows), 1)
        block_h = n * rh
        reps = max(3, math.ceil((H * 2) / block_h) + 1)
        img = Image.new("RGB", (W, block_h * reps), BASE)
        d = ImageDraw.Draw(img)
        fb, fs, ft = _font(58, mono=True), _font(52, mono=True), _font(34, mono=True)
        for r in range(n * reps):
            y = r * rh
            row = rows[r % n]
            if (r % n) % 2 == 0:
                d.rectangle([0, y, W, y + rh], fill=(16, 17, 22))
            d.line([(0, y + rh - 1), (W, y + rh - 1)], fill=(40, 42, 52), width=2)
            d.text((pad, y + rh / 2 - 22), row[0], font=_font(44, mono=True), fill=EIQ_GREEN, anchor="lm")
            d.text((pad, y + rh / 2 + 32), row[5], font=ft, fill=(140, 142, 155), anchor="lm")
            d.text((430, y + rh / 2 - 38), row[1], font=fb, fill=self.ca, anchor="lm")
            d.text((W - pad, y + rh / 2 - 38), row[2], font=fs, fill=(225, 225, 232), anchor="rm")
            d.text((430, y + rh / 2 + 38), row[3], font=fb, fill=self.ch, anchor="lm")
            d.text((W - pad, y + rh / 2 + 38), row[4], font=fs, fill=(225, 225, 232), anchor="rm")
        self.big = np.asarray(_glow(img, 6, 0.8))
        self.block_h, self.rh = block_h, rh
        self.speed = self.rng.uniform(38, 55)                # px per second
        self.off0 = self.rng.uniform(0, block_h)

    def frame(self, t):
        off = int(self.off0 + t * self.speed) % self.block_h
        fr = self.big[off:off + H].copy()
        # a highlight bar sweeps down the board like a live update
        hy = int((t * 260) % (H + 400)) - 200
        y0, y1 = max(hy, 0), min(hy + self.rh, H)
        if y1 > y0:
            fr[y0:y1] = np.clip(fr[y0:y1].astype(np.int16) + np.array(EIQ_GREEN, np.int16) // 3, 0, 255).astype(np.uint8)
        return fr


# ---------------- 3) trading-terminal chart ----------------
class Chart(_Base):
    def __init__(self, game, seed):
        super().__init__(game, seed)
        grid = Image.new("RGB", (W, H), BASE)
        d = ImageDraw.Draw(grid)
        for x in range(0, W, 108): d.line([(x, 0), (x, H)], fill=(22, 24, 30), width=2)
        for y in range(0, H, 108): d.line([(0, y), (W, y)], fill=(22, 24, 30), width=2)
        self.grid = np.asarray(grid)
        # two series (one per team) as smooth random walks; purely decorative, no axis values
        self.series = []
        for col, base in ((self.ca, 0.36), (self.ch, 0.64)):
            v, vel, pts = base, 0.0, []
            for i in range(48):
                vel = vel * 0.6 + self.rng.gauss(0, 0.026)
                v = min(0.85, max(0.15, v + vel + (base - v) * 0.08))
                pts.append(v)
            self.series.append((col, pts))
        lay = Image.new("RGB", (W, H), (0, 0, 0))
        dl = ImageDraw.Draw(lay)
        fill = Image.new("RGB", (W, H), (0, 0, 0))
        df = ImageDraw.Draw(fill)
        for col, pts in self.series:
            xy = [(int(i / (len(pts) - 1) * W), int(p * H)) for i, p in enumerate(pts)]
            df.polygon(xy + [(W, H), (0, H)], fill=tuple(int(c * 0.10) for c in col))
            dl.line(xy, fill=col, width=14, joint="curve")
        self.lines = (np.asarray(_glow(lay, 22, 1.9)).astype(np.int16) + np.asarray(fill).astype(np.int16))
        self.xy = [[(int(i / (len(p) - 1) * W), int(v * H)) for i, v in enumerate(p)] for _, p in self.series]
        self.dur = self.rng.uniform(3.0, 4.2)

    def frame(self, t):
        prog = _ease((t % (self.dur + 1.5)) / self.dur)
        cut = max(2, int(prog * W))
        fr = self.grid.astype(np.int16).copy()
        fr[:, :cut] += self.lines[:, :cut]
        # glowing head dots
        for (col, _), pts in zip(self.series, self.xy):
            i = min(int(prog * (len(pts) - 1)), len(pts) - 1)
            x, y = pts[i]
            y0, y1, x0, x1 = max(y - 22, 0), min(y + 22, H), max(x - 22, 0), min(x + 22, W)
            fr[y0:y1, x0:x1] += np.array(col, np.int16) // 2
        return np.clip(fr, 0, 255).astype(np.uint8)


# ---------------- 4) team glow ----------------
class Glow(_Base):
    def __init__(self, game, seed):
        super().__init__(game, seed)
        self.lw, self.lh = 135, 240
        yy, xx = np.mgrid[0:self.lh, 0:self.lw]
        self.xx, self.yy = xx / self.lw, yy / self.lh
        a = (self.game.get("away") or {}).get("abbr", "")
        h = (self.game.get("home") or {}).get("abbr", "")
        txt = Image.new("RGB", (W * 3, 900), (0, 0, 0))
        d = ImageDraw.Draw(txt)
        f = _font(620)
        x = 0
        for word, col in [(a, self.ca), ("VS", (60, 62, 70)), (h, self.ch)] * 2:
            if not word:
                continue
            d.text((x, 450), word, font=f, fill=tuple(int(c * 0.55) for c in col), anchor="lm",
                   stroke_width=8, stroke_fill=col)
            x += int(d.textlength(word, font=f)) + 160
        self.txt = np.asarray(txt.crop((0, 0, max(x, W + 10), 900))).astype(np.int16)
        self.tw = self.txt.shape[1]
        r = random.Random(seed)
        self.parts = [(r.uniform(0, W), r.uniform(0, H), r.uniform(20, 70), r.uniform(2, 6), r.choice([self.ca, self.ch, EIQ_GREEN]))
                      for _ in range(40)]
        self.ty = r.choice([380, 760, 1150])

    def frame(self, t):
        def blob(cx, cy, rr):
            return np.exp(-(((self.xx - cx) ** 2) / rr + ((self.yy - cy) ** 2) / (rr * 0.6)))
        b1 = blob(0.2 + 0.2 * math.sin(t * 0.4), 0.3 + 0.1 * math.cos(t * 0.3), 0.08)
        b2 = blob(0.8 + 0.2 * math.cos(t * 0.35), 0.7 + 0.1 * math.sin(t * 0.25), 0.08)
        small = (np.array(BASE, float)[None, None] + b1[..., None] * np.array(self.ca) * 0.55
                 + b2[..., None] * np.array(self.ch) * 0.55)
        fr = np.asarray(Image.fromarray(np.clip(small, 0, 255).astype(np.uint8)).resize((W, H), Image.BILINEAR)).astype(np.int16)
        off = int(t * 90) % max(self.tw - W, 1)
        y = self.ty
        fr[y:y + 900] += self.txt[:, off:off + W][: H - y]
        for (px, py, rad, sp, col) in self.parts:
            yy = int((py - t * sp * 25) % H)
            xx = int(px + 20 * math.sin(t + px))
            r = int(rad / 6)
            fr[max(yy - r, 0):yy + r, max(xx - r, 0):xx + r] += np.array(col, np.int16) // 3
        return np.clip(fr, 0, 255).astype(np.uint8)


CLASSES = {"surface": Surface, "board": Board, "chart": Chart, "glow": Glow}


def make_backgrounds(game, n=4, seed=None):
    """n animated backgrounds for one reel, different looks in a shuffled order."""
    seed = seed if seed is not None else random.randrange(1 << 30)
    r = random.Random(seed)
    g = game or {}
    has_teams = bool((g.get("away") or {}).get("abbr"))
    styles = list(STYLES) if has_teams else ["chart", "surface"]   # lesson reels: no team-specific looks
    if "board" in styles and not Board.rows_for(g):
        styles.remove("board")                               # never show an empty/fake odds board
    r.shuffle(styles)
    picks = (styles * n)[:n]
    print(f"[motion] backgrounds: {', '.join(picks)}")
    return [CLASSES[s](game, seed + i) for i, s in enumerate(picks)], [f"motion:{s}" for s in picks]
