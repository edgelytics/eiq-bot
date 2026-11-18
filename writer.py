"""
writer.py — writes the Reel (voiceover + on-screen text + caption) and picks the music.

Script writer, in order of preference:
  1. Claude    (ANTHROPIC_API_KEY)
  2. Gemini    (GEMINI_API_KEY — free tier)
  3. Built-in template (so the bot never posts nothing)
Every run also reads playbook.md (your rules) and avoids recently used hooks.
"""
import json
import os
import re
import requests
from config import CLAUDE_MODEL, HANDLE, DISCLAIMER

HERE = os.path.dirname(os.path.abspath(__file__))

SCRIPT_PROMPT = """You write viral short-form Reels for Edgelytics IQ ({handle}), a sports betting
analytics + education brand. Voice: sharp, confident, numbers-first, a little contrarian,
talks like a smart friend who just read the news — never a tout. Rules:
- NEVER promise wins, never say "lock", "guaranteed", "free money".
- Every reel must tell the viewer something NEW and SPECIFIC about THIS game: a report, a line move,
  an injury, what ESPN's model says vs the betting number. If a sentence could be said about any game, cut it.
- Use ONLY the facts below. Don't invent stats, injuries, quotes, trends or records.
- Match the sport's language: NFL/CFB/NBA spreads are "points"; NHL uses the "puck line" and "the dog".
- The game is played {when} — say it that way, don't say "tonight" unless it is tonight.
- First 1.5 seconds must stop the scroll, and the hook must be about THIS game's news (name the team/player).
- Voiceover total 50-65 words (~22-28 seconds). Short punchy sentences. Write numbers the way
  they're spoken ("three and a half", "minus one-ten").
- Attribute facts naturally: "ESPN is reporting...", "ESPN's model gives them 62 percent",
  "this opened at minus four, it's minus six now".
- BANNED (we've overused these — never say them or anything close): "the number is lying",
  "books don't set lines to predict games", "lines follow the money", "price beats opinion",
  "numbers not noise", "stop asking who wins", "split the money", "the books know something".
- Don't repeat ideas or phrasing from our recent reels: {recent_lines}
- Do NOT reuse or closely copy any of these recent hooks: {recent_hooks}

THIS REEL'S FORMAT — {fmt_name}: {fmt_rule}

Scene types you can use (hook first, cta last, 3-5 scenes in between, in the order that tells the story best):
  hook    — {{"type":"hook","vo":"...","text":"on-screen, max 6 words","accent":"one word from text"}}
  report  — puts an ESPN story on screen like a screenshot: {{"type":"report","ref":<index in facts.reports>,"vo":"what it says, in your words"}}
  matchup — {{"type":"matchup","vo":"introduce the game and the number"}}
  number  — line-movement / key-number graphic: {{"type":"number","vo":"...","label":"max 4 words"}}
  books   — ONLY if facts.sportsbook_lines.books_disagree is true: {{"type":"books","vo":"...","label":"max 4 words"}}
  point   — {{"type":"point","vo":"...","eyebrow":"2-3 words","text":"max 6 words"}}
  cta     — {{"type":"cta","vo":"a question specific to this game that makes people comment + follow","text":"max 6 words"}}

Slot note: {angle}

The owner's playbook (follow it; it overrides the style notes above if they conflict):
{playbook}

Game data (facts were pulled minutes ago from ESPN and sportsbooks):
{game}

Return ONLY valid JSON:
{{
  "scenes": [ ... ],
  "caption": "2-4 short lines about THIS game's news, ends with a question that makes people comment",
  "hashtags": ["6-10 tags, no #, include both team names"],
  "music_mood": "3-5 words describing the music vibe",
  "broll_query": "2-4 word stock-footage search for background video, e.g. 'hockey arena crowd'"
}}"""

