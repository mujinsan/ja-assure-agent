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
  reviewed_at TEXT, post_id TEXT
);
CREATE TABLE IF NOT EXISTS lessons(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  created_at TEXT, brand TEXT, platform TEXT, tag TEXT, note TEXT,
  bad_example TEXT, fixed_example TEXT
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
    c = sqlite3.connect(DB_PATH)
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

def review(asset_id, action, content, tag=None, note="", actor="reviewer"):
    """action: approve | reject. Edits and rejections become lessons."""
    with conn() as c:
        row = dict(c.execute("SELECT * FROM assets WHERE id=?", (asset_id,)).fetchone())
        edited = content.strip() != row["content"].strip()
        status = "approved" if action == "approve" else "rejected"
        c.execute("""UPDATE assets SET status=?, content=?, feedback_tag=?, feedback_note=?,
                     reviewed_at=? WHERE id=?""",
                  (status, content, tag, note, now(), asset_id))
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
