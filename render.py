"""
render.py — the video engine. 1080x1920 @30fps.

Layers per frame:
  background (Pexels B-roll, or animated team-color gradient) ->
  scene graphics (kinetic type, VS cards, line-movement chart, key-number line) ->
  camera punch-zoom + flash cuts ->
  word-by-word captions synced to the voiceover -> progress bar / brand tag
"""
import math
import os
import subprocess
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

from config import GREEN, BG, HANDLE, DISCLAIMER
from broll import ClipReader

W, H, FPS = 1080, 1920, 30
HERE = os.path.dirname(os.path.abspath(__file__))
WHITE = (255, 255, 255)
GREY = (175, 175, 175)
BLACK = (0, 0, 0)

_fc = {}
FONT_DIRS = [os.path.join(HERE, "fonts"), "/usr/share/fonts/opentype/inter",
             "/usr/share/fonts/truetype/liberation", "/usr/share/fonts/truetype/inter"]

def font(name, size):
    key = (name, size)
    if key not in _fc:
        for d in FONT_DIRS:
            p = os.path.join(d, name)
            if os.path.exists(p):
                _fc[key] = ImageFont.truetype(p, size); break
        else:
            _fc[key] = ImageFont.truetype("DejaVuSans-Bold.ttf", size)
    return _fc[key]

BLACKF = "Inter-Black.otf"
XBOLD = "Inter-ExtraBold.otf"
BOLD = "LiberationSans-Bold.ttf"
REG = "LiberationSans-Regular.ttf"
MONO = "LiberationMono-Bold.ttf"


# ---------------- helpers ----------------
def ease_out(t):
    t = min(1.0, max(0.0, t)); return 1 - (1 - t) ** 3

def ease_back(t, s=1.9):
    t = min(1.0, max(0.0, t)); t -= 1; return t * t * ((s + 1) * t + s) + 1

def hex_rgb(h):
    h = (h or "").lstrip("#")
    try:
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    except ValueError:
        return GREEN

def lum(c):
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]

def vivid(c, min_l=70):
    """Team colors like navy are too dark on black — lift them."""
    c = np.array(c, float); l = lum(c)
    if l < min_l:
        c = c + (min_l - l) * 1.2
    return tuple(int(min(255, v)) for v in c)

def A(c, a):
    return (c[0], c[1], c[2], int(max(0, min(255, a))))

def reveal(t, delay, dur=0.4):
    p = ease_out((t - delay) / dur)
    return p, (1 - p) * 70


def text_img(txt, fnt, fill, stroke=6, stroke_fill=(0, 0, 0, 230)):
    """Render text to a tight RGBA image (so it can be scaled / rotated cheaply)."""
    l, t, r, b = fnt.getbbox(txt, stroke_width=stroke)
    im = Image.new("RGBA", (r - l + 4, b - t + 4), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((2 - l, 2 - t), txt, font=fnt, fill=fill, stroke_width=stroke, stroke_fill=stroke_fill)
    return im


def paste_scaled(layer, im, cx, cy, scale=1.0, alpha=1.0, anchor="mm"):
    if alpha <= 0.01 or scale <= 0.01:
        return
    if abs(scale - 1) > 0.01:
        im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))), Image.BILINEAR)
    if alpha < 0.99:
        a = im.getchannel("A").point(lambda v: int(v * alpha)); im = im.copy(); im.putalpha(a)
    if anchor == "mm":
        x, y = int(cx - im.width / 2), int(cy - im.height / 2)
    elif anchor == "lm":
        x, y = int(cx), int(cy - im.height / 2)
    else:  # "lt"
        x, y = int(cx), int(cy)
    layer.alpha_composite(im, (max(0, x), max(0, y)), (max(0, -x), max(0, -y)))


