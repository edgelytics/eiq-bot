"""
run_slot.py — one full cycle: scan -> write -> voice -> render -> pick music -> wait -> post.

The scheduler (GitHub Actions) calls this every day ~20 min before each slot.
  python run_slot.py              # auto-detect which slot is coming up; exits if none
  python run_slot.py --slot primetime --now      # force a slot, post immediately
  python run_slot.py --sample --dry-run          # offline test, never posts
"""
import argparse
import datetime as dt
import json
import os
import random
import sys
import time
from zoneinfo import ZoneInfo

import config
from trends import get_trending, SAMPLE_GAME
from writer import write_script, pick_music
from build import build_reel
from enrich import enrich
import audio
import explainers
import themes

STATE = "state/posted.json"


def load_state():
    try:
        with open(STATE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"games": {}, "posts": []}


def save_state(s):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    s["posts"] = s["posts"][-200:]
    with open(STATE, "w") as f:
        json.dump(s, f, indent=2)


def lru(options, posts, field, forced="auto"):
    """The dashboard's pinned choice, else whichever option was used least recently."""
    if forced and forced != "auto" and forced in options:
        return forced
    last = {}
    for i, p in enumerate(posts):
        if p.get(field):
            last[p[field]] = i
    opts = list(options)
    random.shuffle(opts)
    return min(opts, key=lambda k: last.get(k, -1))


