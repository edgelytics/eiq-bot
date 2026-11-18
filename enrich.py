"""
enrich.py — real facts for the script, so videos say valid things.

  ESPN game summary (free, no key):  ESPN Analytics win probability, ATS records,
                                     injury report, latest news headlines, open/close line
  OddsPapi (ODDSPAPI_KEY):           live spreads/totals at DraftKings, FanDuel, BetMGM, Caesars... (preferred)
  The Odds API (ODDS_API_KEY):       same, used only if OddsPapi isn't set up or fails
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
PREFERRED = ["draftkings", "fanduel", "betmgm", "williamhill_us", "caesars", "williamhill", "espnbet", "fanatics",
             "bet365", "thescore", "betrivers", "hardrockbet", "circa"]   # US books, shown first


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

    # Reports: ESPN stories about this game / these teams (shown on screen as a "report card")
    try:
        out["reports"] = _reports(game, (d.get("news") or {}).get("articles") or [])
        if not out["reports"]:
            del out["reports"]
    except Exception as e:
        print(f"[enrich] reports failed: {e}")

    # Line movement from ESPN's pick center: spread, total and moneyline, open vs now
    try:
        for pc in d.get("pickcenter", []):
            mv = {"provider": (pc.get("provider") or {}).get("name")}
            ps = (pc.get("pointSpread") or {}).get("home") or {}
            o, c = ps.get("open", {}).get("line"), ps.get("close", {}).get("line")
            if o and c:
                mv["home_spread_open"], mv["home_spread_now"] = o, c
            tt = (pc.get("total") or {}).get("over") or {}
            o2, c2 = tt.get("open", {}).get("line"), tt.get("close", {}).get("line")
            if o2 and c2:
                mv["total_open"], mv["total_now"] = str(o2).lstrip("ou"), str(c2).lstrip("ou")
            ml = pc.get("moneyline") or {}
            for side, team in (("home", game["home"]["abbr"]), ("away", game["away"]["abbr"])):
                m = ml.get(side) or {}
                mo, mc = (m.get("open") or {}).get("odds"), (m.get("close") or {}).get("odds")
                if mo and mc:
                    mv[f"{team}_moneyline_open"], mv[f"{team}_moneyline_now"] = mo, mc
            if len(mv) > 1:
                out["espn_line_open_vs_now"] = {"provider": mv["provider"], "home_open": mv.get("home_spread_open"),
                                                "home_now": mv.get("home_spread_now")}
                moved = (mv.get("home_spread_open") != mv.get("home_spread_now")
                         or mv.get("total_open") != mv.get("total_now")
                         or any(mv[k] != mv.get(k.replace("_open", "_now")) for k in mv if k.endswith("moneyline_open")))
                mv["moved"] = bool(moved)
                out["line_movement"] = mv
                break
    except Exception:
        pass
    return out


# ---------------- reports ----------------
def _ago(iso):
    try:
        t = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
        h = (dt.datetime.now(dt.timezone.utc) - t).total_seconds() / 3600
        return f"{int(h * 60)}m ago" if h < 1 else f"{int(h)}h ago" if h < 48 else f"{int(h // 24)}d ago"
    except Exception:
        return ""


def _reports(game, game_articles):
    """ESPN stories tied to this game, plus the league news feed filtered to these two teams. Freshest first."""
    arts = list(game_articles)
    try:
        arts += _get(f"https://site.api.espn.com/apis/site/v2/sports/{PATHS[game['league']]}/news?limit=50").get("articles", [])
    except Exception as e:
        print(f"[enrich] ESPN news feed failed: {e}")
    names = set()
    for side in ("home", "away"):
        t = game[side]
        for k in ("name", "short"):
            if t.get(k):
                names.add(t[k].lower()); names.add(t[k].split()[-1].lower())
    names = {n for n in names if len(n) > 3}
    seen, out = set(), []
    for a in arts:
        hl = (a.get("headline") or "").strip()
        if not hl or hl in seen or a.get("type") in ("Media", "video"):
            continue
        desc = (a.get("description") or "").strip()
        cats = " ".join((c.get("description") or "") for c in a.get("categories") or []).lower()
        blob = f"{hl} {desc} {cats}".lower()
        if a not in game_articles and not any(n in blob for n in names):
            continue
        age_h = None
        try:
            age_h = (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(a["published"].replace("Z", "+00:00"))).total_seconds() / 3600
        except Exception:
            pass
        if age_h is not None and age_h > 72:
            continue
        seen.add(hl)
        out.append({"source": "ESPN", "headline": hl, "summary": desc[:220], "byline": (a.get("byline") or "").strip(),
                    "ago": _ago(a.get("published", "")), "_age": 50 if age_h is None else age_h})
    out.sort(key=lambda r: r["_age"])
    for r in out:
        r.pop("_age", None)
    return out[:5]


# ---------------- player props ----------------
ESPN_SPORT = {"NBA": "basketball/nba", "NFL": "football/nfl", "NHL": "hockey/nhl", "CFB": "football/college-football"}


def player_facts(name, league, stat="points", line=None):
    """Real recent numbers for one player from ESPN: season average and last-10 game log for the stat."""
    import urllib.parse
    res = _get("https://site.web.api.espn.com/apis/common/v3/search?" +
               urllib.parse.urlencode({"query": name, "limit": 10, "type": "player"}))
    items = res.get("items") or res.get("results") or []
    pid = None
    for it in items:
        lg = str(it.get("league") or it.get("defaultLeagueSlug") or "").lower()
        if (it.get("displayName") or "").lower() == name.lower() and (not lg or league.lower() in lg):
            pid = it.get("id"); break
    if not pid and items:
        pid = items[0].get("id")
    if not pid:
        print(f"[enrich] ESPN player not found: {name}")
        return None
    sport = ESPN_SPORT[league]
    log = _get(f"https://site.web.api.espn.com/apis/common/v3/sports/{sport}/athletes/{pid}/gamelog")
    names = [n.lower() for n in log.get("names", [])]
    key = {"points": "points", "rebounds": "totalrebounds", "assists": "assists"}.get(stat, stat)
    idx = names.index(key) if key in names else None
    evmeta = log.get("events") or {}
    games = []
    for st in log.get("seasonTypes", []):
        if "regular" not in (st.get("displayName") or "").lower():
            continue
        for cat in st.get("categories", []):
            for ev in cat.get("events", []):
                if idx is None or idx >= len(ev.get("stats", [])):
                    continue
                try:
                    v = float(ev["stats"][idx])
                except (ValueError, TypeError):
                    continue
                m = evmeta.get(ev.get("eventId"), {})
                games.append({"date": (m.get("gameDate") or "")[:10], "opp": (m.get("opponent") or {}).get("abbreviation"), stat: v})
    games.sort(key=lambda g: g["date"], reverse=True)
    if not games:
        print(f"[enrich] no game log for {name}")
        return {"name": name, "espn_id": pid}
    last = games[:10]
    vals = [g[stat] for g in last]
    out = {"name": name, "stat": stat, "games_this_season": len(games),
           "season_avg": round(sum(g[stat] for g in games) / len(games), 1),
           "last_10_avg": round(sum(vals) / len(vals), 1),
           "last_5_avg": round(sum(vals[:5]) / len(vals[:5]), 1),
           "last_10_games": last}
    if line is not None:
        out["line"] = line
        out["went_over_line_last_10"] = f"{sum(v > line for v in vals)} of {len(vals)}"
    print(f"[enrich] {name}: season {out['season_avg']}, last 10 {out['last_10_avg']}, over {line}: {out.get('went_over_line_last_10')}")
    return out


# ---------------- The Odds API ----------------
def _match(ev, game):
    def norm(s): return (s or "").lower().replace(".", "")
    h, a = norm(game["home"]["name"]), norm(game["away"]["name"])
    eh, ea = norm(ev.get("home_team")), norm(ev.get("away_team"))
    last = lambda s: s.split()[-1] if s else ""
    return (eh == h or last(eh) == last(h)) and (ea == a or last(ea) == last(a))


def book_lines(game, espn_home_line=None):
    """Spread + total at each book for this game: OddsPapi first, The Odds API as backup."""
    rows = None
    try:
        import oddspapi
        rows = oddspapi.book_lines(game)
        if rows:
            print("[enrich] lines from OddsPapi")
    except Exception as e:
        print(f"[enrich] OddsPapi failed: {e}")
    if not rows:
        rows = _odds_api_rows(game)
    if not rows:
        return None
    # sanity check the sign against ESPN's line (guards against a home/away mix-up)
    try:
        espn = float(str(espn_home_line).replace("+", "")) if espn_home_line not in (None, "") else None
    except ValueError:
        espn = None
    med = statistics.median(r["home_spread"] for r in rows)
    if espn and med and abs(espn) >= 1 and (espn > 0) != (med > 0) and abs(abs(espn) - abs(med)) < 3:
        print(f"[enrich] flipping spread sign (ESPN {espn:+g} vs books {med:+g})")
        for r in rows:
            r["home_spread"], r["away_spread"] = r["away_spread"], r["home_spread"]
            r["home_price"], r["away_price"] = r.get("away_price"), r.get("home_price")
    return _summarise(rows)


def _odds_api_rows(game):
    """Backup source. Costs 2 credits (spreads + totals, 1 region)."""
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
    return rows or None


def _summarise(rows):
    us = [r for r in rows if r["key"] in PREFERRED]
    if len(us) >= 3:          # viewers can only bet US books, so compare those when we have enough
        rows = us
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
    lines = book_lines(game, (facts.get("espn_line_open_vs_now") or {}).get("home_now"))
    if lines:
        facts["sportsbook_lines"] = lines
        mv = track_line(state, game, lines)
        if mv:
            facts["our_tracked_movement"] = mv
    game["facts"] = facts
    print(f"[enrich] facts: {', '.join(facts) or 'none'}")
    return game
