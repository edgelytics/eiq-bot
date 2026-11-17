"""
oddspapi.py — live spreads + totals across sportsbooks from OddsPapi (ODDSPAPI_KEY).

Returns rows in the same shape the rest of the bot already uses:
  {"key", "book", "home_spread", "home_price", "away_spread", "away_price", "total", "over_price"}

Everything is looked up at run time (sport IDs, fixtures, market definitions), so nothing
breaks if OddsPapi renumbers things. Any failure returns None and the bot carries on.
"""
import datetime as dt
import os
import re
import time

import requests

KEY = (os.environ.get("ODDSPAPI_KEY") or "").strip().strip('"').strip() or None
BASE_V4 = "https://api.oddspapi.io/v4"
BASE_V5 = "https://v5.oddspapi.io/en"     # B2B keys live here; tried automatically if v4 says the key is invalid
SPORT_NAMES = {"NFL": "american football", "CFB": "american football",
               "NBA": "basketball", "NHL": "ice hockey"}
TOURNEY_HINT = {"NFL": ["nfl"], "CFB": ["ncaa", "college"], "NBA": ["nba"], "NHL": ["nhl"]}
BOOK_NAMES = {"draftkings": "DraftKings", "fanduel": "FanDuel", "betmgm": "BetMGM",
              "caesars": "Caesars", "williamhill": "Caesars", "bet365": "bet365",
              "fanatics": "Fanatics", "espnbet": "ESPN BET", "betrivers": "BetRivers",
              "hardrockbet": "Hard Rock", "hardrock": "Hard Rock", "thescore": "theScore",
              "circa": "Circa", "pinnacle": "Pinnacle", "ballybet": "Bally Bet"}
PREFERRED = ["draftkings", "fanduel", "betmgm", "caesars", "williamhill", "fanatics",
             "bet365", "espnbet", "thescore", "betrivers", "hardrockbet", "circa", "pinnacle"]

_last = [0.0]
_cache = {}
DEBUG = {}   # filled for odds_check.py so problems can be diagnosed from the repo


def _raw(url, params, headers):
    wait = 2.1 - (time.time() - _last[0])
    if wait > 0:
        time.sleep(wait)
    r = requests.get(url, params=params, headers=headers, timeout=30)
    _last[0] = time.time()
    return r


def _version():
    """4 or 5 — whichever API version accepts this key."""
    if "ver" not in _cache:
        r = _raw(f"{BASE_V5}/sports", {}, {"X-API-Key": KEY})
        if r.status_code == 200:
            _cache["ver"], _cache["sports"] = 5, r.json()
        else:
            r4 = _raw(f"{BASE_V4}/sports", {"apiKey": KEY}, {})
            if r4.status_code != 200:
                raise RuntimeError(f"key rejected by v5 (HTTP {r.status_code}: {r.text[:120]}) "
                                   f"and v4 (HTTP {r4.status_code}: {r4.text[:120]})")
            _cache["ver"], _cache["sports"] = 4, r4.json()
        DEBUG["api_version"] = _cache["ver"]
    return _cache["ver"]


def _get(path, **params):
    """GET on whichever API version the key belongs to, respecting the per-endpoint cooldown."""
    if _version() == 5:
        r = _raw(f"{BASE_V5}/{path}", params, {"X-API-Key": KEY})
    else:
        params["apiKey"] = KEY
        r = _raw(f"{BASE_V4}/{path}", params, {})
    if r.status_code != 200:
        raise RuntimeError(f"{path} HTTP {r.status_code}: {r.text[:200]}")
    return r.json()


def _flat_fixture(f):
    """v5 nests names (participants.participant1Name, tournament.tournamentName); flatten to the v4 shape."""
    p, t = f.get("participants") or {}, f.get("tournament") or {}
    return {**f, "participant1Name": f.get("participant1Name") or p.get("participant1Name"),
            "participant2Name": f.get("participant2Name") or p.get("participant2Name"),
            "tournamentName": f.get("tournamentName") or t.get("tournamentName"),
            "categoryName": f.get("categoryName") or (f.get("category") or {}).get("categoryName")}


