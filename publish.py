"""
publish.py — posts a Reel to Instagram via the official Graph API,
with a trending track from Instagram's Audio API attached.

Needs: an Instagram Business account linked to a Facebook Page, a Meta app using
Facebook Login, permissions instagram_basic + instagram_content_publish,
and env vars IG_USER_ID + IG_ACCESS_TOKEN. See README.
"""
import json
import os
import time
import requests

from config import IG_USER_ID, IG_TOKEN, GRAPH_VERSION, IG_MUSIC_VOLUME, IG_VIDEO_VOLUME, DISCORD_WEBHOOK

G = f"https://graph.facebook.com/{GRAPH_VERSION}"


class IGError(Exception):
    pass


def _check(r):
    try:
        j = r.json()
    except ValueError:
        raise IGError(f"HTTP {r.status_code}: {r.text[:300]}")
    if r.status_code >= 400 or "error" in j:
        raise IGError(json.dumps(j.get("error", j))[:500])
    return j


def trending_music(query=None):
    """Instagram's trending (or searched) music that's cleared for third-party use."""
    params = {"audio_type": "music", "user_id": IG_USER_ID, "access_token": IG_TOKEN}
    if query:
        params["search_query"] = query
    j = _check(requests.get(f"{G}/ig_audio", params=params, timeout=30))
    return j.get("audio", j.get("data", []))


def publishing_quota():
    j = _check(requests.get(f"{G}/{IG_USER_ID}/content_publishing_limit",
                            params={"fields": "quota_usage,config", "access_token": IG_TOKEN}, timeout=30))
    return (j.get("data") or [{}])[0]


def _create_container(caption, audio_id=None, strategy="json"):
    data = {"media_type": "REELS", "upload_type": "resumable", "caption": caption,
            "share_to_feed": "true", "access_token": IG_TOKEN}
    if audio_id:
        conf = {"audio_id": str(audio_id), "audio_volume": IG_MUSIC_VOLUME, "video_volume": IG_VIDEO_VOLUME}
        if strategy == "loop":
            conf["should_loop_audio"] = True      # some tracks are shorter than the reel
        data["audio_configuration"] = json.dumps(conf)
    return _check(requests.post(f"{G}/{IG_USER_ID}/media", data=data, timeout=60))


def host_video(path):
    """Put the reel at a public URL for Instagram to fetch (Meta's documented way to attach a song is video_url).
    Inside GitHub Actions: force-push the file alone to a throwaway 'reel-tmp' branch of this (public) repo."""
    import subprocess, tempfile, shutil
    repo, tok = os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_TOKEN")
    if not (repo and tok):
        raise IGError("no GitHub hosting available (GITHUB_REPOSITORY/GITHUB_TOKEN not set)")
    name = f"reel_{int(time.time())}.mp4"
    d = tempfile.mkdtemp()
    shutil.copy(path, os.path.join(d, name))
    run = lambda *a: subprocess.run(a, cwd=d, check=True, capture_output=True, text=True)
    run("git", "init", "-q")
    run("git", "checkout", "-q", "--orphan", "reel-tmp")
    run("git", "-c", "user.name=eiq-bot", "-c", "user.email=eiq-bot@users.noreply.github.com", "add", name)
    run("git", "-c", "user.name=eiq-bot", "-c", "user.email=eiq-bot@users.noreply.github.com", "commit", "-q", "-m", "temp reel for Instagram")
    run("git", "push", "-q", "--force", f"https://x-access-token:{tok}@github.com/{repo}.git", "HEAD:reel-tmp")
    url = f"https://raw.githubusercontent.com/{repo}/reel-tmp/{name}"
    for _ in range(20):                       # wait until the file is publicly reachable
        try:
            if requests.head(url, timeout=15).status_code == 200:
                print(f"[publish] reel hosted at {url}")
                return url
        except requests.RequestException:
            pass
        time.sleep(3)
    raise IGError("hosted reel never became reachable")


def _create_container_url(caption, video_url, audio_id):
    data = {"media_type": "REELS", "video_url": video_url, "caption": caption,
            "share_to_feed": "true", "access_token": IG_TOKEN,
            "audio_configuration": json.dumps({"audio_id": str(audio_id), "audio_volume": IG_MUSIC_VOLUME,
                                               "video_volume": IG_VIDEO_VOLUME})}
    return _check(requests.post(f"{G}/{IG_USER_ID}/media", data=data, timeout=60))


