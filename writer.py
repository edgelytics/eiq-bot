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
talks like a smart friend — never a tout. Rules:
- NEVER promise wins, never say "lock", "guaranteed", "free money".
- Teach the reasoning. Use ONLY the numbers given below. Don't invent stats, injuries, trends or records.
- Match the sport's language: NFL/CFB/NBA spreads are "points"; NHL uses the "puck line" and "the dog".
- The game is played {when} — say it that way, don't say "tonight" unless it is tonight.
- First 1.5 seconds must stop the scroll (pattern interrupt, bold claim, or question).
- Voiceover total 45-60 words (~20-26 seconds). Short punchy sentences. Write numbers the way
  they're spoken ("three and a half", "minus one-ten").
- Do NOT reuse or closely copy any of these recent hooks: {recent_hooks}
- "facts" in the game data was pulled minutes ago from ESPN and US sportsbooks. It is the ONLY outside
  information you may use. Attribute it naturally: "ESPN's model gives them 62 percent", "FanDuel is
  hanging minus three, DraftKings three and a half", "they're 7 and 3 against the spread". If a key player
  is Out or Questionable, that's a great angle. Headlines are context — never quote them word for word.
- If facts.sportsbook_lines.books_disagree is true, include a "books" scene (it shows a price-comparison
  graphic across sportsbooks) and use it to teach line shopping.

Today's angle for this slot: {angle}

The owner's playbook (follow it; it overrides the style notes above if they conflict):
{playbook}

Game data:
{game}

Return ONLY valid JSON (omit the "books" scene if the books don't disagree):
{{
  "scenes": [
    {{"type": "hook", "vo": "spoken line", "text": "on-screen, max 6 words", "accent": "one word from text to highlight"}},
    {{"type": "matchup", "vo": "spoken line introducing the game and the number"}},
    {{"type": "number", "vo": "spoken line about the line movement, key number or total", "label": "max 4 words"}},
    {{"type": "books", "vo": "ONLY if books disagree: spoken line on the price difference between books", "label": "max 4 words"}},
    {{"type": "point", "vo": "spoken line", "eyebrow": "2-3 words", "text": "max 6 words"}},
    {{"type": "point", "vo": "spoken line", "eyebrow": "2-3 words", "text": "max 6 words"}},
    {{"type": "cta", "vo": "spoken line asking them to follow / comment", "text": "max 6 words"}}
  ],
  "caption": "2-4 short lines, ends with a question that makes people comment",
  "hashtags": ["6-10 tags, no #"],
  "music_mood": "3-5 words describing the music vibe",
  "broll_query": "2-4 word stock-footage search for background video, e.g. 'hockey arena crowd'"
}}"""

MUSIC_PROMPT = """Pick the best background track for an Instagram Reel about sports betting.
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
    for model in _gemini_candidates(key)[:5]:
        try:
            r = requests.post(f"{_GEMINI_BASE}/models/{model}:generateContent",
                              headers={"x-goog-api-key": key}, json=body, timeout=90)
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
def write_script(game, angle, recent_hooks=()):
    prompt = SCRIPT_PROMPT.format(
        handle=HANDLE, angle=angle, when=game.get("when", "tonight"),
        recent_hooks="; ".join(f'"{h}"' for h in recent_hooks) or "(none yet)",
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
            if not (((game.get("facts") or {}).get("sportsbook_lines") or {}).get("books_disagree")):
                s["scenes"] = [sc for sc in s["scenes"] if sc["type"] != "books"]
            return _finish(s, game)
        except Exception as e:
            print(f"[writer] bad script from model ({e}) — using template")
    else:
        print("[writer] no AI writer available — using template script")
    return _finish(template_script(game), game)


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
    scored = sorted(((_music_score(t, i), t) for i, t in enumerate(long_enough)), key=lambda x: x[0], reverse=True)
    ok = [t for s, t in scored if s > -3]          # anything that hit a calm word is out
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
def template_script(g):
    a, h, lg = g["away"], g["home"], g["league"]
    when = g.get("when", "tonight")
    fav = g.get("spread_text") or "a pick'em"
    total = g.get("total")
    moved = g.get("spread_open") is not None and g.get("spread_now") is not None and g["spread_open"] != g["spread_now"]
    hockey = lg == "NHL"
    line_word = "puck line" if hockey else "spread"
    if moved:
        num_vo = f"It opened at {g['spread_open']:+g}. Now it's {g['spread_now']:+g}. That move is information."
        label = "Line movement"
    elif lg in ("NFL", "CFB") and g.get("spread") is not None:
        num_vo = f"And {fav} sits right next to a key number. In football that half point matters more than you think."
        label = "Key number"
    else:
        num_vo = (f"The total sits at {total:g}. That's the number sharp bettors actually argue about." if total
                  else "The number is the whole game. Not the logos.")
        label = "The total"
    cta_vo = ("Laying the puck line or taking the dog? Comment, and follow for more." if hockey
              else "Laying it or taking the points? Comment, and follow for more.")
    matchup_vo = f"{a['short']} at {h['short']}, {when}. {fav}" + (f", total {total:g}." if total else ".")
    books_scene = None
    lines = (g.get("facts") or {}).get("sportsbook_lines") or {}
    if lines.get("books_disagree"):
        fav_side = "best_home" if lines.get("home_favored") else "best_away"
        dog_side = "best_away" if lines.get("home_favored") else "best_home"
        fv, dg = lines[fav_side], lines[dog_side]
        books_scene = {"type": "books", "label": "Same game, different price",
                       "vo": f"Same game, different price. Best number on the favorite is {fv['spread']:+g} at {fv['book']}. "
                             f"Best on the dog is {dg['spread']:+g} at {dg['book']}. Shop every book."}
    return {
        "scenes": [
            {"type": "hook", "vo": f"Everyone's on the {h['short']} {when}. The number says something else.",
             "text": "The number is lying", "accent": "lying"},
            {"type": "matchup", "vo": matchup_vo},
            {"type": "number", "vo": num_vo, "label": label},
            *([books_scene] if books_scene else []),
            {"type": "point", "vo": "Books don't set lines to predict games. They set them to split money.",
             "eyebrow": "The trap", "text": "Lines follow the money"},
            {"type": "point", "vo": "Stop asking who wins. Ask if the price is wrong.",
             "eyebrow": "The edge", "text": "Price beats opinion"},
            {"type": "cta", "vo": cta_vo, "text": "Numbers, not noise"},
        ],
        "caption": f"{a['short']} at {h['short']} {when}. The {line_word} says {fav}.\nSharp question: is that price right?\n"
                   + ("Puck line or the dog? 👇" if hockey else "Laying it or taking the points? 👇"),
        "hashtags": ["sportsbetting", lg.lower(), "bettingtips", "linemovement", "sharpbetting", "edgelyticsiq", "sportsanalytics"],
        "music_mood": "dark hype trap instrumental",
        "broll_query": {"NFL": "american football stadium night", "CFB": "college football stadium",
                        "NBA": "basketball arena", "NHL": "ice hockey arena"}.get(lg, "stadium lights"),
    }
