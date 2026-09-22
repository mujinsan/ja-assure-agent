# JA Assure — AI Marketing Agent

Multi-agent pipeline: **Research → Content → Compliance gate → Human review → Approved queue → Posting worker**,
with a closed feedback loop — every rejection or edit becomes a "lesson" injected into future generations.

Nothing reaches a social account without a human approving it, and nothing reaches a
*real* account without a human also arming a separate live switch.

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # add GEMINI_API_KEY (free at aistudio.google.com)
streamlit run app.py
```

With no `GEMINI_API_KEY` the app runs in **mock mode** so the demo still works. Mock
assets are visibly labelled and cannot be approved or published.

```bash
python worker.py            # posting worker, polls every POLL_SECONDS
python worker.py --once     # one pass, then exit
python scripts/check_gemini.py   # verify the Gemini key and model chain
python scripts/check_groq.py     # verify the Groq fallback
```

The app also starts one in-process publisher thread (`worker.start_background()`
wrapped in `st.cache_resource`), so you do not need `worker.py` running to see
auto-publish work.

## Environment

| Variable | Default | Purpose |
|---|---|---|
| `GEMINI_API_KEY` | — | Primary text model. Absent ⇒ mock mode |
| `GEMINI_MODEL` | `gemini-3.6-flash` | First model in the chain |
| `GEMINI_FALLBACK_MODELS` | `gemini-3.5-flash-lite,gemini-3.5-flash` | Tried in order, comma-separated |
| `GEMINI_IMAGE_MODEL` | `gemini-3.1-flash-image` | Image generation; falls back to a Pillow card |
| `GROQ_API_KEY` | — | Last-resort text provider after the Gemini chain |
| `GROQ_MODEL` | `openai/gpt-oss-120b` | Groq model id |
| `TAVILY_API_KEY` | — | Optional live research |
| `AYRSHARE_API_KEY` | — | Real posting. **Not sufficient on its own** — see below |
| `POLL_SECONDS` | `10` | Worker poll interval |
| `DB_PATH` | `ja_assure.db` | SQLite file |
| `MEDIA_DIR` | `media` | Generated and uploaded media |
| `OUTBOX_PATH` | `outbox.jsonl` | Dry-run publish log |

`.env`, `*.db`, `outbox.jsonl` and `media/` are gitignored. Secrets live in env vars
only and are never printed — keys travel in an `Authorization` header and nothing logs them.

## Architecture

| File | Role |
|---|---|
| `pipeline.py` | Orchestrator: research → content → batched compliance → queue |
| `agents/llm.py` | Provider chain with retries, quota tracking and mock fallback |
| `agents/research.py` | Tavily search; web text sanitised + fenced as untrusted (prompt-injection defence) |
| `agents/content.py` | Brand/platform/language-aware generation, A/B variants, lessons as guidance |
| `agents/compliance.py` | Two layers: deterministic regex rules + LLM rubric. Either blocks |
| `agents/media.py` | Prompt expansion, image chain, video render, upload validation |
| `agents/publisher.py` | Publishing adapters: dry-run and Ayrshare |
| `worker.py` | Project 2 posting worker: claim, publish, retry, record |
| `review.py` | Heuristic reason-tag suggestion + the edit/re-review rule |
| `db.py` | SQLite: `assets`, `asset_versions`, `lessons`, `settings`, hash-chained `audit_log` |
| `app.py` | Streamlit dashboard: Generate / Review / Approved queue / Learning & Audit |
| `theme.py`, `vanta.py` | Dark theme, HTML builders, animated background |

## The model chain

Every text call walks `GEMINI_MODEL` → each `GEMINI_FALLBACK_MODELS` entry → Groq → mock.

- **Quota, model-not-found and transient errors** (502/503/504, timeouts, connection
  drops) advance the chain. A 503 first gets one retry on the same model after 2s.
- **Anything else** goes straight to mock, so a real bug stays visible instead of
  being retried into silence.
- A **daily** quota cap or a retired model marks that model dead for the session
  (`llm.exhausted_models`) and it is skipped. A per-minute 429 does not — it is
  temporary.
- `llm.last_provider`, `last_model` and `last_summary` drive the header caption, and
  the provider that produced each asset is persisted in `assets.provider`.

This exists because a hardcoded model name is a dependency with an expiry date:
`gemini-2.5-flash` and `llama-3.3-70b-versatile` were both retired mid-project.

## Data model

`assets.status`: `pending → approved → posting → scheduled`, or `blocked` / `rejected` / `failed`.

- `provider` — who *wrote* the copy (`gemini` / `groq` / `mock`)
- `post_provider` — who *published* it (`dry-run` / `ayrshare`). Deliberately separate.
- `publish_at` — stamped on approval; the worker only picks up assets whose time has come
- `post_id`, `post_url`, `post_error` — publish result
- `image_path`, `video_path` — current media; every change is versioned
- `needs_rereview` — edited after a human approved it

`asset_versions` records every caption/media edit (`asset_id`, `version`, `caption`,
`image_path`, `video_path`, `edited_by`, `ts`).

`audit_log` is **hash-chained**: each row stores `prev_hash` and a SHA-256 `hash` over
its own fields, rooted at `GENESIS`. `db.verify_chain()` returns the first broken row id
or `None`. The Learning & Audit tab shows this as a verification pill.

Schema changes migrate in place — `init()` adds missing columns and backfills the audit
chain, so an existing database upgrades without losing rows.

## Review and re-review

Editing the caption or media of an asset that is `approved`, `posting`, `scheduled` or
`failed` re-runs **both** compliance layers and sends it back to `pending` (or `blocked`),
raising `needs_rereview`. The earlier sign-off was for different content, so it must be
approved again before it can publish. Approving clears the flag.

Reason tags are suggested by `review.suggest_tag()` using heuristics only — no LLM call.
Every rule is evaluated and the winner is chosen by priority
(`inaccurate claim > too salesy > too long > wrong CTA > poor localisation > off-brand tone`),
or `None`, which leaves the dropdown genuinely empty rather than defaulting to the first tag.

## Media

`agents/media.py`:

- **Prompt expansion** turns a rough or detailed idea into a full generation prompt,
  keeping everything the user specified and filling only the gaps from brand
  voice/niche/audience, the platform aspect ratio (Instagram 1:1, LinkedIn 1.91:1,
  video 9:16) and the caption. Four safety constraints are always appended: no logos or
  brand marks, no readable text or numbers, no identifiable real people, nothing implying
  guaranteed outcomes.
- **Image chain**: `GEMINI_IMAGE_MODEL` → a branded Pillow card in the platform's ratio
  showing the caption's hook and the brand colour. The provider used is shown on the card.
- **Video**: LLM voiceover + scene → scene image through the same chain → captions burned
  on with Pillow → edge-tts voiceover → MoviePy 1080×1920 MP4. Failures surface as
  "Video unavailable" rather than breaking the page.
- **Uploads** are validated from the **header bytes**, not the extension (png/jpg/webp/mp4),
  capped at 5 MB for images and 25 MB for video, re-encoded pixel-only so EXIF cannot
  survive, and saved under a generated filename — never the user's.

New, regenerated and uploaded media all create a version and follow the re-review rule.

## Publishing safety model

Two independent gates, both defaulting to safe:

1. **`publishing_paused`** (`settings` table) — a global kill switch. When on, nothing
   publishes, live or dry-run. Overrides everything.
2. **`live_posting`** (`settings` table, default **OFF**) — real posting requires *both*
   this switch and `AYRSHARE_API_KEY`. Arming it needs a confirmation step in the UI and
   shows a red **LIVE** pill in the header.

With the key present but the switch off, the publisher is `dry-run` and makes **zero**
API calls. This matters: an earlier build treated the key alone as consent, which meant
adding a key to `.env` silently turned every publish into a real post.

Independent of those: only `approved`, non-`mock` assets are ever published.

### Worker behaviour

Assets are claimed with a conditional `UPDATE ... WHERE status='approved'`. The WHERE
clause *is* the lock, so N workers racing one asset produce exactly one winner and
nothing is posted twice.

`publisher.preflight()` runs **before** the claim and rejects an unmapped or unlinked
platform, or Instagram without media, so a rejection costs no API call.

On failure: `ValidationError` (Ayrshare rejected the request) is **never retried** —
resending the same body cannot help. 5xx and network errors retry three times with
backoff, then the asset becomes `failed` with the reason in `post_error`.

An asset that already carries a `post_id` takes the **update** path, so a post-publish
edit revises the existing post rather than creating a second one.

### Ayrshare specifics

Base `https://api.ayrshare.com/api`, key in `Authorization: Bearer`.

