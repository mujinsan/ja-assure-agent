"""Publishing gates: only approved, non-mock, due assets, and never when paused."""
import worker
from agents import publisher


def approve(tmpdb, aid, get_asset):
    tmpdb.review(aid, "approve", get_asset(aid)["content"], None, "")


def test_dry_run_is_the_default_provider(tmpdb):
    assert publisher.active_provider() == "dry-run"
    assert publisher.live_armed() is False


def test_approved_asset_publishes_dry_run(tmpdb, offline, make_asset, get_asset):
    aid = make_asset()
    approve(tmpdb, aid, get_asset)
    counts = worker.run_once()
    assert counts["posted"] == 1
    row = get_asset(aid)
    assert row["status"] == "scheduled"
    assert row["post_id"].startswith("dry-")
    assert row["post_provider"] == "dry-run"


def test_mock_assets_are_never_published(tmpdb, offline, make_asset, get_asset):
    aid = make_asset(provider="mock")
    approve(tmpdb, aid, get_asset)
    counts = worker.run_once()
    assert counts["skipped_mock"] == 1
    assert get_asset(aid)["status"] == "approved"


def test_pending_and_blocked_are_untouched(tmpdb, offline, make_asset, get_asset):
    pending = make_asset(status="pending")
    blocked = make_asset(status="blocked")
    worker.run_once()
    assert get_asset(pending)["status"] == "pending"
    assert get_asset(blocked)["status"] == "blocked"


def test_future_publish_at_is_not_due(tmpdb, offline, make_asset, get_asset):
    aid = make_asset()
    tmpdb.review(aid, "approve", get_asset(aid)["content"], None, "",
                 publish_at="2099-01-01T00:00:00+00:00")
    assert [a["id"] for a in tmpdb.due_approved()] == []
    worker.run_once()
    assert get_asset(aid)["status"] == "approved"


def test_pause_overrides_everything(tmpdb, offline, make_asset, get_asset):
    aid = make_asset()
    approve(tmpdb, aid, get_asset)
    tmpdb.set_publishing_paused(True)
    counts = worker.run_once()
    assert counts["paused"] == 1 and counts["posted"] == 0
    assert get_asset(aid)["status"] == "approved"


def test_claim_is_atomic(tmpdb, offline, make_asset, get_asset):
    """The conditional UPDATE is the lock: only one caller may win."""
    aid = make_asset()
    approve(tmpdb, aid, get_asset)
    assert tmpdb.claim_asset(aid) is True
    assert tmpdb.claim_asset(aid) is False      # already 'posting'
