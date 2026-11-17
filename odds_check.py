"""odds_check.py — one-off test of the odds feed: picks the top upcoming game and saves what the bot sees."""
import json
import pathlib

from trends import get_trending
from enrich import espn_facts, book_lines
import config

out = {"games": []}

# --- key diagnostics: shape of the saved secret (never the key itself) + every auth style ---
import os, re, requests
_raw_key = os.environ.get("ODDSPAPI_KEY") or ""
try:
    import oddspapi as _op
    _k = _op.KEY or ""
except Exception:
    _k = _raw_key.strip()
out["key_info"] = {
    "saved_length": len(_raw_key), "cleaned_length": len(_k),
    "has_space_inside": " " in _k, "had_newline": "\n" in _raw_key or "\r" in _raw_key,
    "char_types": "".join(sorted(set("a" if c.isalpha() else "9" if c.isdigit() else c for c in _k))),
    "looks_labelled": bool(re.match(r"(?i)\s*(x-)?api.?key\s*[:=]", _k)),
}
_probes = {}
for name, url, params, headers in [
    ("v5 header", "https://v5.oddspapi.io/en/sports", {}, {"X-API-Key": _k}),
    ("v5 query", "https://v5.oddspapi.io/en/sports", {"apiKey": _k}, {}),
    ("v4 query", "https://api.oddspapi.io/v4/sports", {"apiKey": _k}, {}),
    ("v4 header", "https://api.oddspapi.io/v4/sports", {}, {"X-API-Key": _k}),
]:
    try:
        r = requests.get(url, params=params, headers=headers, timeout=20)
        _probes[name] = f"{r.status_code} {r.text[:90]}"
    except Exception as e:
        _probes[name] = f"error {e}"
    import time; time.sleep(2.2)
out["auth_probes"] = _probes
print(json.dumps({"key_info": out["key_info"], "auth_probes": _probes}, indent=1))
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
