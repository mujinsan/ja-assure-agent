"""Project 2 posting worker.

Polls the assets table for status='approved', claims each one atomically, then
publishes it through agents/publisher.py.

  python worker.py           # poll forever every POLL_SECONDS
  python worker.py --once    # a single pass, then exit

Safety: only status='approved' is ever picked up, the claim is conditional so
two workers cannot post the same asset twice, and mock-generated assets are
never published.
"""
import argparse, os, sys, time
from dotenv import load_dotenv

load_dotenv()

import db
from agents import publisher

POLL_SECONDS = int(os.getenv("POLL_SECONDS", "10") or 10)
MAX_ATTEMPTS = 3


def _publish_claimed(asset):
    """Publish (or update) an already-claimed asset, retrying with backoff.

    An asset that already carries a post_id is a post-publish edit, so it goes
    through the adapter's update path instead of creating a second post.
    Returns (post_id, provider) or raises the last error after MAX_ATTEMPTS.
    """
    existing = asset.get("post_id")
    last = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            if existing:
                return publisher.update(asset, existing)
            return publisher.publish(asset)
        except publisher.ValidationError as e:
            # the request itself was rejected; retrying sends the same thing
            print(f"[worker] #{asset['id']} rejected, not retrying: {e}")
            raise
        except Exception as e:
            last = e
            print(f"[worker] #{asset['id']} attempt {attempt}/{MAX_ATTEMPTS} failed: {e}")
            if attempt < MAX_ATTEMPTS:
                time.sleep(2 ** (attempt - 1))   # 1s, 2s
    raise last


def run_once():
    """One pass over the due approved queue. Returns a counts dict."""
    counts = {"posted": 0, "updated": 0, "failed": 0,
              "skipped_mock": 0, "lost_race": 0, "paused": 0}

    # global kill switch, stored in the DB so every worker and session sees it
    if db.publishing_paused():
        counts["paused"] = 1
        return counts

    # only assets whose publish_at has arrived; never anything but 'approved',
    # which is the human sign-off gate
    for asset in db.due_approved():
        # never publish template text, even if it somehow reached approved
        if asset.get("provider") == "mock":
            counts["skipped_mock"] += 1
            continue

        # platform mapping, linkage and Instagram media are checked before the
        # claim, so a rejection costs no API call
        blocker = publisher.preflight(asset)
        if blocker:
            db.mark_failed(asset["id"], blocker)
            counts["failed"] += 1
            print(f"[worker] #{asset['id']} not publishable: {blocker}")
            continue

        if not db.claim_asset(asset["id"]):
            counts["lost_race"] += 1      # another worker took it
            continue

        try:
            post_id, provider, post_url = _publish_claimed(asset)
        except Exception as e:
            db.mark_failed(asset["id"], e)
            counts["failed"] += 1
            print(f"[worker] #{asset['id']} giving up: {e}")
        except BaseException:
            # Ctrl-C mid-publish: put it back so it isn't stranded in 'posting'
            db.release_asset(asset["id"])
            raise
        else:
            db.mark_scheduled(asset["id"], post_id, provider, post_url)
            key = "updated" if asset.get("post_id") else "posted"
            counts[key] += 1
            print(f"[worker] #{asset['id']} {key} -> {provider} {post_id}")

    return counts


_bg_started = False
_bg_lock = None


def start_background(interval=None):
    """Start one daemon publisher thread for this process. Idempotent.

    Streamlit reruns the script constantly, so this is guarded and meant to be
    wrapped in st.cache_resource by the caller.
    """
    global _bg_started, _bg_lock
    import threading
    if _bg_lock is None:
        _bg_lock = threading.Lock()
    with _bg_lock:
        if _bg_started:
            return False
        _bg_started = True

    every = interval or POLL_SECONDS

    def loop():
        while True:
            try:
                counts = run_once()
                if any(v for k, v in counts.items() if k != "paused"):
                    print(f"[worker:bg] {counts}")
            except Exception as e:                  # never kill the thread
                print(f"[worker:bg] pass failed: {e}")
            time.sleep(every)

    threading.Thread(target=loop, name="ja-publisher", daemon=True).start()
    print(f"[worker:bg] auto-publish thread started, every {every}s")
    return True


def main(argv=None):
    ap = argparse.ArgumentParser(description="JA Assure posting worker")
    ap.add_argument("--once", action="store_true", help="single pass, then exit")
    args = ap.parse_args(argv)

    db.init()
    mode = publisher.active_provider()
    print(f"[worker] provider={mode} poll={POLL_SECONDS}s"
          + (" (dry-run: writes outbox.jsonl)" if mode == "dry-run"
             else " [LIVE: posts to real accounts]")
          + (" [PUBLISHING PAUSED]" if db.publishing_paused() else ""))

    if args.once:
        print(f"[worker] {run_once()}")
        return 0

    try:
        while True:
            counts = run_once()
            if any(counts.values()):
                print(f"[worker] {counts}")
            time.sleep(POLL_SECONDS)
    except KeyboardInterrupt:
        print("\n[worker] stopped")
        return 0


if __name__ == "__main__":
    sys.exit(main())