def upcoming_slot(now):
    """Slot whose post time is between 10 min ago and 50 min from now."""
    for sl in config.SLOTS:
        hh, mm = map(int, sl["post"].split(":"))
        post_at = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
        mins = (post_at - now).total_seconds() / 60
        if -10 <= mins <= 50:
            return sl, post_at
    return None, None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slot")
    ap.add_argument("--now", action="store_true", help="post immediately instead of waiting for the slot time")
    ap.add_argument("--sample", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    dry = a.dry_run or config.DRY_RUN

    tz = ZoneInfo(config.TIMEZONE)
    now = dt.datetime.now(tz)
    if a.slot == "extra":
        # an on-demand post from the dashboard, on top of the 3 scheduled ones
        slot = {"name": "extra", "post": now.strftime("%H:%M"), "angle": config.SLOTS[0]["angle"]}
        post_at = now
    elif a.slot:
        slot = next(s for s in config.SLOTS if s["name"] == a.slot)
        hh, mm = map(int, slot["post"].split(":"))
        post_at = now if a.now else now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    else:
        slot, post_at = upcoming_slot(now)
        if not slot:
            print(f"[run] {now:%H:%M} — no slot coming up, exiting.")
            return 0
        if a.now:
            post_at = now
    print(f"[run] slot={slot['name']} post_at={post_at:%Y-%m-%d %H:%M %Z} dry={dry}")

    state = load_state()
    today = now.date()
    if slot["name"] != "extra" and any(p.get("date") == str(today) and p.get("slot") == slot["name"] and p.get("permalink") for p in state["posts"]):
        print("[run] this slot already posted today, exiting."); return 0

    # 0) what kind of reel, which voice, which design
    kind = config.KIND_CHOICE if config.KIND_CHOICE in ("game", "explainer") else "auto"
    if kind == "auto":
        n = config.EXPLAINER_EVERY_N_DAYS
        kind = "explainer" if (slot["name"] == config.EXPLAINER_SLOT and n and today.toordinal() % n == 0) else "game"
    voice = audio.set_voice(lru(config.VOICES, state["posts"], "voice", config.VOICE_CHOICE))
    theme = lru(themes.THEMES, state["posts"], "theme", config.THEME_CHOICE)
    print(f"[run] kind={kind} voice={voice} theme={theme}")

    # 1) scan
    game = None
    if kind == "game":
        if a.sample:
            game = SAMPLE_GAME
        else:
            recent = [gid for gid, d in state["games"].items()
                      if (today - dt.date.fromisoformat(d)).days < 3]
            games = get_trending(config.LEAGUES, exclude_ids=recent, top_n=5) or get_trending(config.LEAGUES, top_n=5)
            if games:
                game = games[0]
            else:
                print("[run] no upcoming games found anywhere — posting an explainer instead.")
                kind = "explainer"

    if kind == "explainer":
        topic = explainers.pick_topic(state, config.TOPIC_CHOICE)
        script, game = explainers.build_script(topic, state)
        print(f"[run] explainer: {topic} — {explainers.TOPICS[topic]['title']}")
        label = f"explainer_{topic}"
    else:
        print(f"[run] game: {game['away']['abbr']} @ {game['home']['abbr']} ({game['league']}, score {game.get('trend_score')})")
        # 2) real facts: ESPN analytics/injuries/ATS/news + prices across sportsbooks
        game.setdefault("when", "tonight")
        if not a.sample:
            try:
                enrich(game, state)
            except Exception as e:
                print(f"[run] enrich failed ({e}) — continuing without extra facts")
        recent_hooks = [p.get("hook") for p in state["posts"][-12:] if p.get("hook")]
        script = write_script(game, slot["angle"], recent_hooks)
        script["kind"] = "game"
        label = f"{game['away']['abbr']}_{game['home']['abbr']}"

    # 3) build
    script["theme"], script["voice"] = theme, voice
    base = f"out/{today}_{slot['name']}_{label}"
    outs, secs, clip_ids = build_reel(script, game, base, state.get("broll_used", []))
    state["broll_used"] = (state.get("broll_used", []) + clip_ids)[-400:]
    with open(base + ".json", "w") as f:
        json.dump({"slot": slot, "game": game, "script": script}, f, indent=2)

    # 4) pick Instagram music
    # Instagram can silently skip attaching a song. Each post checks whether it stuck; after a miss the bot
    # tries the next way of attaching it, and if none work it bakes our own beat in (retrying every 2 days).
    music = state.setdefault("ig_music", {"strategy": "json", "fails": 0})
    if music["strategy"] == "off" and (today - dt.date.fromisoformat(music.get("off_since", str(today)))).days >= 2:
        music.update(strategy="json", fails=0)
    track = None
    if config.IG_TOKEN and music["strategy"] != "off":   # read-only lookup, also runs on dry runs so you can see the pick
        from publish import trending_music
        try:
            tracks = []
            for q in (None, "hype", "trap", "phonk", "sports"):
                try:
                    got = trending_music(q)
                    for x in got:   # None = Instagram's trending chart, in its own popularity order
                        x["_src"] = "trending" if q is None else "search"
                    tracks += got
                except Exception as e:
                    print(f"[run] audio search {q!r} failed: {e}")
            if not tracks:
                raise RuntimeError("no tracks returned")
            track = pick_music(script, tracks, int(secs * 1000))
            if track:
                print(f"[run] music: {track.get('title')} — {track.get('display_artist')}")
        except Exception as e:
            print(f"[run] Audio API unavailable ({e}) — will use built-in music bed")

    # 5) wait for the slot time, then post
    from publish import post_reel, notify
    if dry or not config.AUTOPOST:
        notify(f"🧪 **EIQ bot built a Reel (not posted)** — {slot['name']} · {kind} · {voice} · {theme}\n🎵 {track.get('title') if track else 'built-in beat'}\n{script['full_caption'][:600]}", outs["preview"])
        print(f"[run] built {outs} — not posting (dry_run={dry}, autopost={config.AUTOPOST})")
        save_state(state)
        return 0

    wait = (post_at - dt.datetime.now(tz)).total_seconds()
    if 0 < wait < 3600:
        print(f"[run] waiting {wait / 60:.1f} min until {post_at:%H:%M}")
        time.sleep(wait)

    try:
        res = post_reel(outs["post"], outs["preview"], script["full_caption"], track, music["strategy"])
    except Exception as e:
        notify(f"⚠️ **EIQ bot failed to post** ({slot['name']}): {e}")
        raise
    if track and res.get("music_attached") is False:
        nxt = {"json": "loop", "loop": "off"}.get(music["strategy"], "off")
        print(f"[run] Instagram did NOT attach the song (strategy {music['strategy']}) — next time: {nxt}")
        music.update(strategy=nxt, fails=music.get("fails", 0) + 1, last_fail=str(today))
        if nxt == "off":
            music["off_since"] = str(today)
        res["audio"] = f"{res['audio']} (NOT attached by Instagram)"
    elif track and res.get("music_attached"):
        music.update(fails=0, last_ok=str(today))
    if kind == "game":
        state["games"][game["id"]] = str(today)
    state["posts"].append({"date": str(today), "slot": slot["name"], "game": game.get("id"),
                           "hook": script["scenes"][0].get("text"), "kind": kind, "topic": script.get("topic"),
                           "voice": voice, "theme": theme, **res})
    save_state(state)
    what = explainers.TOPICS[script["topic"]]["title"] if kind == "explainer" else f"{game['away']['abbr']} @ {game['home']['abbr']}"
    notify(f"✅ **Posted** ({slot['name']}): {what} · voice {voice} · design {theme}\n"
           f"🎵 {res['audio']}\n{res.get('permalink') or ''}")
    print(f"[run] posted: {res}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
