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
    """Publish an already-claimed asset, retrying with backoff.

    Returns (post_id, provider) or raises the last error after MAX_ATTEMPTS.
    """
    last = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return publisher.publish(asset)
        except Exception as e:
            last = e
            print(f"[worker] #{asset['id']} attempt {attempt}/{MAX_ATTEMPTS} failed: {e}")
            if attempt < MAX_ATTEMPTS:
                time.sleep(2 ** (attempt - 1))   # 1s, 2s
    raise last


def run_once():
    """One pass over the approved queue. Returns a counts dict."""
    counts = {"posted": 0, "failed": 0, "skipped_mock": 0, "lost_race": 0}

    for asset in db.list_assets("approved"):
        # never publish template text, even if it somehow reached approved
        if asset.get("provider") == "mock":
            counts["skipped_mock"] += 1
            continue

        if not db.claim_asset(asset["id"]):
            counts["lost_race"] += 1      # another worker took it
            continue

        try:
            post_id, provider = _publish_claimed(asset)
        except Exception as e:
            db.mark_failed(asset["id"], e)
            counts["failed"] += 1
            print(f"[worker] #{asset['id']} giving up: {e}")
        except BaseException:
            # Ctrl-C mid-publish: put it back so it isn't stranded in 'posting'
            db.release_asset(asset["id"])
            raise
        else:
            db.mark_scheduled(asset["id"], post_id, provider)
            counts["posted"] += 1
            print(f"[worker] #{asset['id']} -> {provider} {post_id}")

    return counts


def main(argv=None):
    ap = argparse.ArgumentParser(description="JA Assure posting worker")
    ap.add_argument("--once", action="store_true", help="single pass, then exit")
    args = ap.parse_args(argv)

    db.init()
    mode = publisher.active_provider()
    print(f"[worker] provider={mode} poll={POLL_SECONDS}s"
          + (" (dry-run: writes outbox.jsonl)" if mode == "dry-run" else ""))

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