# ---------------- backgrounds ----------------
class GradientBG:
    """Animated blobs in both team colors + grain + faint grid. Used when no B-roll."""
    def __init__(self, c1, c2):
        self.c1, self.c2 = np.array(vivid(c1, 60), float), np.array(vivid(c2, 60), float)
        self.lw, self.lh = 135, 240
        yy, xx = np.mgrid[0:self.lh, 0:self.lw]
        self.xx, self.yy = xx / self.lw, yy / self.lh
        rng = np.random.default_rng(1)
        self.grain = [rng.integers(-6, 7, (H, W, 1), dtype=np.int16) for _ in range(1)]
        g = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(g)
        for x in range(0, W, 90): d.line([(x, 0), (x, H)], fill=(255, 255, 255, 10))
        for y in range(0, H, 90): d.line([(0, y), (W, y)], fill=(255, 255, 255, 10))
        self.grid = g

    def frame(self, t, fi):
        def blob(cx, cy, r):
            return np.exp(-(((self.xx - cx) ** 2) / r + ((self.yy - cy) ** 2) / (r * 0.6)))
        b1 = blob(0.25 + 0.15 * math.sin(t * 0.5), 0.25 + 0.10 * math.cos(t * 0.4), 0.10)
        b2 = blob(0.75 + 0.15 * math.cos(t * 0.45), 0.72 + 0.10 * math.sin(t * 0.35), 0.10)
        b3 = blob(0.5 + 0.3 * math.sin(t * 0.3), 0.5, 0.05)
        img = (np.array(BG, float)[None, None] + b1[..., None] * self.c1 * 0.55 + b2[..., None] * self.c2 * 0.55
               + b3[..., None] * np.array(GREEN, float) * 0.18)
        im = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).resize((W, H), Image.BILINEAR)
        arr = np.asarray(im).astype(np.int16) + self.grain[0]
        im = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8)).convert("RGBA")
        im.alpha_composite(self.grid)
        return im


def vignette():
    yy, xx = np.mgrid[0:H, 0:W]
    d = np.sqrt(((xx - W / 2) / (W * 0.75)) ** 2 + ((yy - H / 2) / (H * 0.62)) ** 2)
    a = np.clip((d - 0.45) * 1.4, 0, 0.85)
    # extra darkening in caption zone + top for legibility
    a = np.maximum(a, np.clip((yy - 1250) / 500, 0, 0.55))
    v = np.zeros((H, W, 4), np.uint8); v[..., 3] = (a * 255).astype(np.uint8)
    return Image.fromarray(v, "RGBA")


# ---------------- scenes ----------------
def draw_hook(L, t, sc, g):
    d = ImageDraw.Draw(L)
    p, off = reveal(t, 0.0, 0.3)
    net = (g.get("networks") or [None])[0] if g else None
    tag = " · ".join(x for x in (g["league"], net.upper() if net else None, g.get("when", "tonight").upper()) if x) if g else "EDGELYTICS IQ"
    d.text((80, 470 + off), tag, font=font(MONO, 40), fill=A(GREEN, 255 * p))
    words = sc["text"].upper().split()
    accent = (sc.get("accent") or "").upper().strip(".,!?")
    f = font(BLACKF, 138)
    lines, cur = [], []
    for w in words:
        if cur and len(" ".join(cur + [w])) > 11:
            lines.append(cur); cur = []
        cur.append(w)
    lines.append(cur)
    y = 560; k = 0
    for ln in lines:
        x = 80
        for w in ln:
            t0 = 0.08 + k * 0.13
            q = (t - t0) / 0.18
            if q > 0:
                sc_ = 1.0 + 0.6 * (1 - ease_out(q))
                col = A(GREEN, 255) if w.strip(".,!?") == accent else A(WHITE, 255)
                im = text_img(w, f, col, 7)
                jit = (math.sin(t * 90) * 8 * max(0, 1 - q * 1.5))
                paste_scaled(L, im, x + jit, y + im.height / 2, sc_, min(1, q * 2), "lm")
            x += f.getlength(w + " ")
            k += 1
        y += 150
    bar = ease_out((t - 0.15 - k * 0.13) / 0.4)
    d.rectangle([80, y + 20, 80 + int(560 * bar), y + 38], fill=A(GREEN, 255))


