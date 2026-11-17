"""
enrich.py — real facts for the script, so videos say valid things.

  ESPN game summary (free, no key):  ESPN Analytics win probability, ATS records,
                                     injury report, latest news headlines, open/close line
  The Odds API (free, ODDS_API_KEY): live spreads/totals at DraftKings, FanDuel, BetMGM, Caesars...
  Our own snapshots (state file):    how the consensus line has moved since we first saw it
"""
import datetime as dt
import json
import os
import statistics
import urllib.request
import requests

from trends import PATHS

ODDS_KEY = os.environ.get("ODDS_API_KEY")
ODDS_SPORT = {"NFL": "americanfootball_nfl", "NBA": "basketball_nba",
              "CFB": "americanfootball_ncaaf", "NHL": "icehockey_nhl"}
BOOK_NAMES = {"draftkings": "DraftKings", "fanduel": "FanDuel", "betmgm": "BetMGM",
              "williamhill_us": "Caesars", "espnbet": "ESPN BET", "fanatics": "Fanatics",
              "betrivers": "BetRivers", "bet365": "bet365", "hardrockbet": "Hard Rock",
              "ballybet": "Bally Bet", "betonlineag": "BetOnline", "bovada": "Bovada", "lowvig": "LowVig"}
PREFERRED = ["draftkings", "fanduel", "betmgm", "williamhill_us", "espnbet", "fanatics", "bet365", "betrivers"]


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def _abbr(team):
    return (team or {}).get("abbreviation") or (team or {}).get("displayName", "")


# ---------------- ESPN ----------------
def espn_facts(game):
    out = {}
    eid = game["id"].split("-", 1)[1]
    try:
        d = _get(f"https://site.api.espn.com/apis/site/v2/sports/{PATHS[game['league']]}/summary?event={eid}")
    except Exception as e:
        print(f"[enrich] ESPN summary failed: {e}")
        return out

    # ESPN Analytics win probability
    try:
        pr = d.get("predictor") or {}
        h = pr.get("homeTeam", {}).get("gameProjection")
        a = pr.get("awayTeam", {}).get("gameProjection")
        if h or a:
            out["espn_win_prob"] = {game["home"]["abbr"]: f"{float(h):.1f}%" if h else None,
                                    game["away"]["abbr"]: f"{float(a):.1f}%" if a else None}
    except Exception:
        pass

    # Against-the-spread records
    try:
        ats = {}
        for t in d.get("againstTheSpread", []):
            recs = t.get("records") or []
            if recs:
                ats[_abbr(t.get("team"))] = recs[0].get("summary")
        if ats:
            out["ats_records"] = ats
    except Exception:
        pass

    # Injuries (only meaningful statuses, top 4 per team)
    try:
        inj = {}
        for t in d.get("injuries", []):
            rows = []
            for i in t.get("injuries", []):
                st = (i.get("status") or "").strip()
                if st.lower() not in ("out", "doubtful", "questionable", "injured reserve"):
                    continue
                ath = i.get("athlete", {})
                pos = (ath.get("position") or {}).get("abbreviation", "")
                rows.append(f"{ath.get('displayName')} ({pos}) — {st}")
            if rows:
                inj[_abbr(t.get("team"))] = rows[:4]
        if inj:
            out["injuries"] = inj
    except Exception:
        pass

    # Latest headlines about the game / teams
    try:
        arts = (d.get("news") or {}).get("articles") or []
        heads = []
        for a_ in arts[:5]:
            hl = a_.get("headline")
            if hl:
                desc = (a_.get("description") or "").strip()
                heads.append(hl + (f" — {desc[:160]}" if desc else ""))
        if heads:
            out["espn_headlines"] = heads
    except Exception:
        pass

    # Open vs current line from ESPN's pick center
    try:
        for pc in d.get("pickcenter", []):
            ps = (pc.get("pointSpread") or {}).get("home") or {}
            o, c = ps.get("open", {}).get("line"), ps.get("close", {}).get("line")
            if o and c:
                out["espn_line_open_vs_now"] = {"provider": (pc.get("provider") or {}).get("name"),
                                                "home_open": o, "home_now": c}
                break
    except Exception:
        pass
    return out


