"""SQLite store. The `assets` table is the contract between Project 1 and Project 2."""
import hashlib, os, sqlite3
from datetime import datetime, timezone

DB_PATH = os.getenv("DB_PATH", "ja_assure.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS assets(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT, brand TEXT, platform TEXT, language TEXT, topic TEXT,
  variant TEXT, content TEXT, original_content TEXT, image_idea TEXT,
  compliance_pass INTEGER, compliance_reasons TEXT,
  status TEXT DEFAULT 'pending',          -- pending | blocked | approved | rejected | scheduled
  feedback_tag TEXT, feedback_note TEXT,
  lessons_used INTEGER DEFAULT 0,
  provider TEXT,                          -- gemini | groq | mock: who wrote this asset
  post_provider TEXT,                     -- dry-run | ayrshare: who published it
  post_error TEXT,                        -- why the last publish attempt failed
  publish_at TEXT,                        -- ISO time the worker may publish from
  post_url TEXT,                          -- live URL returned by the provider
  image_path TEXT, video_path TEXT,       -- current media, versioned below
  needs_rereview INTEGER DEFAULT 0,       -- edited after approval
  reviewed_at TEXT, post_id TEXT
);
CREATE TABLE IF NOT EXISTS lessons(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT, brand TEXT, platform TEXT, tag TEXT, note TEXT,
  bad_example TEXT, fixed_example TEXT
);
CREATE TABLE IF NOT EXISTS asset_versions(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  asset_id INTEGER, version INTEGER,
  caption TEXT, image_path TEXT, video_path TEXT,
  edited_by TEXT, ts TEXT
);
CREATE TABLE IF NOT EXISTS settings(
  key TEXT PRIMARY KEY, value TEXT
);
CREATE TABLE IF NOT EXISTS audit_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT, asset_id INTEGER, action TEXT, actor TEXT, detail TEXT,
  prev_hash TEXT, hash TEXT
);
"""

def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def conn():
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    return c

def compute_hash(prev_hash, ts, asset_id, action, actor, detail):
    aid = "" if asset_id is None else str(asset_id)
    payload = f"{prev_hash or ''}{ts or ''}{aid}{action or ''}{actor or ''}{detail or ''}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

def init():
    with conn() as c:
        c.executescript(SCHEMA)
        # CREATE TABLE IF NOT EXISTS won't add columns to a table that already
        # exists, so bring older databases forward by hand.
        have = {r[1] for r in c.execute("PRAGMA table_info(assets)")}
        if "provider" not in have:
            c.execute("ALTER TABLE assets ADD COLUMN provider TEXT")
        if "post_provider" not in have:
            c.execute("ALTER TABLE assets ADD COLUMN post_provider TEXT")
        if "post_error" not in have:
            c.execute("ALTER TABLE assets ADD COLUMN post_error TEXT")
        for col, decl in (("publish_at", "TEXT"), ("post_url", "TEXT"),
                          ("image_path", "TEXT"),
                          ("video_path", "TEXT"),
                          ("needs_rereview", "INTEGER DEFAULT 0")):
            if col not in have:
                c.execute(f"ALTER TABLE assets ADD COLUMN {col} {decl}")
        have_audit = {r[1] for r in c.execute("PRAGMA table_info(audit_log)")}
        if "prev_hash" not in have_audit:
            c.execute("ALTER TABLE audit_log ADD COLUMN prev_hash TEXT")
        if "hash" not in have_audit:
            c.execute("ALTER TABLE audit_log ADD COLUMN hash TEXT")

        rows = c.execute(
            "SELECT id, ts, asset_id, action, actor, detail, prev_hash, hash "
            "FROM audit_log ORDER BY id ASC"
        ).fetchall()
        if rows and any(r["hash"] is None for r in rows):
            last_hash = "GENESIS"
            for r in rows:
                if r["hash"] is None:
                    prev = r["prev_hash"] or last_hash
                    h = compute_hash(prev, r["ts"], r["asset_id"], r["action"], r["actor"], r["detail"])
                    c.execute("UPDATE audit_log SET prev_hash=?, hash=? WHERE id=?", (prev, h, r["id"]))
                    last_hash = h
                else:
                    last_hash = r["hash"]

def log(c, asset_id, action, actor, detail=""):
    t = now()
    last = c.execute("SELECT hash FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
    prev_hash = last["hash"] if (last and last["hash"]) else "GENESIS"
    h = compute_hash(prev_hash, t, asset_id, action, actor, detail)
    c.execute("INSERT INTO audit_log(ts,asset_id,action,actor,detail,prev_hash,hash) VALUES(?,?,?,?,?,?,?)",
              (t, asset_id, action, actor, detail, prev_hash, h))

def insert_asset(**a):
    with conn() as c:
        cur = c.execute(
            """INSERT INTO assets(created_at,brand,platform,language,topic,variant,content,
               original_content,image_idea,compliance_pass,compliance_reasons,status,
               lessons_used,provider)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (now(), a["brand"], a["platform"], a["language"], a["topic"], a["variant"],
             a["content"], a["content"], a.get("image_idea", ""), int(a["compliance_pass"]),
             a["compliance_reasons"], a["status"], a.get("lessons_used", 0),
             a.get("provider")))
        log(c, cur.lastrowid, "created", "system", a["status"])
        return cur.lastrowid