def draw_matchup(L, t, sc, g):
    d = ImageDraw.Draw(L)
    for i, side in enumerate(["away", "home"]):
        tm = g[side]; col = vivid(hex_rgb(tm["color"]), 55)
        p = ease_out((t - 0.05 - i * 0.18) / 0.45)
        dx = (1 - p) * (-1100 if i == 0 else 1100)
        y0 = 330 + i * 360
        d.rounded_rectangle([80 + dx, y0, 1000 + dx, y0 + 320], radius=28, fill=A(col, 215 * p))
        d.rectangle([80 + dx, y0 + 24, 92 + dx, y0 + 296], fill=A(GREEN, 255 * p))
        d.text((130 + dx, y0 + 36), "AWAY" if i == 0 else "HOME", font=font(MONO, 34), fill=A(WHITE, 200 * p))
        d.text((126 + dx, y0 + 80), tm["abbr"], font=font(BLACKF, 170), fill=A(WHITE, 255 * p))
        nm = tm["short"].upper(); fs = 54
        while fs > 30 and font(XBOLD, fs).getlength(nm) > 380:
            fs -= 2
        d.text((600 + dx, y0 + 140 + (54 - fs) // 2), nm, font=font(XBOLD, fs), fill=A(WHITE, 255 * p))
        d.text((600 + dx, y0 + 210), tm["record"], font=font(BOLD, 46), fill=A(WHITE, 190 * p))
    q = (t - 0.55) / 0.3
    if q > 0:
        im = Image.new("RGBA", (150, 150), (0, 0, 0, 0)); di = ImageDraw.Draw(im)
        di.ellipse([0, 0, 149, 149], fill=A(BG, 255), outline=A(GREEN, 255), width=6)
        di.text((75, 75), "@", font=font(BLACKF, 70), fill=A(WHITE, 255), anchor="mm")
        paste_scaled(L, im, 540, 670, ease_back(q), 1)
    chips = [("PUCK LINE" if g.get("league") == "NHL" else "SPREAD", g.get("spread_text") or "PK", None), ("TOTAL", None, g.get("total"))]
    for i, (k, txt, num) in enumerate(chips):
        p, off = reveal(t, 0.8 + i * 0.15, 0.35)
        if p <= 0: continue
        x0, y0 = 80 + i * 470, 1040 + off
        d.rounded_rectangle([x0, y0, x0 + 450, y0 + 190], radius=26, fill=A(BG, 200 * p), outline=A(GREEN, 255 * p), width=5)
        d.text((x0 + 34, y0 + 26), k, font=font(MONO, 34), fill=A(GREEN, 255 * p))
        if num is not None:
            v = num * ease_out((t - 0.8 - i * 0.15) / 0.7)
            txt = f"O/U {v:.1f}"
        d.text((x0 + 32, y0 + 78), txt, font=font(BLACKF, 78), fill=A(WHITE, 255 * p))


def draw_number(L, t, sc, g):
    d = ImageDraw.Draw(L)
    p, off = reveal(t, 0.0, 0.3)
    d.text((80, 330 + off), (sc.get("label") or "THE NUMBER").upper(), font=font(MONO, 44), fill=A(GREEN, 255 * p))
    o, n = (g or {}).get("spread_open"), (g or {}).get("spread_now")
    fav = (g.get("spread_text") or "").split()[0] if g and g.get("spread_text") else ""
    if o is not None and n is not None and o != n:
        # ---- line movement chart: OPEN -> NOW ----
        x0, x1, ya, yb = 140, 940, 520, 1000
        d.rounded_rectangle([80, 440, 1000, 1240], radius=30, fill=A(BG, 170 * p), outline=A((255, 255, 255), 40 * p), width=2)
        lo, hi = min(o, n) - 1.5, max(o, n) + 1.5
        Y = lambda v: ya + (v - lo) / (hi - lo) * (yb - ya)    # more negative = higher on screen
        for v in np.arange(math.ceil(lo), math.floor(hi) + 1):
            d.line([(x0, Y(v)), (x1, Y(v))], fill=A(WHITE, 28 * p), width=2)
            d.text((x1 + 10, Y(v) - 16), f"{v:+g}", font=font(MONO, 28), fill=A(GREY, 160 * p))
        pts = [(x0, Y(o)), (x0 + 260, Y(o)), (x0 + 330, Y((o + n) / 2)), (x0 + 520, Y((o + n) / 2)), (x0 + 600, Y(n)), (x1, Y(n))]
        prog = ease_out((t - 0.3) / 1.4)
        seg_len = [math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]
        tot = sum(seg_len) * prog; drawn = [pts[0]]
        for i, sl in enumerate(seg_len):
            if tot <= 0: break
            f = min(1, tot / sl); a, b = pts[i], pts[i + 1]
            drawn.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)); tot -= sl
        d.line(drawn, fill=A(GREEN, 255), width=10, joint="curve")
        hx, hy = drawn[-1]
        pulse = 18 + 6 * math.sin(t * 10)
        d.ellipse([hx - pulse, hy - pulse, hx + pulse, hy + pulse], fill=A(GREEN, 90))
        d.ellipse([hx - 11, hy - 11, hx + 11, hy + 11], fill=A(WHITE, 255))
        d.text((x0, 1040), "OPEN", font=font(MONO, 34), fill=A(GREY, 255 * p))
        d.text((x0, 1085), f"{fav} {o:+g}".strip(), font=font(BLACKF, 72), fill=A(WHITE, 255 * p))
        q = (t - 1.5) / 0.35
        if q > 0:
            d.text((600, 1040), "NOW", font=font(MONO, 34), fill=A(GREEN, 255 * min(1, q)))
            d.text((600, 1085), f"{fav} {n:+g}".strip(), font=font(BLACKF, 72), fill=A(GREEN, 255 * min(1, q)))
            badge = text_img(f"MOVED {abs(n - o):.1f} PTS", font(BLACKF, 50), A(BG, 255), 0)
            bg = Image.new("RGBA", (badge.width + 50, badge.height + 34), A(GREEN, 255))
            bg.alpha_composite(badge, (25, 17))
            paste_scaled(L, bg, 540, 470, ease_back(q), 1)
    elif g and g["league"] in ("NFL", "CFB") and g.get("spread") is not None:
        # ---- football key-number line ----
        s = abs(g["spread"]); lo, hi = max(0, math.floor(s) - 4), math.floor(s) + 5
        X = lambda v: 110 + (v - lo) / (hi - lo) * 860
        y = 820
        d.line([(110, y), (970, y)], fill=A(WHITE, 160 * p), width=4)
        for v in range(lo, hi + 1):
            key = v in (3, 7, 10, 14)
            q = ease_out((t - 0.2 - (v - lo) * 0.05) / 0.3)
            hgt = 70 if key else 26
            d.line([(X(v), y - hgt * q), (X(v), y + hgt * q)], fill=A(GREEN if key else WHITE, 255 * q), width=8 if key else 3)
            d.text((X(v), y + 110), str(v), font=font(BLACKF if key else BOLD, 58 if key else 40),
                   fill=A(GREEN if key else GREY, 255 * q), anchor="mm")
        d.text((110, 560), "KEY NUMBERS", font=font(BLACKF, 92), fill=A(WHITE, 255 * p))
        d.text((110, 670), "Most NFL games land on 3 and 7", font=font(BOLD, 44), fill=A(GREY, 255 * p))
        m = ease_out((t - 0.9) / 0.8); mx = X(lo) + (X(s) - X(lo)) * m
        d.polygon([(mx, y - 95), (mx - 26, y - 140), (mx + 26, y - 140)], fill=A(WHITE, 255 * m))
        d.text((mx, y - 185), f"{fav} {g['spread']:+g}".strip(), font=font(BLACKF, 56), fill=A(WHITE, 255 * m), anchor="mm")
    else:
        # ---- big total / stat counter ----
        val = (g or {}).get("total") or 0
        v = val * ease_out((t - 0.1) / 0.9)
        d.text((540, 760), f"{v:.1f}", font=font(BLACKF, 300), fill=A(WHITE, 255 * p), anchor="mm")
        d.text((540, 960), "GAME TOTAL", font=font(MONO, 50), fill=A(GREEN, 255 * p), anchor="mm")


