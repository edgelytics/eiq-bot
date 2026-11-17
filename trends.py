"""
trends.py — finds the most postable games right now.

Uses ESPN's public scoreboard (no key). Scores each upcoming game on
primetime TV, tight spread, high total, team quality, line movement and start time.
"""
import json
import datetime as dt
import urllib.request

PATHS = {
    "NFL": "football/nfl",
    "NBA": "basketball/nba",
    "CFB": "football/college-football",
    "NHL": "hockey/nhl",
}
BIG_TV = {"NBC", "ESPN", "ABC", "Prime Video", "FOX", "CBS", "TNT", "Peacock", "Netflix", "truTV"}


def _num(x):
    try:
        return float(str(x).replace("o", "").replace("u", "").replace("+", ""))
    except (TypeError, ValueError):
        return None


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)


def fetch_league(league, days_ahead=2):
    """Today's games plus the next couple of days (so late-night runs still find a slate)."""
    events, seen = [], set()
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=-6))).date()
    for i in range(days_ahead + 1):
        d = (today + dt.timedelta(days=i)).strftime("%Y%m%d")
        try:
            data = _get(f"https://site.api.espn.com/apis/site/v2/sports/{PATHS[league]}/scoreboard?dates={d}")
        except Exception as e:
            print(f"[trends] {league} {d}: {e}"); continue
        for ev in data.get("events", []):
            if ev["id"] not in seen:
                seen.add(ev["id"]); events.append(ev)
    games = []
    for ev in events:
        comp = ev["competitions"][0]
        if comp.get("status", {}).get("type", {}).get("state") != "pre":
            continue
        teams = {}
        for c in comp["competitors"]:
            t = c["team"]
            teams[c["homeAway"]] = {
                "name": t.get("displayName"),
                "short": t.get("shortDisplayName") or t.get("name"),
                "abbr": t.get("abbreviation"),
                "color": "#" + (t.get("color") or "16A34A"),
                "alt_color": "#" + (t.get("alternateColor") or "FFFFFF"),
                "record": ((c.get("records") or [{}])[0]).get("summary", ""),
            }
        odds = (comp.get("odds") or [{}])[0]
        ps = odds.get("pointSpread", {}).get("home", {})
        games.append({
            "league": league,
            "id": f"{league}-{ev['id']}",
            "start": ev["date"],
            "away": teams.get("away"),
            "home": teams.get("home"),
            "spread_text": odds.get("details"),
            "spread": _num(odds.get("spread")),                 # home perspective
            "spread_open": _num(ps.get("open", {}).get("line")),
            "spread_now": _num(ps.get("close", {}).get("line")),
            "total": _num(odds.get("overUnder")),
            "networks": [n for b in comp.get("broadcasts", []) for n in b.get("names", [])],
            "venue": comp.get("venue", {}).get("fullName"),
        })
    return games


def _wp(rec):
    try:
        w, l = (int(x) for x in rec.split("-")[:2])
        return w / (w + l) if w + l else 0.5
    except Exception:
        return 0.5


def score(g, now=None):
    s = 0.0
    if any(n in BIG_TV for n in g["networks"]):
        s += 2.0
    if g["spread"] is not None:
        s += max(0.0, 3.0 - abs(g["spread"]) / 2.0)
    if g["total"]:
        if g["league"] in ("NFL", "CFB") and g["total"] >= 48: s += 1.0
        if g["league"] == "NBA" and g["total"] >= 230: s += 1.0
    s += 2.0 * min(_wp(g["away"]["record"]), _wp(g["home"]["record"]))
    if g.get("spread_open") is not None and g.get("spread_now") is not None:
        s += min(2.0, abs(g["spread_now"] - g["spread_open"]))   # line movement = story
    s += {"NFL": 1.5, "NBA": 0.75, "CFB": 0.75, "NHL": 0.0}.get(g["league"], 0)
    # prefer games starting in the next ~12h (people are betting them now)
    try:
        now = now or dt.datetime.now(dt.timezone.utc)
        hrs = (dt.datetime.fromisoformat(g["start"].replace("Z", "+00:00")) - now).total_seconds() / 3600
        if 0 < hrs <= 12: s += 1.5
        elif hrs > 36: s -= 1.5
    except Exception:
        pass
    return round(s, 4)


def get_trending(leagues, exclude_ids=(), top_n=5):
    games = []
    for lg in leagues:
        try:
            games += fetch_league(lg)
        except Exception as e:
            print(f"[trends] {lg} skipped: {e}")
    games = [g for g in games if g["id"] not in set(exclude_ids) and g["away"] and g["home"]]
    for g in games:
        g["trend_score"] = score(g)
    games.sort(key=lambda g: g["trend_score"], reverse=True)
    return games[:top_n]


SAMPLE_GAME = {
    "league": "NFL", "id": "NFL-sample", "start": "2026-11-17T01:15:00Z",
    "away": {"name": "Dallas Cowboys", "short": "Cowboys", "abbr": "DAL", "color": "#003594", "alt_color": "#869397", "record": "6-4"},
    "home": {"name": "Philadelphia Eagles", "short": "Eagles", "abbr": "PHI", "color": "#06424D", "alt_color": "#A5ACAF", "record": "8-2"},
    "spread_text": "PHI -3.5", "spread": -3.5, "spread_open": -2.5, "spread_now": -3.5,
    "total": 46.5, "networks": ["ESPN"], "venue": "Lincoln Financial Field", "trend_score": 9.1,
}

if __name__ == "__main__":
    from config import LEAGUES
    print(json.dumps(get_trending(LEAGUES), indent=2))
