# Operations

Setup, running, troubleshooting and deployment notes.

---

## Setup

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
```

Python 3.12 is what this is developed and tested against.

Add at minimum `GEMINI_API_KEY` (free from aistudio.google.com). With no key the
app runs in mock mode — everything works, but every asset is labelled MOCK and
cannot be approved or published.

`ffmpeg` is **not** a separate install: `imageio-ffmpeg` (a MoviePy dependency)
ships a binary.

---

## Environment variables

| Variable | Default | Notes |
|---|---|---|
| `GEMINI_API_KEY` | — | Absent ⇒ mock mode. Newer keys start `AQ.`, older ones `AIza`; both are valid |
| `GEMINI_MODEL` | `gemini-3.6-flash` | First model tried |
| `GEMINI_FALLBACK_MODELS` | `gemini-3.5-flash-lite,gemini-3.5-flash` | Comma-separated, tried in order |
| `GEMINI_IMAGE_MODEL` | `gemini-3.1-flash-image` | Falls back to a Pillow card |
| `GROQ_API_KEY` | — | Optional. Tried after the whole Gemini chain |
| `GROQ_MODEL` | `openai/gpt-oss-120b` | Verify against Groq's live model list |
| `TAVILY_API_KEY` | — | Optional live research |
| `AYRSHARE_API_KEY` | — | Necessary but **not sufficient** for real posting |
| `POLL_SECONDS` | `10` | Worker poll interval |
| `DB_PATH` | `ja_assure.db` | SQLite file |
| `MEDIA_DIR` | `media` | Generated and uploaded media |
| `OUTBOX_PATH` | `outbox.jsonl` | Dry-run publish log |

Never commit `.env`. It is gitignored and has never been tracked.

---

## Running

```bash
streamlit run app.py               # the dashboard
python worker.py                   # posting worker, polls forever
python worker.py --once            # one pass, then exit
python -m pytest tests -q          # the test suite (no network)
python scripts/check_gemini.py     # is the Gemini key and model chain healthy?
python scripts/check_groq.py       # is the Groq fallback healthy?
```

The Streamlit app starts its **own** background publisher thread, so you do not
need `worker.py` running to see auto-publish. Run `worker.py` separately when
you want publishing to continue with the UI closed. Both are safe together —
the atomic claim guarantees one winner per asset.

### First-run flow

1. **Generate** — pick brand, language, platforms, topic. Press *Run pipeline*.
2. **Review** — read each card, edit if needed, attach media, approve or reject.
3. **Approved queue** — watch assets move to Posted; *Run worker once* forces a pass.
4. **Learning & Audit** — rejection-rate trend, stored lessons, audit chain status.

---

## Troubleshooting

### Everything comes out as mock output

Check the header caption. `MOCK (no GEMINI_API_KEY)` means no key is loaded.
`LIVE — last call FAILED, using mock` means the chain ran out. Run
`python scripts/check_gemini.py` for the exact error, and check the terminal for
`[llm]` lines — they name the model and reason for each hop.

Remember the failure is now **visible**: assets written by mock carry
`provider='mock'`, show a "MOCK — do not approve" banner, cannot be approved,
and turn the pipeline pills amber.

### 429 RESOURCE_EXHAUSTED

A quota error. Two kinds, treated differently:

- **Per-day** (`PerDay` in the message): that model is marked dead for the
  session and skipped, shown as `exhausted:` in the header caption. It resets
  on Google's daily boundary; restarting the app clears the in-memory set but
  the quota is still spent.
- **Per-minute**: transient. The chain advances but the model is **not**
  blacklisted, so the next run tries it again.

If `limit: 0` appears, that model is not available on your tier at all — this is
the case for the Gemini **image** models on a free key, which is why the Pillow
card is what you actually get.

Mitigation: put a working model first via `GEMINI_MODEL`, add more
`GEMINI_FALLBACK_MODELS`, or set `GROQ_API_KEY`.

### 503 UNAVAILABLE / "high demand"

Transient. The model is retried once after 2s, then the chain advances. A run
can take ~30–60s when several hops are involved. If it is persistent, reorder
`GEMINI_MODEL` to a less contended model.

### "Image path" is empty after generating or uploading

This was a real bug, fixed: Streamlit's `text_input` honours its `value`
argument only on first render, so a programmatic change left a stale empty box —
and a following *Save edit* wrote that emptiness back over the media. The path
inputs are now keyed by media revision.

If you see it again, check `asset_versions` — if v1 holds a path and v2 holds
`None`, the same class of bug has returned.

### Media generated but no preview

The preview only renders when the file exists on disk. Check
`assets.image_path` / `video_path` against `MEDIA_DIR`. Paths are stored
relative, so launching the app from a different working directory breaks them.

### Dry-run vs live — how to tell

The Approved queue shows a pill: **Dry-run mode** (amber) or **Live · ayrshare**
(green), plus a red **LIVE** pill in the header when real posting is armed.
Definitively:

```bash
python -c "import db; from dotenv import load_dotenv; load_dotenv(); from agents import publisher; print('provider:', publisher.active_provider(), '| live:', db.live_posting(), '| paused:', db.publishing_paused())"
```

To force safe:

```bash
python -c "import db; db.set_live_posting(False); db.set_publishing_paused(True)"
```

**When testing, always set `AYRSHARE_API_KEY=` in the test environment.** `.env`
is loaded automatically, and an armed switch plus a key means tests post for
real. The test suite does this in `conftest.py`.

### Instagram assets fail to publish

Instagram requires media. A text-only Instagram asset is marked `failed` with
`Instagram requires an image or video` **before** any API call — generate or
upload an image, re-approve, and the worker will pick it up.

Also check the platform is genuinely linked:

```bash
curl -s -H "Authorization: Bearer $AYRSHARE_API_KEY" https://api.ayrshare.com/api/user
```

`activeSocialAccounts` lists what Ayrshare believes is linked. Note that this
can report a platform as linked while posting still fails with
`code 156: not linked` — in that case reconnect it on Ayrshare's Social Accounts
page. Ayrshare also applies a circuit breaker after repeated identical errors,
which needs a cooldown.

### A post says "scheduled" but nothing appeared

Check the Ayrshare record directly:

```bash
curl -s -H "Authorization: Bearer $AYRSHARE_API_KEY" https://api.ayrshare.com/api/post/<post_id>
```

An empty `postIds` with a populated `blocked` array means Ayrshare accepted the
request but the platform refused it. **The worker does not currently inspect
`blocked`**, so it records this as `scheduled`. See ROADMAP.

### "database is locked"

The background thread and the UI share one SQLite file. `db.conn()` sets a 10s
busy timeout, which covers normal use. Sustained locking means something is
holding a long transaction — check for a stuck worker.

### Changes to a module do not take effect

Streamlit re-executes `app.py` per rerun but **caches imported modules**. Editing
`db.py`, `theme.py`, `review.py` or anything under `agents/` needs a full server
restart, not just a rerun. Symptom: `AttributeError` for a function you can see
in the file.

---

## Deployment notes

This is a hackathon prototype. Before exposing it beyond one trusted operator:

- **Add authentication.** There is none. Anyone who reaches the port can approve
  and publish. This is the single biggest gap.
- **Move off SQLite** to Postgres. The schema is portable; the concurrency model
  is not, and the background thread plus multiple workers will contend.
- **Run the worker as a separate process** (systemd unit or container) rather
  than relying on the in-app thread, so publishing survives a UI restart.
- **Persist `media/` to object storage.** Local disk does not survive a
  container restart, and Ayrshare needs publicly reachable URLs anyway.
- **Set a cost ceiling.** Nothing currently limits API spend.
- **Pin the model names** you have verified. Model ids are retired without
  notice — `gemini-2.5-flash` and `llama-3.3-70b-versatile` both disappeared
  mid-project.
- **Back up the audit chain** somewhere append-only. Its value is evidential.
- Keep `publishing_paused` **on** in any shared environment until the team
  agrees who may publish.