def draw_books(L, t, sc, g):
    """Price comparison across sportsbooks: favorite's spread at each book, best number highlighted."""
    d = ImageDraw.Draw(L)
    lines = ((g or {}).get("facts") or {}).get("sportsbook_lines") or {}
    books = (lines.get("books") or [])[:5]
    p, off = reveal(t, 0.0, 0.3)
    d.text((80, 330 + off), (sc.get("label") or "SAME GAME, DIFFERENT PRICE").upper(), font=font(MONO, 40), fill=A(GREEN, 255 * p))
    if not books:
        return
    home_fav = lines.get("home_favored", True)
    fav = g["home"]["abbr"] if home_fav else g["away"]["abbr"]
    dog = g["away"]["abbr"] if home_fav else g["home"]["abbr"]
    key, pkey = ("home_spread", "home_price") if home_fav else ("away_spread", "away_price")
    best = lines["best_home" if home_fav else "best_away"]
    d.text((80, 395 + off), f"{fav} SPREAD BY BOOK", font=font(BLACKF, 66), fill=A(WHITE, 255 * p))
    y = 520
    for i, b in enumerate(books):
        q = ease_out((t - 0.25 - i * 0.12) / 0.4)
        if q <= 0:
            y += 140; continue
        dx = (1 - q) * 900
        is_best = b["book"] == best["book"] and b.get(key) == best["spread"]
        fill = A(GREEN, 235 * q) if is_best else A(BG, 200 * q)
        txt = A(BG, 255 * q) if is_best else A(WHITE, 255 * q)
        d.rounded_rectangle([80 + dx, y, 1000 + dx, y + 115], radius=22, fill=fill,
                            outline=None if is_best else A((255, 255, 255), 50 * q), width=2)
        d.text((115 + dx, y + 57), b["book"].upper(), font=font(BLACKF, 50), fill=txt, anchor="lm")
        val = b.get(key)
        price = b.get(pkey)
        d.text((800 + dx, y + 57), f"{val:+g}" if val is not None else "—", font=font(BLACKF, 62), fill=txt, anchor="rm")
        if price is not None:
            d.text((960 + dx, y + 57), f"{price:+d}" if isinstance(price, int) else str(price),
                   font=font(MONO, 32), fill=A(BG if is_best else GREY, 255 * q), anchor="rm")
        if is_best:
            tag = text_img("BEST", font(BLACKF, 30), A(GREEN, 255), 0)
            bgt = Image.new("RGBA", (tag.width + 24, tag.height + 14), A(BG, 255)); bgt.alpha_composite(tag, (12, 7))
            paste_scaled(L, bgt, 990 + dx, y - 4, ease_back((t - 0.9) / 0.3), q, "mm")
        y += 140
    dg = lines.get("best_home" if not home_fav else "best_away") or {}
    q = ease_out((t - 1.1) / 0.4)
    if dg and q > 0:
        d.text((80, y + 10), f"BEST {dog}: {dg['spread']:+g} @ {dg['book'].upper()}", font=font(MONO, 36), fill=A(GREEN, 255 * q))


