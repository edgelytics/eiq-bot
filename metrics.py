"""
metrics.py — pulls Instagram numbers into state/metrics.json for the Command Center.

Runs at the end of every workflow run (and on demand with mode=metrics).
Never raises: a stats hiccup must not break posting.
"""
import datetime as dt
import json
import os
import pathlib

import requests

from config import IG_USER_ID, IG_TOKEN, GRAPH_VERSION

G = f"https://graph.facebook.com/{GRAPH_VERSION}"
PATH = pathlib.Path("state/metrics.json")
INS_ERR = []
REEL_METRICS = ["views", "reach", "saved", "shares", "total_interactions"]


def _get(url, **params):
    params["access_token"] = IG_TOKEN
    r = requests.get(url, params=params, timeout=30)
    j = r.json()
    if "error" in j:
        raise RuntimeError(j["error"].get("message", "graph error"))
    return j


def _insights(mid):
    """Per-reel insights. If one metric isn't allowed, drop it and retry."""
    metrics = list(REEL_METRICS)
    while metrics:
        try:
            j = _get(f"{G}/{mid}/insights", metric=",".join(metrics))
            return {d["name"]: (d.get("total_value") or (d.get("values") or [{}])[0]).get("value", 0)
                    for d in j.get("data", [])}
        except RuntimeError as e:
            bad = next((m for m in metrics if m in str(e)), None)
            if not bad:
                INS_ERR.append(str(e)[:200])
                return {}
            metrics.remove(bad)
    return {}


def collect():
    old = json.loads(PATH.read_text()) if PATH.exists() else {}
    now = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    out = {"updated": now.isoformat(), "account": old.get("account", {}),
           "history": old.get("history", []), "media": old.get("media", []), "error": None}
    try:
        acct = _get(f"{G}/{IG_USER_ID}", fields="username,followers_count,follows_count,media_count")
        out["account"] = {k: acct.get(k) for k in ("username", "followers_count", "follows_count", "media_count")}

        media = _get(f"{G}/{IG_USER_ID}/media", limit=30,
                     fields="id,caption,permalink,timestamp,media_product_type,like_count,comments_count,thumbnail_url")
        rows = []
        for m in media.get("data", []):
            ins = _insights(m["id"])
            try:
                atype = _get(f"{G}/{m['id']}", fields="media_audio_type").get("media_audio_type")
            except RuntimeError:
                atype = None
            rows.append({
                "id": m["id"], "permalink": m.get("permalink"), "timestamp": m.get("timestamp"),
                "type": m.get("media_product_type"), "thumb": m.get("thumbnail_url"),
                "caption": (m.get("caption") or "").split("\n")[0][:140],
                "likes": m.get("like_count", 0), "comments": m.get("comments_count", 0),
                "views": ins.get("views", 0), "reach": ins.get("reach", 0), "saves": ins.get("saved", 0),
                "shares": ins.get("shares", 0), "interactions": ins.get("total_interactions", 0),
                "audio_type": atype,
            })
        out["media"] = rows
        if INS_ERR and not any(r["views"] or r["reach"] for r in rows):
            out["error"] = "Reel views unavailable: " + INS_ERR[0]

        snap = {"t": now.isoformat(), "followers": out["account"].get("followers_count"),
                "views": sum(r["views"] for r in rows), "likes": sum(r["likes"] for r in rows)}
        hist = out["history"]
        # one point per hour is plenty
        if hist and hist[-1]["t"][:13] == snap["t"][:13]:
            hist[-1] = snap
        else:
            hist.append(snap)
        out["history"] = hist[-720:]
    except Exception as e:  # keep the last good numbers, note what went wrong
        out["error"] = str(e)[:300]
    PATH.parent.mkdir(exist_ok=True)
    PATH.write_text(json.dumps(out, indent=1))
    print(f"[metrics] followers={out['account'].get('followers_count')} posts={len(out['media'])} error={out['error']}")


if __name__ == "__main__":
    if IG_USER_ID and IG_TOKEN:
        collect()
    else:
        print("[metrics] IG secrets not set, skipping")