# Reel formats — the bot rotates through the ones today's facts can support, so reels don't sound alike.
FORMATS = {
    "report":  ("The Report", "Lead with the freshest ESPN report in facts.reports. Put it on screen with a "
                "'report' scene right after the hook, then explain what it changes about the betting number."),
    "move":    ("Line Move Alert", "Lead with how the line has moved (facts.line_movement / our_tracked_movement): "
                "where it opened, where it is now, the likely reason from the facts, and whether the value is gone."),
    "injury":  ("Injury Impact", "Lead with the biggest name on the injury report and how much it should matter "
                "to the spread or total. Be specific about the player and status."),
    "model":   ("Model vs Market", "Compare ESPN's win probability with what the betting line implies. "
                "Say which side the gap points to and why that might be."),
    "pick":    ("Our Play Tonight", "The owner's pick is in game.pick — make the WHOLE reel about it. Hook names the "
                "player and the number (e.g. 'Ajay Mitchell over 17.5'). Back it with facts.player (his real recent "
                "numbers, how often he's gone over this line) plus injuries/news from the game facts. Present it as "
                "our play and the reasoning — confident, never 'lock' or 'guaranteed', and remind them to shop the line. "
                "Only quote numbers that are in the data. CTA: 'Over or under? Comment.'"),
    "matchup": ("Sharp Angle", "Find the single most interesting fact in the data and build the whole reel around it."),
}


def eligible_formats(game):
    f = (game or {}).get("facts") or {}
    out = []
    if f.get("reports"): out.append("report")
    if (f.get("line_movement") or {}).get("moved") or f.get("our_tracked_movement"): out.append("move")
    if f.get("injuries"): out.append("injury")
    if f.get("espn_win_prob"): out.append("model")
    return out or ["matchup"]

MUSIC_PROMPT = """Pick the best background track for an Instagram Reel about sports betting.
The list is Instagram's trending chart, most popular first — prefer higher-ranked tracks when they fit.
Reel vibe: {mood}. Reel topic: {topic}. It sits UNDER a voiceover, so pick something energetic,
modern and confident (hype, trap, phonk, cinematic, drill, bass-heavy). Never pick anything calm,
sad, sleepy, romantic, childish, holiday, acoustic or comedic.

Tracks (index: title — artist):
{tracks}

Reply with ONLY the index number."""


# ---------------- playbook ----------------
def load_playbook():
    try:
        with open(os.path.join(HERE, "playbook.md")) as f:
            text = f.read().strip()
        return text[:6000] or "(empty)"
    except FileNotFoundError:
        return "(none)"


# ---------------- LLM providers ----------------
def _claude(prompt, max_tokens=1500):
    import anthropic
    client = anthropic.Anthropic()
    msg = client.messages.create(model=CLAUDE_MODEL, max_tokens=max_tokens,
                                 messages=[{"role": "user", "content": prompt}])
    return msg.content[0].text.strip()


_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"
_gemini_models = None


def _gemini_candidates(key):
    """Newest Gemini Flash models first (free tier covers Flash / Flash-Lite)."""
    global _gemini_models
    if _gemini_models is not None:
        return _gemini_models
    forced = os.environ.get("GEMINI_MODEL")
    if forced:
        _gemini_models = [forced]
        return _gemini_models
    names = []
    try:
        r = requests.get(f"{_GEMINI_BASE}/models", params={"pageSize": 200},
                         headers={"x-goog-api-key": key}, timeout=30)
        for m in r.json().get("models", []):
            n = m.get("name", "").replace("models/", "")
            if "generateContent" not in m.get("supportedGenerationMethods", []):
                continue
            if "flash" not in n or any(b in n for b in ("image", "tts", "audio", "live", "embed", "exp", "thinking")):
                continue
            names.append(n)
    except Exception as e:
        print(f"[writer] couldn't list Gemini models ({e})")

    def rank(n):
        v = re.findall(r"gemini-(\d+(?:\.\d+)?)", n)
        ver = float(v[0]) if v else 0.0
        return (ver, "lite" not in n, "preview" not in n)
    names.sort(key=rank, reverse=True)
    _gemini_models = names or ["gemini-flash-latest", "gemini-2.5-flash"]
    return _gemini_models