def draw_point(L, t, sc, g, idx):
    d = ImageDraw.Draw(L)
    p, off = reveal(t, 0.0, 0.3)
    ghost = font(BLACKF, 520)
    d.text((1080 - 30, 1150), f"0{idx}", font=ghost, fill=A(WHITE, 14 * p), anchor="rm")
    eb = (sc.get("eyebrow") or "").upper()
    d.rounded_rectangle([80, 470 + off, 80 + font(MONO, 40).getlength(eb) + 48, 540 + off], radius=12, fill=A(GREEN, 255 * p))
    d.text((104, 482 + off), eb, font=font(MONO, 40), fill=A(BG, 255 * p))
    words = sc["text"].upper().split(); f = font(BLACKF, 124)
    lines, cur = [], []
    for w in words:
        if cur and len(" ".join(cur + [w])) > 11: lines.append(cur); cur = []
        cur.append(w)
    lines.append(cur)
    y, k = 600, 0
    for ln in lines:
        x = 80
        for w in ln:
            q = ease_out((t - 0.15 - k * 0.09) / 0.35)
            if q > 0:
                im = text_img(w, f, A(WHITE, 255), 6)
                paste_scaled(L, im, x, y + (1 - q) * 60, 1, q, "lt")
            x += f.getlength(w + " "); k += 1
        y += 140
    hb = ease_out((t - 0.1) / 0.6)
    d.rectangle([40, 600, 52, 600 + int((y - 610) * hb)], fill=A(GREEN, 255))


