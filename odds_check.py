"""odds_check.py — one-off test of the odds feed: picks the top upcoming game and saves what the bot sees."""
import json
import pathlib

from trends import get_trending
from enrich import espn_facts, book_lines
import config

out = {"games": []}
try:
    import oddspapi
    oddspapi._version()
    out["api_version"] = oddspapi._cache.get("ver")
    out["sports"] = [f"{s.get('sportId')}: {s.get('sportName')}" for s in oddspapi._cache.get("sports", [])][:60]
except Exception as e:
    out["sports"] = str(e)
for g in get_trending(config.LEAGUES, top_n=3)[:3]:
    facts = espn_facts(g)
    espn_line = (facts.get("espn_line_open_vs_now") or {}).get("home_now")
    try:
        lines = book_lines(g, espn_line)
    except Exception as e:
        lines = {"error": str(e)}
    import oddspapi
    out["games"].append({"game": f"{g['away']['name']} @ {g['home']['name']} ({g['league']})",
                         "espn_home_line": espn_line, "lines": lines, "debug": dict(oddspapi.DEBUG)})
    oddspapi.DEBUG.clear()
    print(json.dumps(out["games"][-1], indent=1)[:1500])
pathlib.Path("state").mkdir(exist_ok=True)
pathlib.Path("state/odds_check.json").write_text(json.dumps(out, indent=1))