- `GET /user` → `activeSocialAccounts`, used to check the platform is actually linked
- Media upload is two-step per their docs: `GET /media/uploadUrl?fileName=&contentType=`
  returns `{uploadUrl, accessUrl}`, then `PUT` the bytes to `uploadUrl`; `accessUrl` goes
  into `mediaUrls` (with `isVideo` for video)
- `POST /post` with `{post, platforms:[...], mediaUrls:[...]}`; success returns
  `{id, postIds:[{id, postUrl, status}]}`, errors return `{status:"error", code, message}`
- Platform names map `instagram`/`linkedin`, and our `X` → `twitter`

**dry-run** (the default) appends a JSON record to `outbox.jsonl` — `event` is `post` or
`update`, carrying the `post_id` and any media paths — and returns a `dry-<uuid8>` id.
No network, no keys, safe for demos.

## Known limitations

- **Gemini image generation is unavailable on a free-tier key.** The API returns 429 with
  `limit: 0` for the image models, which is a tier restriction, not transient. The Pillow
  card is what you actually get until billing is enabled.
- **The live Ayrshare path is only stub-tested.** Every automated test uses a stubbed
  transport. Its first real exercise will be a real post.
- **Ayrshare cannot reach local `media/` files.** Generated media is uploaded via their
  media endpoint; a path that is neither uploadable nor an https URL is skipped with a warning.