def _gemini(prompt, max_tokens=4096, json_mode=False):
    key = os.environ["GEMINI_API_KEY"]
    body = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"maxOutputTokens": max_tokens, "temperature": 0.95}}
    if json_mode:
        body["generationConfig"]["responseMimeType"] = "application/json"
    last = None
    import time
    cands = _gemini_candidates(key)
    order = [m for m in cands if "lite" not in m][:4] + [m for m in cands if "lite" in m][:2]
    deadline = time.time() + 420            # free tier gets overloaded: keep retrying for up to 7 minutes
    tries = [(rnd, m) for rnd in range(4) for m in (order or cands[:4])]
    for i, (rnd, model) in enumerate(tries):
        if time.time() > deadline:
            break
        if i and tries[i - 1][0] != rnd:
            print(f"[writer] all Gemini models busy — waiting {20 * rnd}s and trying again")
            time.sleep(20 * rnd)
        try:
            r = requests.post(f"{_GEMINI_BASE}/models/{model}:generateContent",
                              headers={"x-goog-api-key": key}, json=body, timeout=35)
            j = r.json()
            if r.status_code >= 400 or "error" in j:
                raise RuntimeError(json.dumps(j.get("error", j))[:300])
            parts = j["candidates"][0]["content"]["parts"]
            text = "".join(p.get("text", "") for p in parts if not p.get("thought")).strip()
            if text:
                print(f"[writer] Gemini model: {model}")
                return text
            raise RuntimeError("empty response")
        except Exception as e:
            print(f"[writer] Gemini {model} failed: {e}")
            last = e
    raise RuntimeError(f"all Gemini models failed: {last}")


def llm(prompt, json_mode=False, short=False):
    """Returns text from the best available model, or None if none configured / all fail."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            return _claude(prompt, 20 if short else 1500)
        except Exception as e:
            print(f"[writer] Claude failed ({e})")
    if os.environ.get("GEMINI_API_KEY"):
        try:
            return _gemini(prompt, json_mode=json_mode)
        except Exception as e:
            print(f"[writer] Gemini failed ({e})")
    return None


# ---------------- script ----------------
def write_script(game, angle, recent_hooks=(), fmt="matchup", recent_lines=()):
    reports = ((game.get("facts") or {}).get("reports")) or []
    prompt = SCRIPT_PROMPT.format(
        handle=HANDLE, angle=angle, when=game.get("when", "tonight"),
        fmt_name=FORMATS.get(fmt, FORMATS["matchup"])[0], fmt_rule=FORMATS.get(fmt, FORMATS["matchup"])[1],
        recent_hooks="; ".join(f'"{h}"' for h in recent_hooks) or "(none yet)",
        recent_lines=" | ".join(l[:160] for l in recent_lines) or "(none yet)",
        playbook=load_playbook(), game=json.dumps(game, indent=2))
    text = llm(prompt, json_mode=True)
    if text:
        try:
            s = json.loads(text[text.find("{"): text.rfind("}") + 1])
            types = [sc["type"] for sc in s["scenes"]]
            assert types[0] == "hook" and types[-1] == "cta" and all(sc.get("vo") for sc in s["scenes"])
            for sc in s["scenes"]:
                if sc["type"] in ("hook", "point", "cta"):
                    sc.setdefault("text", sc["vo"][:40])
            s["scenes"] = [sc for sc in s["scenes"] if sc["type"] != "report" or _fill_report(sc, reports)]
            if not (((game.get("facts") or {}).get("sportsbook_lines") or {}).get("books_disagree")):
                s["scenes"] = [sc for sc in s["scenes"] if sc["type"] != "books"]
            low = " ".join(sc["vo"] for sc in s["scenes"]).lower()
            if any(b in low for b in BANNED):
                print("[writer] model used a banned stock line — trimming it")
                s["scenes"] = [sc for sc in s["scenes"] if sc["type"] in ("hook", "cta") or not any(b in sc["vo"].lower() for b in BANNED)]
            s["format"] = fmt
            s["writer"] = "ai"
            return _finish(s, game)
        except Exception as e:
            print(f"[writer] bad script from model ({e}) — using fact-based backup")
    else:
        print("[writer] no AI writer available — using fact-based backup script")
    s = template_script(game, fmt, recent_hooks)
    s["format"], s["writer"] = fmt, "backup"
    return _finish(s, game)


BANNED = ("number is lying", "predict games", "follow the money", "price beats opinion", "numbers, not noise",
          "numbers not noise", "stop asking who wins", "split money", "split the money", "books know something")


def _fill_report(sc, reports):
    """The model only picks WHICH report; the words shown on screen always come straight from ESPN's data."""
    try:
        r = reports[int(sc.get("ref", 0))]
    except (ValueError, IndexError, TypeError):
        return False
    sc.update(source=r["source"], headline=r["headline"], summary=r.get("summary", ""),
              byline=r.get("byline", ""), ago=r.get("ago", ""))
    return True


