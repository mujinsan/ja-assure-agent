"""Publishing adapters. Dry-run by default; Ayrshare only when a key is set.

publish() returns (post_id, provider) or raises. Nothing here prints or logs
the API key - it travels only in the Authorization header.
"""
import json, os, uuid
from datetime import datetime, timezone

OUTBOX = os.getenv("OUTBOX_PATH", "outbox.jsonl")
# base per Ayrshare's docs; /post, /user and /media/uploadUrl hang off it
AYRSHARE_BASE = os.getenv("AYRSHARE_BASE", "https://api.ayrshare.com/api")
AYRSHARE_URL = f"{AYRSHARE_BASE}/post"

# Strategy 2 media host. Anonymous, no key; swap _anon_upload() to change it.
FALLBACK_HOST = os.getenv("MEDIA_FALLBACK_HOST", "catbox.moe")
FALLBACK_HOST_URL = os.getenv("MEDIA_FALLBACK_URL", "https://catbox.moe/user/api.php")


class ValidationError(RuntimeError):
    """Ayrshare rejected the request itself. Retrying cannot help."""


class MediaUploadBlocked(RuntimeError):
    """Ayrshare's media endpoint refused us: plan, auth or payment (401/402/403)."""

# Ayrshare's platform slugs differ from the labels used in config.PLATFORMS
PLATFORM_SLUG = {"linkedin": "linkedin", "instagram": "instagram",
                 "x": "twitter", "twitter": "twitter", "facebook": "facebook"}


def live_armed():
    """Real posting needs BOTH a key and the human-armed DB switch."""
    import db
    return bool(os.getenv("AYRSHARE_API_KEY")) and db.live_posting()


def active_provider():
    """"ayrshare" only when live posting is armed; otherwise "dry-run"."""
    return "ayrshare" if live_armed() else "dry-run"


def _headers():
    key = os.getenv("AYRSHARE_API_KEY")
    if not key:
        raise ValidationError("AYRSHARE_API_KEY not set")
    return {"Authorization": f"Bearer {key}"}      # key never logged


def linked_platforms():
    """Lowercased activeSocialAccounts from GET /user, or an empty set."""
    import requests
    try:
        r = requests.get(f"{AYRSHARE_BASE}/user", headers=_headers(), timeout=20)
        r.raise_for_status()
        return {str(p).strip().lower() for p in (r.json().get("activeSocialAccounts") or [])}
    except Exception as e:
        print(f"[publisher] could not read linked accounts: {e}")
        return set()


def latest_media(asset):
    """Newest local media file on the asset: video wins over image."""
    for key in ("video_path", "image_path"):
        val = (asset.get(key) or "").strip()
        if val:
            return val, ("video" if key == "video_path" else "image")
    return None, None


def preflight(asset):
    """Reason this asset must not be posted live, or None.

    Runs before the worker claims anything, so a rejected asset is marked
    failed without a wasted API call.
    """
    if not live_armed():
        return None
    slug = PLATFORM_SLUG.get((asset.get("platform") or "").strip().lower())
    if not slug:
        return f"no Ayrshare platform mapping for {asset.get('platform')!r}"
    media, _ = latest_media(asset)
    if slug == "instagram" and not media:
        return "Instagram requires an image or video"
    linked = linked_platforms()
    if linked and slug not in linked:
        return f"{slug} is not linked in Ayrshare (linked: {', '.join(sorted(linked)) or 'none'})"
    return None


def _ayrshare_upload(path):
    """Strategy 1: Ayrshare's own two-step upload. Returns accessUrl.

    Raises MediaUploadBlocked on 401/402/403 - those mean the endpoint is not
    available to this key or plan, which a retry cannot fix but a different
    host can.
    """
    import mimetypes, requests
    ext = os.path.splitext(path)[1].lstrip(".").lower() or "png"
    r = requests.get(f"{AYRSHARE_BASE}/media/uploadUrl", headers=_headers(),
                     params={"fileName": os.path.basename(path), "contentType": ext},
                     timeout=30)
    if r.status_code in (401, 402, 403):
        raise MediaUploadBlocked(f"HTTP {r.status_code} from /media/uploadUrl")
    r.raise_for_status()
    info = r.json()
    upload_url, access_url = info.get("uploadUrl"), info.get("accessUrl")
    if not upload_url or not access_url:
        raise ValidationError(f"upload URL response missing fields: {str(info)[:160]}")
    ctype = info.get("contentType") or mimetypes.guess_type(path)[0] or "application/octet-stream"
    with open(path, "rb") as fh:
        put = requests.put(upload_url, data=fh.read(),
                           headers={"Content-Type": ctype}, timeout=120)
    if put.status_code in (401, 402, 403):
        raise MediaUploadBlocked(f"HTTP {put.status_code} uploading to the presigned URL")
    put.raise_for_status()
    return access_url


def _anon_upload(path):
    """Strategy 2: anonymous public image host. Returns a direct URL.

    Swap this single function to change host. Current host is catbox.moe:
    POST multipart to /user/api.php with reqtype=fileupload and fileToUpload,
    which answers with the direct URL as plain text. No key, no account.
    Anonymous uploads are kept until two years of inactivity.
    """
    import requests
    with open(path, "rb") as fh:
        r = requests.post(
            FALLBACK_HOST_URL,
            data={"reqtype": "fileupload"},
            files={"fileToUpload": (os.path.basename(path), fh)},
            # the CDN drops requests carrying the default python-requests agent
            headers={"User-Agent": "Mozilla/5.0 (compatible; ja-assure/1.0)"},
            timeout=120)
    r.raise_for_status()
    url = (r.text or "").strip()
    if not url.startswith("https://"):
        raise RuntimeError(f"unexpected response from {FALLBACK_HOST}: {url[:120]!r}")
    return url