def list_assets(status=None):
    with conn() as c:
        if status:
            return [dict(r) for r in c.execute(
                "SELECT * FROM assets WHERE status=? ORDER BY id DESC", (status,))]
        return [dict(r) for r in c.execute("SELECT * FROM assets ORDER BY id DESC")]

def review(asset_id, action, content, tag=None, note="", actor="reviewer",
           publish_at=None):
    """action: approve | reject. Edits and rejections become lessons.

    Approving stamps publish_at (default now) so the worker can pick the asset
    up, and clears the needs_rereview flag: a human has just looked at it.
    """
    with conn() as c:
        row = dict(c.execute("SELECT * FROM assets WHERE id=?", (asset_id,)).fetchone())
        edited = content.strip() != row["content"].strip()
        status = "approved" if action == "approve" else "rejected"
        c.execute("""UPDATE assets SET status=?, content=?, feedback_tag=?, feedback_note=?,
                     reviewed_at=? WHERE id=?""",
                  (status, content, tag, note, now(), asset_id))
        if action == "approve":
            c.execute("UPDATE assets SET publish_at=?, needs_rereview=0 WHERE id=?",
                      (publish_at or now(), asset_id))
        log(c, asset_id, status + (" (edited)" if edited else ""), actor, tag or "")
        if action == "reject" or edited:
            c.execute("""INSERT INTO lessons(created_at,brand,platform,tag,note,bad_example,fixed_example)
                         VALUES(?,?,?,?,?,?,?)""",
                      (now(), row["brand"], row["platform"], tag or "edited", note,
                       row["original_content"], content if edited else None))

def add_lesson(brand, platform, tag, note="", bad_example=None, fixed_example=None,
               asset_id=None, actor="system"):
    """Store a lesson outside the human-review path (e.g. a compliance block)."""
    with conn() as c:
        c.execute("""INSERT INTO lessons(created_at,brand,platform,tag,note,bad_example,fixed_example)
                     VALUES(?,?,?,?,?,?,?)""",
                  (now(), brand, platform, tag, note, bad_example, fixed_example))
        if asset_id is not None:
            log(c, asset_id, "lesson stored", actor, tag)

def get_lessons(brand, limit=6):
    with conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM lessons WHERE brand=? ORDER BY id DESC LIMIT ?", (brand, limit))]

def all_lessons():
    with conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM lessons ORDER BY id DESC")]

def audit():
    with conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT 100")]

def verify_chain():
    """Recomputes the chain and returns the first broken entry id or None."""
    with conn() as c:
        rows = c.execute(
            "SELECT id, ts, asset_id, action, actor, detail, prev_hash, hash "
            "FROM audit_log ORDER BY id ASC"
        ).fetchall()
        expected_prev = "GENESIS"
        for r in rows:
            if r["prev_hash"] != expected_prev:
                return r["id"]
            expected_hash = compute_hash(
                expected_prev, r["ts"], r["asset_id"], r["action"], r["actor"], r["detail"]
            )
            if r["hash"] != expected_hash:
                return r["id"]
            expected_prev = r["hash"]
        return None


# --- Project 2 worker helpers ------------------------------------------------

def claim_asset(asset_id, actor="worker"):
    """Move approved -> posting, but only if still approved.

    The WHERE clause is the lock: SQLite applies the UPDATE atomically, so two
    workers racing on the same asset produce exactly one rowcount of 1.
    Returns True if this caller won the claim.
    """
    with conn() as c:
        cur = c.execute(
            "UPDATE assets SET status='posting' WHERE id=? AND status='approved'",
            (asset_id,))
        if cur.rowcount == 1:
            log(c, asset_id, "claimed", actor, "approved -> posting")
            return True
        return False


