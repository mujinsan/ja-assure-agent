"""Editing an asset a human already signed off must send it back to review."""
import review


def test_edit_after_approval_returns_to_pending(tmpdb, offline, make_asset, get_asset):
    aid = make_asset(status="approved")
    ver, status, reasons, needs = review.apply_edit(
        get_asset(aid), "Revised copy. T&Cs apply. Talk to us.")
    assert ver == 1
    assert status == "pending"
    assert needs is True
    assert get_asset(aid)["needs_rereview"] == 1


def test_edit_failing_compliance_is_blocked(tmpdb, offline, make_asset, get_asset):
    aid = make_asset(status="approved")
    _ver, status, reasons, _needs = review.apply_edit(
        get_asset(aid), "Guaranteed payout, 100% covered!")
    assert status == "blocked"
    assert "Guarantees an outcome" in reasons


def test_editing_a_pending_asset_does_not_flag_rereview(tmpdb, offline, make_asset, get_asset):
    aid = make_asset(status="pending")
    _ver, status, _reasons, needs = review.apply_edit(
        get_asset(aid), "Still pending. T&Cs apply. Talk to us.")
    assert needs is False
    assert status == "pending"


def test_published_asset_edit_also_returns_to_pending(tmpdb, offline, make_asset, get_asset):
    aid = make_asset(status="scheduled")
    _ver, status, _reasons, needs = review.apply_edit(
        get_asset(aid), "Revised after publishing. T&Cs apply. Talk to us.")
    assert (status, needs) == ("pending", True)


def test_approval_clears_the_rereview_flag(tmpdb, offline, make_asset, get_asset):
    aid = make_asset(status="approved")
    review.apply_edit(get_asset(aid), "Revised copy. T&Cs apply. Talk to us.")
    assert get_asset(aid)["needs_rereview"] == 1
    tmpdb.review(aid, "approve", get_asset(aid)["content"], None, "")
    row = get_asset(aid)
    assert row["needs_rereview"] == 0
    assert row["status"] == "approved"
    assert row["publish_at"], "approval must stamp publish_at"


def test_every_edit_creates_a_version_and_media_is_recorded(tmpdb, offline, make_asset, get_asset):
    aid = make_asset(status="approved")
    review.apply_edit(get_asset(aid), "One. T&Cs apply. Talk to us.", "media/a.png")
    review.apply_edit(get_asset(aid), "Two. T&Cs apply. Talk to us.", "media/b.png")
    versions = tmpdb.list_versions(aid)
    assert [v["version"] for v in versions] == [2, 1]
    assert versions[0]["image_path"] == "media/b.png"
    assert get_asset(aid)["image_path"] == "media/b.png"


def test_edit_is_audited(tmpdb, offline, make_asset, get_asset):
    aid = make_asset(status="approved")
    review.apply_edit(get_asset(aid), "Edited. T&Cs apply. Talk to us.")
    actions = [r["action"] for r in tmpdb.audit() if r["asset_id"] == aid]
    assert any(a.startswith("edited v") for a in actions)
