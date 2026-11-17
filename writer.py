"""
writer.py — Claude writes the Reel (voiceover + on-screen text + caption)
and picks the Instagram music track.

Needs ANTHROPIC_API_KEY. Falls back to a template so the bot never posts nothing.
"""
import json
import os
from config import CLAUDE_MODEL, HANDLE, DISCLAIMER

SCRIPT_PROMPT = """You write viral short-form Reels for Edgelytics IQ ({handle}), a sports betting
analytics + education brand. Voice: sharp, confident, numbers-first, a little contrarian,
talks like a smart friend — never a tout. Rules:
- NEVER promise wins, never say "lock", "guaranteed", "free money".
- Teach the reasoning. Use ONLY the numbers given below. Don't invent stats, injuries or trends.
- First 1.5 seconds must stop the scroll (pattern interrupt, bold claim, or question).
- Voiceover total 45-60 words (~20-26 seconds). Short punchy sentences. Write numbers the way
  they're spoken ("three and a half", "minus one-ten").

Today's angle for this slot: {angle}

Game data:
{game}

Return ONLY valid JSON:
{{
  "scenes": [
    {{"type": "hook", "vo": "spoken line", "text": "on-screen, max 6 words", "accent": "one word from text to highlight"}},
    {{"type": "matchup", "vo": "spoken line introducing the game and the number"}},
    {{"type": "number", "vo": "spoken line about the line movement or key number", "label": "max 4 words"}},
    {{"type": "point", "vo": "spoken line", "eyebrow": "2-3 words", "text": "max 6 words"}},
    {{"type": "point", "vo": "spoken line", "eyebrow": "2-3 words", "text": "max 6 words"}},
    {{"type": "cta", "vo": "spoken line asking them to follow / comment", "text": "max 6 words"}}
  ],
  "caption": "2-4 short lines, ends with a question that makes people comment",
  "hashtags": ["6-10 tags, no #"],
  "music_mood": "3-5 words describing the music vibe",
  "broll_query": "2-4 word stock-footage search for background video, e.g. 'football stadium night'"
}}"""

MUSIC_PROMPT = """Pick the best background track for this Instagram Reel.
Reel vibe: {mood}. Reel topic: {topic}. Prefer energetic, modern, instrumental-feeling tracks
that won't fight a voiceover. Avoid anything sad, childish, holiday or comedic.

Tracks (index: title — artist):
{tracks}

Reply with ONLY the index number."""


def _claude(prompt, max_tokens=1200):
    import anthropic
    client = anthropic.Anthropic()
    msg = client.messages.create(model=CLAUDE_MODEL, max_tokens=max_tokens,
                                 messages=[{"role": "user", "content": prompt}])
    return msg.content[0].text.strip()


def write_script(game, angle):
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            text = _claude(SCRIPT_PROMPT.format(handle=HANDLE, angle=angle, game=json.dumps(game, indent=2)))
            s = json.loads(text[text.find("{"): text.rfind("}") + 1])
            assert s["scenes"][0]["type"] == "hook"
            return _finish(s)
        except Exception as e:
            print(f"[writer] Claude script failed ({e}) — using template")
    else:
        print("[writer] No ANTHROPIC_API_KEY — using template script")
    return _finish(template_script(game))


def _finish(s):
    tags = " ".join("#" + h.lstrip("#") for h in s.get("hashtags", []))
    s["full_caption"] = f"{s['caption']}\n\n{DISCLAIMER}\n\n{tags}".strip()
    return s


def pick_music(script, tracks, min_ms):
    """tracks = list from Instagram's /ig_audio. Returns one track dict or None."""
    bad = ("christmas", "xmas", "jingle", "santa", "holiday", "kids", "lullaby", "birthday", "baby",
           "sad", "piano ballad", "funny", "meme", "cartoon", "nursery")
    clean = [t for t in tracks if not any(b in f"{t.get('title')} {t.get('display_artist')}".lower() for b in bad)]
    ok = [t for t in clean if (t.get("duration_in_ms") or 0) >= min_ms] or clean
    if not ok:
        return None
    if os.environ.get("ANTHROPIC_API_KEY") and len(ok) > 1:
        try:
            listing = "\n".join(f"{i}: {t.get('title')} — {t.get('display_artist')}" for i, t in enumerate(ok[:30]))
            topic = script["scenes"][0]["text"]
            i = int(_claude(MUSIC_PROMPT.format(mood=script.get("music_mood", "hype"), topic=topic, tracks=listing), 10))
            return ok[i]
        except Exception as e:
            print(f"[writer] music pick fallback ({e})")
    return ok[0]


def template_script(g):
    a, h = g["away"], g["home"]
    fav = g.get("spread_text") or "a pick'em"
    moved = g.get("spread_open") is not None and g.get("spread_now") is not None and g["spread_open"] != g["spread_now"]
    num_vo = (f"It opened at {g['spread_open']:+g}. Now it's {g['spread_now']:+g}. That move is information."
              if moved else f"And {fav} sits right next to a key number. In football that half point matters more than you think.")
    return {
        "scenes": [
            {"type": "hook", "vo": f"Everyone's on the {h['short']} tonight. The number says something else.",
             "text": "The number is lying", "accent": "lying"},
            {"type": "matchup", "vo": f"{a['short']} at {h['short']}. {fav}, total {g['total']:g}."},
            {"type": "number", "vo": num_vo, "label": "Line movement" if moved else "Key number"},
            {"type": "point", "vo": "Books don't set lines to predict games. They set them to split money.",
             "eyebrow": "The trap", "text": "Lines follow the money"},
            {"type": "point", "vo": "Stop asking who wins. Ask if the price is wrong.",
             "eyebrow": "The edge", "text": "Price beats opinion"},
            {"type": "cta", "vo": "Laying it or taking the points? Comment, and follow for more.",
             "text": "Numbers, not noise"},
        ],
        "caption": f"{a['short']} at {h['short']}. The line says {fav}.\nSharp question: is that price right?\nLaying it or taking the points? 👇",
        "hashtags": ["sportsbetting", g["league"].lower(), "bettingtips", "linemovement", "sharpbetting", "edgelyticsiq", "sportsanalytics"],
        "music_mood": "dark hype trap instrumental",
        "broll_query": {"NFL": "american football stadium night", "CFB": "college football stadium",
                        "NBA": "basketball arena", "NHL": "ice hockey arena"}.get(g["league"], "stadium lights"),
    }