def mark_scheduled(asset_id, post_id, post_provider, post_url=None, actor="worker"):
    with conn() as c:
        c.execute("""UPDATE assets SET status='scheduled', post_id=?, post_provider=?,
                     post_url=?, post_error=NULL WHERE id=?""",
                  (post_id, post_provider, post_url, asset_id))
        log(c, asset_id, "posted", actor,
            f"{post_provider} {post_id}" + (f" {post_url}" if post_url else ""))


def mark_failed(asset_id, reason, actor="worker"):
    with conn() as c:
        c.execute("UPDATE assets SET status='failed', post_error=? WHERE id=?",
                  (str(reason)[:500], asset_id))
        log(c, asset_id, "post failed", actor, str(reason)[:200])


def release_asset(asset_id, actor="worker"):
    """Hand a claimed asset back to the queue (used on interrupt)."""
    with conn() as c:
        cur = c.execute(
            "UPDATE assets SET status='approved' WHERE id=? AND status='posting'",
            (asset_id,))
        if cur.rowcount == 1:
            log(c, asset_id, "released", actor, "posting -> approved")


# --- global settings ---------------------------------------------------------

def get_setting(key, default=None):
    with conn() as c:
        r = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return r["value"] if r else default


def set_setting(key, value, actor="human"):
    with conn() as c:
        c.execute("INSERT INTO settings(key,value) VALUES(?,?) "
                  "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                  (key, str(value)))
        log(c, None, f"setting {key}", actor, str(value))


def publishing_paused():
    return get_setting("publishing_paused", "0") == "1"


def set_publishing_paused(paused, actor="human"):
    set_setting("publishing_paused", "1" if paused else "0", actor)


# --- scheduling --------------------------------------------------------------

def set_publish_at(asset_id, when_iso, actor="human"):
    with conn() as c:
        c.execute("UPDATE assets SET publish_at=? WHERE id=?", (when_iso, asset_id))
        log(c, asset_id, "scheduled for", actor, when_iso or "now")


def due_approved(now_iso=None):
    """Approved assets whose publish_at has arrived (or was never set)."""
    now_iso = now_iso or now()
    with conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM assets WHERE status='approved' "
            "AND (publish_at IS NULL OR publish_at <= ?) ORDER BY id ASC", (now_iso,))]


# --- versioned editing -------------------------------------------------------

def add_version(asset_id, caption, image_path=None, video_path=None,
                edited_by="human", c=None):
    """Append a version row. Pass an open connection to join a transaction."""
    def _do(cx):
        r = cx.execute("SELECT MAX(version) v FROM asset_versions WHERE asset_id=?",
                       (asset_id,)).fetchone()
        nxt = (r["v"] or 0) + 1
        cx.execute("""INSERT INTO asset_versions(asset_id,version,caption,image_path,
                      video_path,edited_by,ts) VALUES(?,?,?,?,?,?,?)""",
                   (asset_id, nxt, caption, image_path, video_path, edited_by, now()))
        return nxt
    if c is not None:
        return _do(c)
    with conn() as cx:
        return _do(cx)


def list_versions(asset_id):
    with conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT * FROM asset_versions WHERE asset_id=? ORDER BY version DESC",
            (asset_id,))]


def apply_version(asset_id, caption, image_path, video_path, new_status,
                  compliance_pass, compliance_reasons, needs_rereview,
                  edited_by="human"):
    """Write an edit: new version row, updated asset, audit entry - one transaction."""
    with conn() as c:
        version = add_version(asset_id, caption, image_path, video_path, edited_by, c=c)
        c.execute("""UPDATE assets SET content=?, image_path=?, video_path=?,
                     status=?, compliance_pass=?, compliance_reasons=?,
                     needs_rereview=? WHERE id=?""",
                  (caption, image_path, video_path, new_status,
                   int(compliance_pass), compliance_reasons,
                   1 if needs_rereview else 0, asset_id))
        log(c, asset_id, f"edited v{version}", edited_by,
            f"status -> {new_status}" + (" (needs re-review)" if needs_rereview else ""))
        return version


def live_posting():
    """Human-armed switch for real publishing. Off unless explicitly enabled."""
    return get_setting("live_posting", "0") == "1"


def set_live_posting(on, actor="human"):
    set_setting("live_posting", "1" if on else "0", actor)