def _finish(s, game=None):
    tags = " ".join("#" + h.lstrip("#").replace(" ", "") for h in s.get("hashtags", []))
    asof = ""
    lines = ((game or {}).get("facts") or {}).get("sportsbook_lines")
    if lines:
        try:
            from zoneinfo import ZoneInfo
            import datetime as _dt
            t = _dt.datetime.fromisoformat(lines["as_of"]).astimezone(ZoneInfo("America/Chicago"))
            asof = f"\n\nOdds as of {t:%-I:%M%p} CT — lines move, always shop around."
        except Exception:
            pass
    s["full_caption"] = f"{s['caption']}{asof}\n\n{DISCLAIMER}\n\n{tags}".strip()
    return s


# ---------------- music ----------------
GOOD = ("hype", "trap", "phonk", "drill", "bass", "energy", "energetic", "power", "epic", "beast", "rage",
        "fire", "boom", "legend", "champion", "win", "run", "fight", "battle", "attack", "dark", "night",
        "money", "boss", "turn up", "anthem", "cinematic", "action", "sport", "game", "victory")
CALM = ("peaceful", "reverie", "relax", "calm", "sleep", "lofi", "lo-fi", "chill", "meditation", "ambient",
        "acoustic", "piano", "lullaby", "soft", "gentle", "dream", "love", "romantic", "sad",
        "tears", "rain", "spa", "yoga", "christmas", "xmas", "jingle", "santa", "holiday", "kids",
        "birthday", "baby", "nursery", "cartoon", "funny", "meme", "wedding")


def _music_score(t, rank):
    name = f"{t.get('title', '')} {t.get('display_artist', '')}".lower()
    s = sum(2 for w in GOOD if w in name) - sum(6 for w in CALM if w in name)
    return s - rank * 0.05


def pick_music(script, tracks, min_ms):
    """tracks = list from Instagram's /ig_audio (trending + searches). Returns one track or None."""
    seen, uniq = set(), []
    for t in tracks:
        if t.get("audio_id") and t["audio_id"] not in seen:
            seen.add(t["audio_id"]); uniq.append(t)
    long_enough = [t for t in uniq if (t.get("duration_in_ms") or 0) >= min_ms] or uniq
    # 1st choice: Instagram's trending chart (kept in its own popularity order), minus calm/novelty tracks.
    trending = [t for t in long_enough if t.get("_src") == "trending" and _music_score(t, 0) > -3]
    if trending:
        ok = trending[:20]
        print(f"[writer] choosing from {len(ok)} trending tracks")
    else:
        scored = sorted(((_music_score(t, i), t) for i, t in enumerate(long_enough)), key=lambda x: x[0], reverse=True)
        ok = [t for s, t in scored if s > -3]          # anything that hit a calm word is out
        print(f"[writer] no usable trending tracks — choosing from {len(ok)} searched tracks")
    if not ok:
        return None
    if len(ok) > 1:
        listing = "\n".join(f"{i}: {t.get('title')} — {t.get('display_artist')}" for i, t in enumerate(ok[:30]))
        ans = llm(MUSIC_PROMPT.format(mood=script.get("music_mood", "hype"),
                                      topic=script["scenes"][0].get("text", ""), tracks=listing), short=True)
        if ans:
            m = re.search(r"\d+", ans)
            if m and int(m.group()) < len(ok[:30]):
                return ok[int(m.group())]
    return ok[0]