def _v5_odds_as_v4(odds):
    """v5 odds: {book: {entryKey: quote{marketId, outcomeId, price...}}} -> v4 bookmakerOdds shape."""
    out = {}
    for book, entries in (odds.get("odds") or {}).items():
        meta = (odds.get("bookmakers") or {}).get(book) or {}
        mk = out.setdefault(book, {"suspended": meta.get("suspended"), "markets": {}})["markets"]
        for q in (entries or {}).values():
            if not isinstance(q, dict) or q.get("playerId") not in (0, "0", None):
                continue
            m = mk.setdefault(str(q.get("marketId")), {"outcomes": {}})
            m["outcomes"][str(q.get("outcomeId"))] = {"players": {"0": q}}
    return {"bookmakerOdds": out}


def _norm(s):
    return re.sub(r"[^a-z0-9 ]", "", (s or "").lower()).strip()


def _same_team(a, b):
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return False
    return a == b or a in b or b in a or a.split()[-1] == b.split()[-1]


def _american(p):
    """priceAmerican can be '+150' / '-110' / number; fall back to decimal price."""
    v = p.get("priceAmerican")
    try:
        if v not in (None, ""):
            return int(float(str(v).replace("+", "")))
    except ValueError:
        pass
    d = p.get("price")
    try:
        d = float(d)
        return int(round((d - 1) * 100)) if d >= 2 else int(round(-100 / (d - 1)))
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def _sport_id(league):
    _version()
    want = SPORT_NAMES[league]
    for s in _cache["sports"]:
        if _norm(s.get("sportName")) == want:
            return s.get("sportId")
    for s in _cache["sports"]:
        if want.split()[-1] in _norm(s.get("sportName")):
            return s.get("sportId")
    return None


def _markets(sport_id):
    """marketId -> {kind: 'spread'|'total', handicap, outcomes{outcomeId: name}} for full-game lines."""
    ck = ("markets", sport_id) if _version() == 5 else "markets"
    if ck not in _cache:
        _cache[ck] = _get("markets", sportId=sport_id) if _version() == 5 else _get("markets")
    _cache["markets_last"] = _cache[ck]
    out = {}
    for m in _cache[ck]:
        if m.get("sportId") != sport_id or m.get("playerProp"):
            continue
        period = _norm(m.get("period"))
        if period and period not in ("fulltime", "full time", "ft", "match", "game", "fulltimeincludingot", "result"):
            # keep only the full game, incl. overtime variants
            if "full" not in period and "ot" not in period:
                continue
        name, mtype = _norm(m.get("marketName")), _norm(m.get("marketType"))
        outs = {str(o.get("outcomeId")): _norm(o.get("outcomeName")) for o in m.get("outcomes") or []}
        if len(outs) != 2:
            continue
        if any(w in name for w in ("half", "quarter", "period", "inning", "1st", "2nd", "3rd", "team total")):
            continue
        hcap = m.get("handicap")
        if ("spread" in mtype or "handicap" in mtype or "spread" in name or "handicap" in name
                or "puck line" in name or "point spread" in name):
            out[str(m["marketId"])] = {"kind": "spread", "handicap": hcap, "outcomes": outs}
        elif ("total" in mtype or "over under" in name or "totals" in name) and \
                any("over" in v for v in outs.values()) and hcap:
            out[str(m["marketId"])] = {"kind": "total", "handicap": hcap, "outcomes": outs}
    return out


def _find_fixture(game, sport_id):
    start = dt.datetime.fromisoformat(game["start"].replace("Z", "+00:00"))
    frm = (start - dt.timedelta(hours=12)).strftime("%Y-%m-%dT%H:%M:%SZ")
    to = (start + dt.timedelta(hours=12)).strftime("%Y-%m-%dT%H:%M:%SZ")
    if _version() == 5:
        fx = [_flat_fixture(f) for f in _get("fixtures", sportId=sport_id,
                                             startTimeFrom=int((start - dt.timedelta(hours=12)).timestamp()),
                                             startTimeTo=int((start + dt.timedelta(hours=12)).timestamp()))]
    else:
        fx = _get("fixtures", sportId=sport_id, **{"from": frm, "to": to})
    DEBUG["fixtures_sample"] = [f"{f.get('participant1Name')} v {f.get('participant2Name')} | {f.get('tournamentName')}" for f in fx[:15]]
    hints = TOURNEY_HINT[game["league"]]
    best = None
    for f in fx:
        p1, p2 = f.get("participant1Name"), f.get("participant2Name")
        home, away = game["home"]["name"], game["away"]["name"]
        if _same_team(p1, home) and _same_team(p2, away):
            flip = False
        elif _same_team(p1, away) and _same_team(p2, home):
            flip = True
        else:
            continue
        t = _norm(f.get("tournamentName")) + " " + _norm(f.get("categoryName"))
        score = 1 if any(h in t for h in hints) else 0
        if best is None or score > best[0]:
            best = (score, f, flip)
    return (best[1], best[2]) if best else (None, None)


