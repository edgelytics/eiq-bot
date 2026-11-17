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
import sys
import time
from zoneinfo import ZoneInfo

import config
from trends import get_trending, SAMPLE_GAME
from writer import write_script, pick_music
from build import build_reel
from enrich import enrich

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
    if a.slot:
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
    if any(p.get("date") == str(today) and p.get("slot") == slot["name"] and p.get("permalink") for p in state["posts"]):
        print("[run] this slot already posted today, exiting."); return 0

    # 1) scan
    if a.sample:
        game = SAMPLE_GAME
    else:
        recent = [gid for gid, d in state["games"].items()
                  if (today - dt.date.fromisoformat(d)).days < 3]
        games = get_trending(config.LEAGUES, exclude_ids=recent, top_n=5) or get_trending(config.LEAGUES, top_n=5)
        if not games:
            print("[run] no upcoming games found anywhere — skipping slot.")
            return 0
        game = games[0]
    print(f"[run] game: {game['away']['abbr']} @ {game['home']['abbr']} ({game['league']}, score {game.get('trend_score')})")

    # 2) real facts: ESPN analytics/injuries/ATS/news + prices across sportsbooks
    game.setdefault("when", "tonight")
    if not a.sample:
        try:
            enrich(game, state)
        except Exception as e:
            print(f"[run] enrich failed ({e}) — continuing without extra facts")

    # 3) write + build
    recent_hooks = [p.get("hook") for p in state["posts"][-12:] if p.get("hook")]
    script = write_script(game, slot["angle"], recent_hooks)
    base = f"out/{today}_{slot['name']}_{game['away']['abbr']}_{game['home']['abbr']}"
    outs, secs, clip_ids = build_reel(script, game, base, state.get("broll_used", []))
    state["broll_used"] = (state.get("broll_used", []) + clip_ids)[-400:]
    with open(base + ".json", "w") as f:
        json.dump({"slot": slot, "game": game, "script": script}, f, indent=2)

    # 4) pick Instagram music
    track = None
    if config.IG_TOKEN:   # read-only lookup, also runs on dry runs so you can see the pick
        from publish import trending_music
        try:
            tracks = []
            for q in (None, "hype", "trap", "phonk", "sports"):
                try:
                    tracks += trending_music(q)
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
        notify(f"🧪 **EIQ bot built a Reel (not posted)** — {slot['name']}\n🎵 {track.get('title') if track else 'built-in beat'}\n{script['full_caption'][:600]}", outs["preview"])
        print(f"[run] built {outs} — not posting (dry_run={dry}, autopost={config.AUTOPOST})")
        save_state(state)
        return 0

    wait = (post_at - dt.datetime.now(tz)).total_seconds()
    if 0 < wait < 3600:
        print(f"[run] waiting {wait / 60:.1f} min until {post_at:%H:%M}")
        time.sleep(wait)

    try:
        res = post_reel(outs["post"], outs["preview"], script["full_caption"], track)
    except Exception as e:
        notify(f"⚠️ **EIQ bot failed to post** ({slot['name']}): {e}")
        raise
    state["games"][game["id"]] = str(today)
    state["posts"].append({"date": str(today), "slot": slot["name"], "game": game["id"],
                           "hook": script["scenes"][0].get("text"), **res})
    save_state(state)
    notify(f"✅ **Posted** ({slot['name']}): {game['away']['abbr']} @ {game['home']['abbr']}\n"
           f"🎵 {res['audio']}\n{res.get('permalink') or ''}")
    print(f"[run] posted: {res}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
