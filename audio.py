"""
audio.py — voiceover (Kokoro), word timings for captions, sound effects,
a fallback music bed, and the final mix.
"""
import re
import numpy as np
import soundfile as sf
from config import KOKORO_MODEL, KOKORO_VOICES, VOICE, VOICE_SPEED

SR = 24000
_kokoro = None


def _tts():
    global _kokoro
    if _kokoro is None:
        from kokoro_onnx import Kokoro
        _kokoro = Kokoro(KOKORO_MODEL, KOKORO_VOICES)
    return _kokoro


def _trim(x, thresh=0.012, pad=0.04):
    idx = np.where(np.abs(x) > thresh)[0]
    if not len(idx):
        return x
    a = max(0, idx[0] - int(pad * SR))
    b = min(len(x), idx[-1] + int(pad * SR))
    return x[a:b]


def _syllables(w):
    w = re.sub(r"[^a-z0-9]", "", w.lower())
    if not w:
        return 1
    if w.isdigit():
        return max(1, len(w))
    return max(1, len(re.findall(r"[aeiouy]+", w)) - (1 if w.endswith("e") and len(w) > 3 else 0))


def speak(text):
    """Returns (samples float32 @24k, [(word, start_s, end_s), ...])."""
    s, sr = _tts().create(text, voice=VOICE, speed=VOICE_SPEED, lang="en-us")
    s = _trim(np.asarray(s, dtype=np.float32))
    assert sr == SR
    words = text.split()
    # weight by syllables, plus a little extra after punctuation (natural pauses)
    w = np.array([_syllables(x) + (0.9 if re.search(r"[.,!?;:]$", x) else 0) for x in words], float)
    dur = len(s) / SR
    edges = np.concatenate([[0], np.cumsum(w) / w.sum() * dur])
    timings = [(words[i], float(edges[i]), float(edges[i + 1])) for i in range(len(words))]
    return s, timings


# ---------------- sound design (procedural, royalty-free by construction) ----------------
def _noise(n, seed=0):
    return np.random.default_rng(seed).standard_normal(n).astype(np.float32)


def _onepole_lp(x, a):
    y = np.empty_like(x); acc = 0.0
    for i in range(len(x)):
        acc += a * (x[i] - acc); y[i] = acc
    return y


def whoosh(dur=0.45, seed=1):
    n = int(dur * SR); t = np.linspace(0, 1, n)
    x = _noise(n, seed)
    # sweep: crude band emphasis via difference of lowpasses with moving cutoff
    lp = np.cumsum(x) / np.arange(1, n + 1)
    hp = x - np.convolve(x, np.ones(24) / 24, mode="same")
    mix = hp * (t ** 1.5) + (x - lp) * 0.3
    env = np.sin(np.pi * t) ** 2 * (0.4 + 0.6 * t)
    return (mix * env * 0.35).astype(np.float32)


def impact(dur=0.9):
    n = int(dur * SR); t = np.arange(n) / SR
    f = 38 + 90 * np.exp(-t * 18)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 4.0)
    click = _noise(n, 3) * np.exp(-t * 60) * 0.5
    return (np.tanh((body + click) * 2.2) * 0.55).astype(np.float32)


def riser(dur=1.2):
    n = int(dur * SR); t = np.linspace(0, 1, n)
    f = 200 + 1400 * t ** 2
    tone = np.sin(2 * np.pi * np.cumsum(f) / SR) * 0.15
    hiss = (_noise(n, 5) - np.convolve(_noise(n, 5), np.ones(8) / 8, "same")) * 0.25
    return ((tone + hiss) * t ** 2 * 0.5).astype(np.float32)


def tick():
    n = int(0.05 * SR); t = np.arange(n) / SR
    return (np.sin(2 * np.pi * 2200 * t) * np.exp(-t * 120) * 0.25).astype(np.float32)