class CTA:
    def __init__(self):
        logo = text_img("EIQ", font(BLACKF, 300), A(WHITE, 255), 0)
        glow = Image.new("RGBA", (logo.width + 160, logo.height + 160), (0, 0, 0, 0))
        tint = Image.new("RGBA", logo.size, A(GREEN, 255)); tint.putalpha(logo.getchannel("A"))
        glow.alpha_composite(tint, (80, 80)); glow = glow.filter(ImageFilter.GaussianBlur(40))
        self.logo, self.glow = logo, glow

    def draw(self, L, t, sc, g):
        d = ImageDraw.Draw(L)
        q = (t - 0.05) / 0.35
        paste_scaled(L, self.glow, 540, 600, ease_back(q), (0.55 + 0.35 * math.sin(t * 4)) * min(1, max(0, q)))
        paste_scaled(L, self.logo, 540, 600, ease_back(q), min(1, max(0, q * 2)))
        bar = ease_out((t - 0.35) / 0.5)
        d.rectangle([540 - 260 * bar, 760, 540 + 260 * bar, 776], fill=A(GREEN, 255))
        p, off = reveal(t, 0.45)
        d.text((540, 860 + off), sc["text"].upper(), font=font(XBOLD, 66), fill=A(WHITE, 255 * p), anchor="mm")
        p2, off2 = reveal(t, 0.7)
        s = 1 + 0.04 * math.sin(t * 6)
        pill = Image.new("RGBA", (560, 130), (0, 0, 0, 0)); dp = ImageDraw.Draw(pill)
        dp.rounded_rectangle([0, 0, 559, 129], radius=65, fill=A(GREEN, 255))
        dp.text((280, 65), "FOLLOW " + HANDLE.upper(), font=font(BLACKF, 40), fill=A(BG, 255), anchor="mm")
        paste_scaled(L, pill, 540, 1010 + off2, s, p2)
        d.text((540, 1180), DISCLAIMER, font=font(MONO, 28), fill=A(GREY, 230 * p2), anchor="mm")


# ---------------- captions ----------------
def caption_chunks(words, max_words=3, max_chars=15):
    chunks, cur = [], []
    for w in words:
        if cur and len(" ".join(x[0] for x in cur + [w])) > max_chars:
            chunks.append(cur); cur = []
        cur.append(w)
        if len(cur) >= max_words or w[0].rstrip()[-1:] in ".,!?;:":
            chunks.append(cur); cur = []
    if cur: chunks.append(cur)
    return chunks


def draw_caption(L, t, chunks):
    for i, ch in enumerate(chunks):
        start, end = ch[0][1], ch[-1][2]
        nxt = chunks[i + 1][0][1] if i + 1 < len(chunks) else end + 0.4
        if not (start <= t < max(end, nxt)):
            continue
        f = font(BLACKF, 92)
        parts = [(w.upper().strip(), s, e) for w, s, e in ch]
        widths = [f.getlength(w + " ") for w, _, _ in parts]
        im = Image.new("RGBA", (int(sum(widths)) + 40, 150), (0, 0, 0, 0)); di = ImageDraw.Draw(im)
        x = 20
        for (w, s, e), wd in zip(parts, widths):
            on = s <= t
            col = A(GREEN, 255) if (s <= t < e + 0.05) else A(WHITE, 255 if on else 110)
            di.text((x, 20), w, font=f, fill=col, stroke_width=8, stroke_fill=(0, 0, 0, 240))
            x += wd
        fit = min(1.0, 980 / im.width)
        pop = (0.82 + 0.18 * ease_back((t - start) / 0.14)) * fit
        paste_scaled(L, im, W / 2, 1420, pop, 1)
        break


