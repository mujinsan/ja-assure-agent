"""The audit log is hash-chained, so edits to history are detectable."""


def test_chain_is_intact_after_normal_activity(tmpdb, offline, make_asset):
    aid = make_asset()
    tmpdb.review(aid, "approve", "Approved copy. T&Cs apply.", None, "")
    assert tmpdb.verify_chain() is None


def test_every_entry_is_linked(tmpdb, make_asset):
    make_asset()
    make_asset()
    rows = sorted(tmpdb.audit(), key=lambda r: r["id"])
    assert rows[0]["prev_hash"] == "GENESIS"
    for prev, cur in zip(rows, rows[1:]):
        assert cur["prev_hash"] == prev["hash"]


def test_tampering_with_a_detail_is_detected(tmpdb, make_asset):
    aid = make_asset()
    tmpdb.review(aid, "reject", "Rejected copy.", "too salesy", "note")
    assert tmpdb.verify_chain() is None

    target = sorted(tmpdb.audit(), key=lambda r: r["id"])[1]
    with tmpdb.conn() as c:
        c.execute("UPDATE audit_log SET detail=? WHERE id=?",
                  ("quietly altered", target["id"]))
    assert tmpdb.verify_chain() == target["id"]


def test_deleting_an_entry_is_detected(tmpdb, make_asset):
    make_asset()
    make_asset()
    make_asset()
    rows = sorted(tmpdb.audit(), key=lambda r: r["id"])
    victim = rows[1]
    with tmpdb.conn() as c:
        c.execute("DELETE FROM audit_log WHERE id=?", (victim["id"],))
    # the row after the hole no longer chains to its predecessor
    assert tmpdb.verify_chain() == rows[2]["id"]


def test_changing_the_actor_is_detected(tmpdb, make_asset):
    make_asset()
    target = tmpdb.audit()[0]
    with tmpdb.conn() as c:
        c.execute("UPDATE audit_log SET actor='someone else' WHERE id=?", (target["id"],))
    assert tmpdb.verify_chain() == target["id"]


def test_hash_is_deterministic(tmpdb):
    a = tmpdb.compute_hash("GENESIS", "2026-01-01T00:00:00+00:00", 1, "created", "system", "pending")
    b = tmpdb.compute_hash("GENESIS", "2026-01-01T00:00:00+00:00", 1, "created", "system", "pending")
    c = tmpdb.compute_hash("GENESIS", "2026-01-01T00:00:00+00:00", 1, "created", "system", "blocked")
    assert a == b and a != c