def music_bed(seconds, bpm=142, seed=7):
    """Dark trap-style instrumental. Used for previews, and as a fallback if the
    Instagram Audio API isn't available. Royalty-free (generated)."""
    n = int(seconds * SR)
    out = np.zeros(n + SR, np.float32)
    beat = 60 / bpm
    step = beat / 4  # 16th
    rng = np.random.default_rng(seed)

    def put(sig, t0, gain=1.0):
        i = int(t0 * SR)
        if i >= n: return
        j = min(len(out), i + len(sig)); out[i:j] += sig[: j - i] * gain

    # samples
    tk = np.arange(int(0.9 * SR)) / SR
    kick = np.tanh(np.sin(2 * np.pi * np.cumsum(45 + 110 * np.exp(-tk * 30)) / SR) * np.exp(-tk * 3.2) * 2.5) * 0.8
    tc = np.arange(int(0.25 * SR)) / SR
    clapn = _noise(len(tc), 11); clapn = clapn - np.convolve(clapn, np.ones(6) / 6, "same")
    clap = clapn * (np.exp(-tc * 28) + 0.6 * np.exp(-np.maximum(tc - 0.012, 0) * 40) * (tc > 0.012)) * 0.45
    th = np.arange(int(0.05 * SR)) / SR
    hn = _noise(len(th), 13); hat = (hn - np.convolve(hn, np.ones(3) / 3, "same")) * np.exp(-th * 90) * 0.22

    # A minor-ish progression: Am - F - C - G (roots)
    roots = [55.0, 43.65, 65.41, 49.0]
    chords = [[220, 261.63, 329.63], [174.61, 220, 261.63], [261.63, 329.63, 392], [196, 246.94, 293.66]]
    bar = beat * 4
    bars = int(np.ceil(seconds / bar)) + 1
    kick_pat = [0, 6, 10]          # 16th positions
    for b in range(bars):
        t0 = b * bar
        r = roots[b % 4]
        for k in kick_pat + ([14] if b % 2 else []):
            put(kick, t0 + k * step, 1.0)
            # 808 sub follows kick
            ln = int(step * 3.5 * SR); ts = np.arange(ln) / SR
            put(np.tanh(np.sin(2 * np.pi * r * ts) * 2) * np.exp(-ts * 2.2) * 0.35, t0 + k * step)
        for c in (4, 12):
            put(clap, t0 + c * step)
        for h in range(16):
            if h % 2 == 0 or rng.random() < 0.25:
                put(hat, t0 + h * step, 0.7 if h % 4 else 1.0)
        if b % 2 == 1:  # hat roll
            for h in range(6):
                put(hat, t0 + (15 * step) - h * step / 3, 0.6)
        # pad
        ln = int(bar * SR); tp = np.arange(ln) / SR
        pad = sum(np.sign(np.sin(2 * np.pi * f * tp + 0.3)) * 0.33 + np.sin(2 * np.pi * f * 1.003 * tp)
                  for f in chords[b % 4])
        pad = _onepole_lp(pad.astype(np.float32) * 0.05, 0.04)
        env = np.minimum(1, tp / 0.3) * np.minimum(1, (bar - tp) / 0.3)
        put(pad * env, t0)
    out = out[:n]
    # sidechain-ish pump on every beat
    tt = np.arange(n) / SR
    pump = 0.55 + 0.45 * np.clip(((tt % beat) / beat) * 3, 0, 1)
    out *= pump
    out /= max(1e-6, np.abs(out).max())
    fade = int(1.2 * SR); out[-fade:] *= np.linspace(1, 0, fade)
    return out * 0.9


def mix(tracks, seconds):
    """tracks = list of (samples, start_s, gain). Returns limited float32 mono."""
    n = int(seconds * SR)
    out = np.zeros(n, np.float32)
    for sig, start, gain in tracks:
        i = int(start * SR)
        if i >= n: continue
        j = min(n, i + len(sig))
        out[i:j] += sig[: j - i] * gain
    peak = np.abs(out).max()
    if peak > 0.98:
        out = np.tanh(out / peak * 1.4) / np.tanh(1.4) * 0.95
    return out


def duck(music, voice_track, amount=0.35):
    """Lower music under the voice."""
    env = np.convolve(np.abs(voice_track), np.ones(2400) / 2400, "same")
    env = np.clip(env / (env.max() + 1e-6) * 4, 0, 1)
    return music * (1 - amount * env)


def write_wav(path, x):
    sf.write(path, x, SR)