def _best_line(entries):
    """Among a book's alternate lines, pick the main one (flagged mainLine, else prices closest to even)."""
    main = [e for e in entries if e["main"]]
    pool = main or entries
    return min(pool, key=lambda e: abs((e["p1"] or 0) + (e["p2"] or 0)) if e["p1"] and e["p2"] else 999)


def book_lines(game):
    """Rows of spread/total per sportsbook for this game, or None."""
    if not KEY or game.get("league") not in SPORT_NAMES:
        return None
    sid = _sport_id(game["league"])
    if not sid:
        print("[oddspapi] sport not found")
        return None
    fixture, flip = _find_fixture(game, sid)
    if not fixture:
        print("[oddspapi] game not found")
        return None
    mk = _markets(sid)
    DEBUG["sport_markets_sample"] = [{k: m.get(k) for k in ("marketId", "marketName", "marketType", "handicap", "period")}
                                     for m in _cache["markets_last"] if m.get("sportId") == sid][:40]
    DEBUG["markets_used"] = len(mk)
    if _version() == 5:
        odds = _v5_odds_as_v4(_get("fixtures/odds", fixtureId=fixture["fixtureId"]))
    else:
        odds = _get("odds", fixtureId=fixture["fixtureId"], oddsFormat="american")
    DEBUG["books_raw"] = {b: list((v.get("markets") or {}))[:12] for b, v in list((odds.get("bookmakerOdds") or {}).items())[:12]}
    rows = []
    for slug, bk in (odds.get("bookmakerOdds") or {}).items():
        if bk.get("bookmakerIsActive") is False or bk.get("suspended"):
            continue
        spreads, totals = [], []
        for mid, m in (bk.get("markets") or {}).items():
            meta = mk.get(str(mid))
            if not meta or m.get("marketActive") is False:
                continue
            oc = m.get("outcomes") or {}
            ids = list(meta["outcomes"])
            prices, main = [], False
            for oid in ids:
                players = (oc.get(oid) or {}).get("players") or {}
                pl = players.get("0") or next(iter(players.values()), None)
                if not pl or pl.get("active") is False:
                    prices.append(None)
                    continue
                main = main or bool(pl.get("mainLine"))
                prices.append(_american(pl))
            if None in prices:
                continue
            e = {"h": float(meta["handicap"]), "p1": prices[0], "p2": prices[1], "main": main, "names": meta["outcomes"], "ids": ids}
            (spreads if meta["kind"] == "spread" else totals).append(e)
        if not spreads:
            continue
        s = _best_line(spreads)
        # the handicap belongs to participant1; participant1 is ESPN's home team unless flipped
        p1_spread = s["h"]
        if flip:
            home_spread, home_price, away_price = -p1_spread, s["p2"], s["p1"]
        else:
            home_spread, home_price, away_price = p1_spread, s["p1"], s["p2"]
        row = {"key": slug, "book": BOOK_NAMES.get(slug, slug.replace("_", " ").title()),
               "home_spread": home_spread, "home_price": home_price,
               "away_spread": -home_spread, "away_price": away_price}
        if totals:
            t = _best_line(totals)
            over_first = "over" in t["names"][t["ids"][0]]
            row["total"], row["over_price"] = abs(t["h"]), (t["p1"] if over_first else t["p2"])
        rows.append(row)
    if not rows:
        print("[oddspapi] no spread prices found")
        return None
    rows.sort(key=lambda r: PREFERRED.index(r["key"]) if r["key"] in PREFERRED else 99)
    print(f"[oddspapi] {len(rows)} books: " + ", ".join(f"{r['book']} {r['home_spread']:+g}" for r in rows[:8]))
    return rows