# ---------------- The Odds API ----------------
def _match(ev, game):
    def norm(s): return (s or "").lower().replace(".", "")
    h, a = norm(game["home"]["name"]), norm(game["away"]["name"])
    eh, ea = norm(ev.get("home_team")), norm(ev.get("away_team"))
    last = lambda s: s.split()[-1] if s else ""
    return (eh == h or last(eh) == last(h)) and (ea == a or last(ea) == last(a))


def book_lines(game):
    """Spread + total at each US book for this game. Costs 2 credits (spreads + totals, 1 region)."""
    if not ODDS_KEY or game["league"] not in ODDS_SPORT:
        return None
    try:
        r = requests.get(f"https://api.the-odds-api.com/v4/sports/{ODDS_SPORT[game['league']]}/odds",
                         params={"apiKey": ODDS_KEY, "regions": "us", "markets": "spreads,totals",
                                 "oddsFormat": "american"}, timeout=30)
        r.raise_for_status()
        print(f"[enrich] Odds API credits left: {r.headers.get('x-requests-remaining')}")
        events = r.json()
    except Exception as e:
        print(f"[enrich] Odds API failed: {e}")
        return None
    ev = next((e for e in events if _match(e, game)), None)
    if not ev:
        print("[enrich] game not found at Odds API")
        return None
    home = ev["home_team"]
    rows = []
    for bk in ev.get("bookmakers", []):
        row = {"key": bk["key"], "book": BOOK_NAMES.get(bk["key"], bk.get("title", bk["key"]))}
        for m in bk.get("markets", []):
            if m["key"] == "spreads":
                for o in m["outcomes"]:
                    if o["name"] == home:
                        row["home_spread"], row["home_price"] = o.get("point"), o.get("price")
                    else:
                        row["away_spread"], row["away_price"] = o.get("point"), o.get("price")
            elif m["key"] == "totals":
                for o in m["outcomes"]:
                    if o["name"] == "Over":
                        row["total"], row["over_price"] = o.get("point"), o.get("price")
        if row.get("home_spread") is not None:
            rows.append(row)
    if not rows:
        return None
    rows.sort(key=lambda r: PREFERRED.index(r["key"]) if r["key"] in PREFERRED else 99)
    spreads = [r["home_spread"] for r in rows]
    consensus = statistics.median(spreads)
    fav_home = consensus < 0
    # best number for each side: favorite wants the smallest number to lay, dog wants the biggest
    best_home = max(rows, key=lambda r: (r["home_spread"], r.get("home_price") or -999))
    best_away = max(rows, key=lambda r: (r["away_spread"], r.get("away_price") or -999))
    return {
        "as_of": dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes"),
        "home_favored": fav_home,
        "consensus_home_spread": consensus,
        "spread_range": [min(spreads), max(spreads)],
        "books_disagree": min(spreads) != max(spreads),
        "best_home": {"book": best_home["book"], "spread": best_home["home_spread"], "price": best_home.get("home_price")},
        "best_away": {"book": best_away["book"], "spread": best_away["away_spread"], "price": best_away.get("away_price")},
        "books": [{k: r.get(k) for k in ("book", "home_spread", "home_price", "away_spread", "away_price", "total")}
                  for r in rows[:6]],
    }


# ---------------- our own line history ----------------
def track_line(state, game, lines):
    """Store a snapshot each run; report movement since our first snapshot of this game."""
    if not lines:
        return None
    hist = state.setdefault("lines", {}).setdefault(game["id"], [])
    now = dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes")
    hist.append({"t": now, "home_spread": lines["consensus_home_spread"]})
    del hist[:-20]
    # keep the state file small: drop games older than 5 days
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=5)).isoformat()
    for gid in list(state["lines"]):
        if state["lines"][gid] and state["lines"][gid][-1]["t"] < cutoff:
            del state["lines"][gid]
    if len(hist) >= 2 and hist[0]["home_spread"] != hist[-1]["home_spread"]:
        return {"first_seen": hist[0], "now": hist[-1]}
    return None


def enrich(game, state):
    facts = espn_facts(game)
    lines = book_lines(game)
    if lines:
        facts["sportsbook_lines"] = lines
        mv = track_line(state, game, lines)
        if mv:
            facts["our_tracked_movement"] = mv
    game["facts"] = facts
    print(f"[enrich] facts: {', '.join(facts) or 'none'}")
    return game