# ---------------- template (fallback) ----------------
import random as _rnd


def _say(x):
    try:
        return f"{float(x):+g}".replace("+", "plus ").replace("-", "minus ")
    except (TypeError, ValueError):
        return str(x)


def template_script(g, fmt="matchup", recent_hooks=()):
    """Used only when no AI writer answers. Built from the real facts so it still says something specific."""
    a, h, lg = g["away"], g["home"], g["league"]
    when = g.get("when", "tonight")
    f = g.get("facts") or {}
    hockey = lg == "NHL"
    fav = g.get("spread_text") or "a pick'em"
    total = g.get("total")
    mv = f.get("line_movement") or {}
    reports = f.get("reports") or []
    inj = f.get("injuries") or {}
    wp = f.get("espn_win_prob") or {}
    scenes, hook = [], None

    if fmt == "report" and reports:
        r = reports[0]
        hook = {"type": "hook", "vo": f"New report on {a['short']} and {h['short']} before {when}.",
                "text": _rnd.choice([f"{h['short']} news just dropped", f"Read this before betting {h['short']}",
                                     f"ESPN just reported this"]), "accent": "news", "tag": "ESPN REPORT"}
        rep = {"type": "report", "ref": 0, "vo": f"ESPN is reporting: {r['headline']}."}
        _fill_report(rep, reports)
        scenes.append(rep)
        scenes.append({"type": "matchup", "vo": f"Right now it's {fav}" + (f", total {total:g}." if total else ".")})
        scenes.append({"type": "point", "vo": "News like this moves lines fast. If the number hasn't adjusted yet, that's your window. If it has, don't chase it.",
                       "eyebrow": "Before you bet", "text": "Has the line caught up?"})
    elif fmt == "move" and mv:
        o, n = mv.get("home_spread_open"), mv.get("home_spread_now")
        if o and n and o != n:
            line = f"{h['short']} opened at {_say(o)}. They're {_say(n)} now."
        elif mv.get("total_open") and mv.get("total_open") != mv.get("total_now"):
            line = f"The total opened at {mv['total_open']} and it's sitting at {mv['total_now']} now."
        else:
            line = "The moneyline has moved since it opened."
        hook = {"type": "hook", "vo": f"This line moved, and nobody's talking about it. {a['short']} at {h['short']}.",
                "text": _rnd.choice([f"{h['short']} line just moved", "Somebody bet this early", f"Watch the {h['short']} number"]),
                "accent": "moved"}
        scenes.append({"type": "number", "vo": line + " Early money usually means someone saw something.", "label": "Line movement"})
        scenes.append({"type": "point", "vo": "If you missed the opener, the question is simple. Is there any value left at this price?",
                       "eyebrow": "Your move", "text": "Is the value gone?"})
    elif fmt == "injury" and inj:
        team, rows = next(iter(inj.items()))
        who = rows[0].split(" (")[0]; status = rows[0].rsplit("— ", 1)[-1]
        hook = {"type": "hook", "vo": f"{who} is listed {status.lower()} for {team}, and that changes this bet.",
                "text": f"{who.split()[-1]} is {status.lower()}", "accent": status.split()[0].lower()}
        more = f" They've also got {len(rows) - 1} more on the report." if len(rows) > 1 else ""
        scenes.append({"type": "matchup", "vo": f"{a['short']} at {h['short']}, {when}. {fav}." + more})
        scenes.append({"type": "point", "vo": "Before you bet it, check whether the line already moved for the news. If it did, the edge is priced in.",
                       "eyebrow": "Check first", "text": "Is it priced in?"})
    elif fmt == "model" and wp:
        team, pct = max(wp.items(), key=lambda kv: float(str(kv[1] or "0").rstrip("%")))
        hook = {"type": "hook", "vo": f"ESPN's model gives {team} a {pct.rstrip('%')} percent chance {when}.",
                "text": f"ESPN says {team} {pct}", "accent": team}
        scenes.append({"type": "matchup", "vo": f"The betting market has it {fav}. Compare that to the model before you lay anything."})
        scenes.append({"type": "point", "vo": "When the model and the market disagree, one of them is wrong. Your job is figuring out which.",
                       "eyebrow": "The gap", "text": "Model vs the market"})
    pk = g.get("pick") or {}
    if fmt == "pick" and pk:
        pl = f.get("player") or {}
        nm, ln, st = pk["player"], pk.get("line"), pk.get("stat", "points")
        hook = {"type": "hook", "vo": f"Our play {when}: {nm}, over {ln:g} {st}.",
                "text": f"{nm.split()[-1]} over {ln:g}", "accent": "over", "tag": "OUR PLAY TONIGHT"}
        if pl.get("last_10_avg") is not None:
            scenes.append({"type": "point", "vo": f"He's averaging {pl['last_10_avg']:g} {st} over his last ten, "
                           f"{pl['season_avg']:g} on the season. He's cleared {ln:g} in {pl.get('went_over_line_last_10')} of those games.",
                           "eyebrow": "Last 10 games", "text": f"{pl['last_10_avg']:g} {st} per game"})
        scenes.append({"type": "matchup", "vo": f"{a['short']} at {h['short']}, {when}. {fav}."})
        scenes.append({"type": "point", "vo": f"Shop it before you bet. Some books will hang {ln:g}, some {ln + 1:g}. That half point matters.",
                       "eyebrow": "Shop the line", "text": "Find the best number"})
        q = None
    if not hook:
        hook = {"type": "hook", "vo": f"{a['short']} at {h['short']} {when}. Here's the one number that matters.",
                "text": f"{a['short']} at {h['short']}", "accent": h["short"].split()[-1]}
        scenes.append({"type": "matchup", "vo": f"{fav}" + (f", total {total:g}." if total else ".")})
        if reports and fmt != "report":
            rep = {"type": "report", "ref": 0, "vo": f"And ESPN is reporting: {reports[0]['headline']}."}
            _fill_report(rep, reports); scenes.append(rep)

    lines = f.get("sportsbook_lines") or {}
    if lines.get("books_disagree"):
        fv = lines["best_home" if lines.get("home_favored") else "best_away"]
        scenes.append({"type": "books", "label": "Same game, different price",
                       "vo": f"And shop it. Best number on the favorite is {fv['spread']:+g} at {fv['book']}."})
    q = f"{pk['player']} over or under {pk['line']:g}? Comment, and follow for more." if fmt == "pick" and pk else _rnd.choice([f"Who are you taking, {a['short']} or {h['short']}? Comment and follow.",
                     f"Does this change your {h['short']} bet? Tell me below, and follow for more.",
                     f"{a['short']} or {h['short']}? Drop it in the comments and follow."])
    return {
        "scenes": [hook, *scenes, {"type": "cta", "vo": q, "text": f"{a['short']} or {h['short']}?"}],
        "caption": f"{a['short']} at {h['short']} {when}. "
                   + (f"ESPN: {reports[0]['headline']}" if reports else f"The line: {fav}.")
                   + f"\nWho are you taking? 👇",
        "hashtags": ["sportsbetting", lg.lower(), a["short"].replace(" ", "").lower(), h["short"].replace(" ", "").lower(),
                     "linemovement", "bettingnews", "edgelyticsiq"],
        "music_mood": "dark hype trap instrumental",
        "broll_query": {"NFL": "american football stadium night", "CFB": "college football stadium",
                        "NBA": "basketball arena", "NHL": "ice hockey arena"}.get(lg, "stadium lights"),
    }
