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


def _dry_run(asset):
    """Append the post to outbox.jsonl and hand back a fake id."""
    record = {
        "brand": asset.get("brand"),
        "platform": asset.get("platform"),
        "language": asset.get("language"),
        "content": asset.get("content"),
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    with open(OUTBOX, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    return f"dry-{uuid.uuid4().hex[:8]}"


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