# ---------------- main render ----------------
def render_video(script, game, timeline, total, out_path, broll_paths=()):
    """timeline: list of {scene, start, dur, words:[(w, abs_start, abs_end)]}"""
    if broll_paths:
        readers = [ClipReader(p) for p in broll_paths]
        bg_src = None
    else:
        readers = []
        c1 = hex_rgb(game["away"]["color"]) if game else GREEN
        c2 = hex_rgb(game["home"]["color"]) if game else GREEN
        bg_src = GradientBG(c1, c2)
    vig = vignette()
    shade = Image.new("RGBA", (W, H), (7, 7, 7, 105))   # extra darkening over real footage
    cta = CTA()
    all_words = [w for seg in timeline for w in seg["words"]]
    chunks = caption_chunks(all_words)
    tag = text_img("EDGELYTICS IQ", font(MONO, 30), A(WHITE, 200), 0)

    ff = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
         "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-maxrate", "10M", "-bufsize", "20M",
         "-pix_fmt", "yuv420p", "-movflags", "+faststart", out_path], stdin=subprocess.PIPE)

    n = int(total * FPS)
    point_idx = {}
    k = 0
    for seg in timeline:
        if seg["scene"]["type"] == "point":
            k += 1; point_idx[id(seg)] = k
    last_bg = None
    for fi in range(n):
        t = fi / FPS
        si = max(i for i, s in enumerate(timeline) if s["start"] <= t) if t >= timeline[0]["start"] else 0
        seg = timeline[si]; lt = t - seg["start"]; sc = seg["scene"]

        # background
        if readers:
            fr = readers[si % len(readers)].next()
            if fr is None: fr = last_bg
            last_bg = fr
            frame = Image.fromarray(fr).convert("RGBA")
            frame.alpha_composite(shade)
        else:
            frame = bg_src.frame(t, fi)
        frame.alpha_composite(vig)

        # scene graphics
        L = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        typ = sc["type"]
        if typ == "hook": draw_hook(L, lt, sc, game)
        elif typ == "matchup" and game: draw_matchup(L, lt, sc, game)
        elif typ == "number": draw_number(L, lt, sc, game)
        elif typ == "books": draw_books(L, lt, sc, game)
        elif typ == "point": draw_point(L, lt, sc, game, point_idx[id(seg)])
        elif typ == "cta": cta.draw(L, lt, sc, game)
        frame.alpha_composite(L)

        # camera punch-in at each scene start
        z = 1 + 0.07 * (1 - ease_out(lt / 0.35))
        if z > 1.002:
            cw, ch = int(W / z), int(H / z)
            frame = frame.crop(((W - cw) // 2, (H - ch) // 2, (W + cw) // 2, (H + ch) // 2)).resize((W, H), Image.BILINEAR)

        # flash cut
        if si > 0 and lt < 0.1:
            fl = Image.new("RGBA", (W, H), (255, 255, 255, int(110 * (1 - lt / 0.1))))
            frame.alpha_composite(fl)

        # captions + UI
        U = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        if typ != "cta":
            draw_caption(U, t, chunks)
        du = ImageDraw.Draw(U)
        du.rectangle([0, 0, int(W * t / total), 9], fill=A(GREEN, 255))
        U.alpha_composite(tag, (80, 210))
        frame.alpha_composite(U)

        ff.stdin.write(frame.convert("RGB").tobytes())
    ff.stdin.close(); ff.wait()
    for r in readers: r.close()
    return out_path