- **Instagram requires media.** A text-only Instagram asset is marked `failed` with
  "Instagram requires an image or video" rather than being attempted.
- **`st.sidebar` does not mount** in Streamlit 1.63 here (reproducible in a minimal app with
  no custom CSS), so the background and replay controls sit in a right-aligned row instead.

## Developer gotchas

- **Editing anything outside `app.py` needs a server restart.** Streamlit re-executes
  `app.py` on every rerun but keeps imported modules cached, so a change to `db.py`,
  `theme.py` or `agents/*` will not take effect on a rerun and can throw confusing
  `AttributeError`s against the stale module.
- **Widget state beats `value=`.** `st.text_input(..., key=k)` honours its `value`
  argument only on first render. When code changes the underlying row, re-key the widget
  (the media path inputs are keyed by version) — writing `st.session_state[k]` after the
  widget is instantiated raises `StreamlitWidgetAlreadyInstantiatedError`.
- **`db.conn()` sets a 10s busy timeout** because the background publisher thread and
  Streamlit reruns touch the same SQLite file concurrently.
- **Test with publishing forced off.** Set `AYRSHARE_API_KEY=` in the test environment;
  `.env` is loaded automatically and an armed switch plus a key means tests post for real.

## Security

Secrets in env vars only, never printed or committed. Scraped web content is sanitised and
fenced as untrusted data before it reaches a model. Uploads are type-checked from their
header bytes and stripped of metadata. Model output is HTML-escaped before rendering, since
it lands in `unsafe_allow_html` markup. Every create, approve, reject, edit and publish is
written to a hash-chained audit log, with the actor recorded (`system`, `reviewer`,
`compliance`, `worker`, `human`).
