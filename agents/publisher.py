"""Publishing adapters. Dry-run by default; Ayrshare only when a key is set.

publish() returns (post_id, provider) or raises. Nothing here prints or logs
the API key - it travels only in the Authorization header.
"""
import json, os, uuid
from datetime import datetime, timezone

OUTBOX = os.getenv("OUTBOX_PATH", "outbox.jsonl")
AYRSHARE_URL = "https://app.ayrshare.com/api/post"

# Ayrshare's platform slugs differ from the labels used in config.PLATFORMS
PLATFORM_SLUG = {"linkedin": "linkedin", "instagram": "instagram",
                 "x": "twitter", "twitter": "twitter", "facebook": "facebook"}


def active_provider():
    """"ayrshare" when a key is configured, otherwise "dry-run"."""
    return "ayrshare" if os.getenv("AYRSHARE_API_KEY") else "dry-run"


def dry_run_mode():
    return active_provider() == "dry-run"


def publish(asset):
    """Publish one asset. Returns (post_id, provider). Raises on failure."""
    provider = active_provider()
    if provider == "ayrshare":
        return _ayrshare(asset), provider
    return _dry_run(asset), provider


def update(asset, post_id):
    """Push an edit to an already-published post. Returns (post_id, provider)."""
    provider = active_provider()
    if provider == "ayrshare":
        return _ayrshare_update(asset, post_id), provider
    return _dry_run(asset, event="update", post_id=post_id), provider


def _dry_run(asset, event="post", post_id=None):
    """Append the post to outbox.jsonl and hand back a fake id."""
    record = {
        "brand": asset.get("brand"),
        "platform": asset.get("platform"),
        "language": asset.get("language"),
        "content": asset.get("content"),
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "event": event,
    }
    if asset.get("image_path"):
        record["image_path"] = asset["image_path"]
    if asset.get("video_path"):
        record["video_path"] = asset["video_path"]
    if post_id:
        record["post_id"] = post_id
    with open(OUTBOX, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    # an update keeps the id of the post it is updating
    return post_id or f"dry-{uuid.uuid4().hex[:8]}"


def _ayrshare(asset):
    """POST to Ayrshare and return its post id."""
    import requests
    key = os.getenv("AYRSHARE_API_KEY")
    if not key:
        raise RuntimeError("AYRSHARE_API_KEY not set")

    label = (asset.get("platform") or "").strip().lower()
    slug = PLATFORM_SLUG.get(label)
    if not slug:
        raise RuntimeError(f"no Ayrshare platform mapping for {asset.get('platform')!r}")

    r = requests.post(
        AYRSHARE_URL,
        headers={"Authorization": f"Bearer {key}"},
        json={"post": asset.get("content") or "", "platforms": [slug]},
        timeout=30)
    r.raise_for_status()
    data = r.json()
    if str(data.get("status", "")).lower() in ("error", "fail", "failed"):
        raise RuntimeError(f"ayrshare rejected the post: {str(data)[:200]}")

    post_id = data.get("id")
    if not post_id:
        ids = data.get("postIds") or []
        post_id = (ids[0].get("id") if ids and isinstance(ids[0], dict) else None)
    if not post_id:
        raise RuntimeError(f"ayrshare returned no post id: {str(data)[:200]}")
    return post_id


def _ayrshare_update(asset, post_id):
    """Ayrshare edit endpoint. Untested against the live API - no key here."""
    import requests
    key = os.getenv("AYRSHARE_API_KEY")
    if not key:
        raise RuntimeError("AYRSHARE_API_KEY not set")
    r = requests.put(
        AYRSHARE_URL,
        headers={"Authorization": f"Bearer {key}"},
        json={"id": post_id, "post": asset.get("content") or ""},
        timeout=30)
    r.raise_for_status()
    data = r.json()
    if str(data.get("status", "")).lower() in ("error", "fail", "failed"):
        raise RuntimeError(f"ayrshare rejected the update: {str(data)[:200]}")
    return data.get("id") or post_id