def media_audio_type(mid, tries=4):
    """MUSIC if Instagram actually attached a library song, ORIGINAL_SOUND if not (None = unknown)."""
    for i in range(tries):
        try:
            j = _check(requests.get(f"{G}/{mid}", params={"fields": "media_audio_type", "access_token": IG_TOKEN}, timeout=30))
            if j.get("media_audio_type"):
                return j["media_audio_type"]
        except IGError as e:
            print(f"[publish] media_audio_type check failed: {e}")
        time.sleep(6 * (i + 1))
    return None


def _upload(container, path):
    uri = container.get("uri") or f"https://rupload.facebook.com/ig-api-upload/{GRAPH_VERSION}/{container['id']}"
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        r = requests.post(uri, data=f, timeout=600, headers={
            "Authorization": f"OAuth {IG_TOKEN}", "offset": "0", "file_size": str(size)})
    _check(r)


def _wait_ready(cid, timeout=600):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = _check(requests.get(f"{G}/{cid}", params={"fields": "status_code,status", "access_token": IG_TOKEN}, timeout=30))
        st = j.get("status_code")
        if st == "FINISHED":
            return
        if st in ("ERROR", "EXPIRED"):
            raise IGError(f"container {st}: {j.get('status')}")
        time.sleep(8)
    raise IGError("container processing timed out")


def _publish(cid):
    j = _check(requests.post(f"{G}/{IG_USER_ID}/media_publish",
                             data={"creation_id": cid, "access_token": IG_TOKEN}, timeout=60))
    mid = j["id"]
    try:
        link = _check(requests.get(f"{G}/{mid}", params={"fields": "permalink", "access_token": IG_TOKEN}, timeout=30)).get("permalink")
    except IGError:
        link = None
    return mid, link


def post_reel(post_mp4, preview_mp4, caption, track=None, strategy="json"):
    """
    Try: voice/SFX video + Instagram track attached.
    If attaching music fails: post the version with our own music bed baked in.
    """
    if not (IG_USER_ID and IG_TOKEN):
        raise IGError("IG_USER_ID / IG_ACCESS_TOKEN not set")
    attempts = []
    if track:
        label = f"{track.get('title')} — {track.get('display_artist')}"
        if strategy == "url":
            # Meta's documented path: hosted video_url + audio_configuration
            attempts.append(("url", post_mp4, track.get("audio_id"), label))
        else:
            # resumable upload (Instagram has been dropping the song this way) — keep our beat under it
            attempts.append(("upload", preview_mp4 if strategy != "json" else post_mp4, track.get("audio_id"), label))
    attempts.append(("upload", preview_mp4, None, "built-in music bed"))
    last = None
    for how, path, audio_id, label in attempts:
        try:
            if how == "url":
                c = _create_container_url(caption, host_video(path), audio_id)
            else:
                c = _create_container(caption, audio_id, strategy)
                _upload(c, path)
            _wait_ready(c["id"])
            mid, link = _publish(c["id"])
            res = {"media_id": mid, "permalink": link, "audio": label}
            if audio_id:
                atype = media_audio_type(mid)
                res["audio_type"] = atype
                res["music_attached"] = atype == "MUSIC" if atype else None
                print(f"[publish] Instagram reports audio type: {atype} (strategy={strategy}, {how})")
            return res
        except IGError as e:
            print(f"[publish] attempt with {label} failed: {e}")
            last = e
    raise last


def notify(msg, file_path=None):
    if not DISCORD_WEBHOOK:
        return
    try:
        if file_path and os.path.getsize(file_path) >= 24 * 1024 * 1024:
            import subprocess
            small = file_path.replace(".mp4", "_discord.mp4")
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", file_path, "-vf", "scale=540:-2",
                            "-c:v", "libx264", "-crf", "28", "-preset", "veryfast", "-c:a", "aac", "-b:a", "96k", small], check=True)
            file_path = small
        if file_path and os.path.getsize(file_path) < 24 * 1024 * 1024:
            with open(file_path, "rb") as f:
                requests.post(DISCORD_WEBHOOK, data={"content": msg[:1900]}, files={"file": (os.path.basename(file_path), f)}, timeout=60)
        else:
            requests.post(DISCORD_WEBHOOK, json={"content": msg[:1900]}, timeout=30)
    except Exception as e:
        print(f"[notify] {e}")
