"""
build.py — script -> voiceover timeline -> video -> two audio mixes.

Outputs:
  <base>_post.mp4     voice + SFX only (Instagram's trending track gets attached at post time)
  <base>_preview.mp4  voice + SFX + generated music bed (to preview, and fallback if
                      the Instagram Audio API isn't available)
"""
import os
import subprocess
import tempfile
import numpy as np

import audio
from render import render_video
from broll import fetch_clips

LEAD = {"hook": 0.35}         # silence before the line starts (hook leaves room for the impact)
TAIL = 0.32                   # breathing room after each line
MIN_DUR = {"matchup": 3.4, "number": 3.6, "cta": 3.2}


def build_timeline(script):
    timeline, t = [], 0.0
    for sc in script["scenes"]:
        vo, words = audio.speak(sc["vo"])
        lead = LEAD.get(sc["type"], 0.12)
        dur = max(MIN_DUR.get(sc["type"], 2.0), lead + len(vo) / audio.SR + TAIL)
        timeline.append({"scene": sc, "start": t, "dur": dur, "vo": vo, "vo_at": t + lead,
                         "words": [(w, t + lead + s, t + lead + e) for w, s, e in words]})
        t += dur
    return timeline, t + 0.4


def build_audio(timeline, total):
    voice = [(seg["vo"], seg["vo_at"], 1.0) for seg in timeline]
    sfx = [(audio.impact(), timeline[0]["start"] + 0.05, 0.9)]
    for seg in timeline[1:]:
        sfx.append((audio.whoosh(seed=int(seg["start"] * 10)), max(0, seg["start"] - 0.22), 0.8))
    cta = timeline[-1]
    sfx.append((audio.riser(), max(0, cta["start"] - 1.2), 0.5))
    sfx.append((audio.impact(0.7), cta["start"] + 0.05, 0.6))

    voice_only = audio.mix(voice, total)
    post = audio.mix(voice + sfx, total)
    bed = audio.duck(audio.music_bed(total), voice_only, 0.45)
    preview = audio.mix(voice + sfx + [(bed, 0, 0.30)], total)
    return post, preview


def build_reel(script, game, base):
    os.makedirs(os.path.dirname(base) or ".", exist_ok=True)
    timeline, total = build_timeline(script)
    post_wav, prev_wav = build_audio(timeline, total)
    clips = fetch_clips(script.get("broll_query", "stadium lights"), n=3)
    print(f"[build] {total:.1f}s, {len(timeline)} scenes, b-roll clips: {len(clips)}")

    with tempfile.TemporaryDirectory() as td:
        silent = os.path.join(td, "v.mp4")
        render_video(script, game, timeline, total, silent, clips)
        outs = {}
        for name, wav in (("post", post_wav), ("preview", prev_wav)):
            wp = os.path.join(td, f"{name}.wav"); audio.write_wav(wp, wav)
            out = f"{base}_{name}.mp4"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", silent, "-i", wp,
                            "-c:v", "copy", "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
                            "-shortest", "-movflags", "+faststart", out], check=True)
            outs[name] = out
    return outs, total