def _public_media_url(path):
    """A publicly reachable URL for a local file. Returns (url, strategy).

    Ayrshare needs a URL it can fetch, so a local path must be hosted somewhere
    first. Strategy 1 is Ayrshare's own endpoint; strategy 2 is an anonymous
    host, used when strategy 1 is unavailable rather than failing the post.
    """
    if path.startswith(("http://", "https://")):
        return path, "already-public"

    plan_blocked, first_error = False, None
    try:
        return _ayrshare_upload(path), "ayrshare"
    except MediaUploadBlocked as e:
        plan_blocked, first_error = True, e
        print(f"[publisher] strategy 1 (Ayrshare media upload) not permitted: {e}"
              f" - falling back to {FALLBACK_HOST}")
    except Exception as e:
        first_error = e
        print(f"[publisher] strategy 1 (Ayrshare media upload) failed: {e}"
              f" - falling back to {FALLBACK_HOST}")

    try:
        return _anon_upload(path), FALLBACK_HOST
    except Exception as e2:
        lead = ("Ayrshare upload not permitted on this plan"
                if plan_blocked else f"Ayrshare media upload failed ({first_error})")
        raise ValidationError(
            f"{lead}; fallback host {FALLBACK_HOST} also failed ({e2}). "
            f"Set image_path to a public https URL to bypass both.")


def dry_run_mode():
    return active_provider() == "dry-run"


def publish(asset):
    """Publish one asset. Returns (post_id, provider, post_url). Raises on failure."""
    provider = active_provider()
    if provider == "ayrshare":
        pid, url = _ayrshare(asset)
        return pid, provider, url
    return _dry_run(asset), provider, None


def update(asset, post_id):
    """Push an edit to a published post. Returns (post_id, provider, post_url)."""
    provider = active_provider()
    if provider == "ayrshare":
        pid, url = _ayrshare_update(asset, post_id)
        return pid, provider, url
    return _dry_run(asset, event="update", post_id=post_id), provider, None


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


def _raise_for_ayrshare(resp):
    """Split validation errors (never retry) from transport errors (retry)."""
    try:
        data = resp.json()
    except ValueError:
        data = {}
    if resp.status_code >= 500:
        raise RuntimeError(f"ayrshare {resp.status_code}: {resp.text[:200]}")
    if resp.status_code >= 400 or str(data.get("status", "")).lower() == "error":
        code = data.get("code")
        msg = data.get("message") or resp.text[:200]
        raise ValidationError(f"ayrshare {resp.status_code}"
                              + (f" [{code}]" if code else "") + f": {msg}")
    return data


def _post_ids(data):
    """(id, postUrl) from the documented response shape."""
    entries = data.get("postIds") or []
    first = entries[0] if entries and isinstance(entries[0], dict) else {}
    for e in entries:
        if isinstance(e, dict) and str(e.get("status", "")).lower() == "error":
            raise ValidationError(f"ayrshare rejected {e.get('platform')}: "
                                  f"{e.get('message') or e}")
    return (first.get("id") or data.get("id"), first.get("postUrl"))


def _body_for(asset):
    """Documented POST /post body, with media uploaded to a public accessUrl."""
    slug = PLATFORM_SLUG.get((asset.get("platform") or "").strip().lower())
    if not slug:
        raise ValidationError(f"no Ayrshare platform mapping for {asset.get('platform')!r}")

    linked = linked_platforms()
    if linked and slug not in linked:
        raise ValidationError(f"{slug} is not linked in Ayrshare")

    body = {"post": asset.get("content") or "", "platforms": [slug]}
    path, kind = latest_media(asset)
    if path:
        url, strategy = _public_media_url(path)
        print(f"[publisher] media hosted via {strategy}")
        body["mediaUrls"] = [url]
        if kind == "video":
            body["isVideo"] = True
    elif slug == "instagram":
        raise ValidationError("Instagram requires an image or video")
    return body


def _ayrshare(asset):
    """POST /post. Returns (post_id, post_url)."""
    import requests
    r = requests.post(AYRSHARE_URL, headers=_headers(), json=_body_for(asset), timeout=60)
    data = _raise_for_ayrshare(r)
    pid, url = _post_ids(data)
    if not pid:
        raise ValidationError(f"ayrshare returned no post id: {str(data)[:200]}")
    return pid, url


def _ayrshare_update(asset, post_id):
    """PUT /post to edit a live post. Returns (post_id, post_url)."""
    import requests
    body = _body_for(asset)
    body["id"] = post_id
    r = requests.put(AYRSHARE_URL, headers=_headers(), json=body, timeout=60)
    data = _raise_for_ayrshare(r)
    pid, url = _post_ids(data)
    return (pid or post_id), url


def last_outbox_entry(post_id):
    """Most recent dry-run outbox record for a post_id, or None."""
    if not post_id or not os.path.exists(OUTBOX):
        return None
    found = None
    try:
        with open(OUTBOX, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    continue
                if rec.get("post_id") == post_id:
                    found = rec
    except OSError:
        return None
    return found
