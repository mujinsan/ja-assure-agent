# Code walkthrough

Every module, what it is for, its key functions, and how data moves between them.

---

## `config.py`

Static configuration, no logic. `BRANDS` (niche, voice, audience per brand),
`PLATFORMS` (style string per platform — the word and character limits are
**parsed** from these strings elsewhere so they cannot drift), `LANGUAGES`,
`MARKETS`, `FEEDBACK_TAGS`, `COMPLIANCE_RUBRIC` (the prompt for the LLM
compliance layer).

---

## `agents/llm.py` — the provider chain

Every text call in the app goes through here.

| Function | Purpose |
|---|---|
| `generate_json(prompt, system, mock)` | The only public entry point. Walks the chain and returns parsed JSON. |
| `model_chain()` | `GEMINI_MODEL` + `GEMINI_FALLBACK_MODELS`, de-duplicated. |
| `_classify(e)` | `quota` / `missing` / `transient` / `other` — decides whether to advance. |
| `_is_busy(e)` | 503-style error worth one immediate retry. |
| `_is_daily_quota(e)` | Per-day cap (dead for the session) vs per-minute (temporary). |
| `_call_gemini(model, full)` | One model, with a single 2s retry on 503. |
| `_groq(full)` | Groq's OpenAI-compatible endpoint, used after the Gemini chain. |
| `_parse(text)` | Strips code fences and extracts the JSON object. |

**Module state the UI reads:** `last_provider`, `last_model`, `last_summary`,
`last_error`, `exhausted_models`.

**Why it exists:** a hardcoded model name is a dependency with an expiry date.
`gemini-2.5-flash` and `llama-3.3-70b-versatile` were both retired during this
project, and the original silent mock fallback hid it.

---

## `agents/research.py` — untrusted input boundary

| Function | Purpose |
|---|---|
| `research(query)` | Tavily search; returns fenced text or `None`. |
| `sanitise(text)` | Drops lines matching injection patterns, strips tags, truncates. |
| `fence(text)` | Wraps in `<untrusted_web_content>` with an explicit instruction not to obey it. |

Returns `None` when there are no usable results, so callers never report
"with research context" over an empty block.

---

## `agents/content.py` — generation

| Function | Purpose |
|---|---|
| `create(brand, platform, language, topic, lessons, research)` | One LLM call producing variant A and B. |
| `lessons_block(lessons)` | Formats past human feedback as do-not-repeat guidance. |
| `_mock(...)` | The template used when no provider answers. Deliberately contains a compliance violation in variant B so the gate is visibly exercised in demos. |

---

## `agents/compliance.py` — the two-layer gate

| Function | Purpose |
|---|---|
| `HARD_RULES` | Regex + label pairs. Deterministic, always runs, never batched. |
| `hard_reasons(text)` | Labels of every rule that fired. |
| `hard_matches(text)` | `(start, end, rule)` spans, ordered and de-overlapped — display only, used for the red wavy underline. |
| `check(text)` | Single asset, both layers. Used by the re-review path. |
| `check_batch(items)` | Regex per variant, **one** LLM call for the whole run. |
| `split_reasons(text)` | Turns the stored reason string back into rule-layer and AI-layer display lines. |

Stored format: reasons joined by `"; "`, LLM-layer entries prefixed `LLM: `.
That prefix is what `split_reasons` uses to separate the layers again.

---

## `agents/media.py` — images, video, uploads

| Function | Purpose |
|---|---|
| `expand_prompt(idea, asset, video)` | Idea → full generation prompt; keeps the user's details, fills gaps, appends the safety constraints. |
| `generate_image(prompt, asset, version)` | Gemini image model → branded Pillow card. Returns `(path, provider)`. |
| `_pillow_card(asset, out, size)` | The fallback: hook, brand name, brand colour, measured text wrapping. |
| `video_script(idea, asset)` | `{voiceover, scene}` from the LLM. |
| `generate_video(idea, asset, version)` | Scene image → Pillow-burned captions → edge-tts → MoviePy 1080x1920. |
| `sniff(data)` | `(ext, kind)` from header bytes. The extension is never trusted. |
| `save_upload(data, asset_id, version)` | Validates, caps size, strips EXIF by re-encoding pixels only, saves under a generated name. |
| `size_for` / `aspect_label` | Instagram 1:1, LinkedIn 1.91:1, video 9:16. |

---

## `agents/publisher.py` — publishing adapters

| Function | Purpose |
|---|---|
| `live_armed()` | `AYRSHARE_API_KEY` **and** `db.live_posting()`. Both required. |
| `active_provider()` | `"ayrshare"` only when armed, else `"dry-run"`. |
| `preflight(asset)` | Reason this asset must not be posted, or `None`. Runs **before** the claim. |
| `publish(asset)` | `(post_id, provider, post_url)`. |
| `update(asset, post_id)` | Revises an existing post rather than creating a second. |
| `linked_platforms()` | `activeSocialAccounts` from `GET /user`. |
| `_upload_media(path)` | Two-step Ayrshare upload → public `accessUrl`. |
| `_raise_for_ayrshare(resp)` | Splits `ValidationError` (never retry) from 5xx (retry). |
| `last_outbox_entry(post_id)` | Reads back the dry-run record for the UI panel. |

`ValidationError` is the important type: it means the request itself was
rejected, so resending it cannot help.

---

## `review.py` — review-flow helpers

| Function | Purpose |
|---|---|
| `suggest_tag(asset)` | Heuristic reason tag. **No LLM call.** |
| `platform_limit(platform)` | `(limit, unit)` parsed from `config.PLATFORMS`. |
| `has_no_cta(text)` | Strips trailing hashtags; a closing question counts as a CTA. |
| `apply_edit(asset, caption, image, video, edited_by)` | The re-review rule. |
| `PRIORITY` | Tag ranking — every rule is evaluated, then ranked. |

---

## `db.py` — storage and the audit chain

| Function | Purpose |
|---|---|
| `init()` | Creates tables and **migrates in place** (adds missing columns, backfills the audit chain). |
| `insert_asset(**a)` | New asset + `created` audit row. |
| `review(id, action, content, ...)` | Approve/reject; approval stamps `publish_at` and clears `needs_rereview`. |
| `apply_version(...)` | Edit: version row + asset update + audit, in one transaction. |
| `claim_asset(id)` | `UPDATE ... WHERE status='approved'` — the conditional WHERE *is* the lock. |
| `mark_scheduled` / `mark_failed` / `release_asset` | Publish outcomes. |
| `due_approved(now)` | Approved assets whose `publish_at` has arrived. |
| `log(c, ...)` | Appends a hash-chained audit row. Must share the caller's transaction. |
| `compute_hash(...)` | SHA-256 over `prev_hash + fields`. |
| `verify_chain()` | First broken row id, or `None`. |
| `get_setting` / `set_setting` | Global switches. |

---

## `worker.py` — the posting worker

| Function | Purpose |
|---|---|
| `run_once()` | One pass over the due queue. Returns a counts dict. |
| `_publish_claimed(asset)` | Publish or update, 3 retries with backoff, never retrying a `ValidationError`. |
| `start_background(interval)` | One daemon thread per process, idempotent. |
| `main(argv)` | CLI: loop, or `--once`. |

---

## `app.py`, `theme.py`, `vanta.py` — the UI

`app.py` is the Streamlit script, re-executed top to bottom on every
interaction. Four tabs: Generate, Review, Approved queue, Learning & Audit.
`theme.py` holds the palette, the injected CSS and HTML builders (every builder
HTML-escapes its input). `vanta.py` mounts the animated background in an
iframe pinned behind the app.

---

## Tracing one asset: "Run pipeline" to published

1. **`app.py`** — you pick brand, language, platforms, topic and press *Run pipeline*.
2. **`pipeline.run()`** — loads `db.get_lessons(brand)` (past human feedback for this brand).
3. **`agents/research.py`** — if enabled, searches Tavily, sanitises and fences the text. Returns `None` if nothing usable.
4. **`agents/content.py`** — builds one prompt per platform containing brand voice, platform style, language, topic, the lessons block and any fenced research, then calls `generate_json`.
5. **`agents/llm.py`** — walks the chain. On success records `last_provider` / `last_model`; on total failure returns the mock template.
6. **`pipeline.run()`** — collects every variant across every platform into `drafts`, capturing `llm.last_provider` per platform.
7. **`agents/compliance.py`** — `check_batch()` runs the regex layer **per variant**, then one LLM rubric call for all of them. Verdicts come back keyed `"<platform>:<variant>"`.
8. **`db.insert_asset()`** — each variant is stored `pending` or `blocked`, with `provider` recording who wrote it. A blocked asset also writes a `lessons` row with actor `compliance`.
9. **Review tab** — the card shows the compliance breakdown, applied lessons, a suggested reason tag, and (for blocked assets) the offending phrases underlined. You can edit the caption, generate or upload media — each of which creates a version via `review.apply_edit()` and re-runs both layers.
10. **Approve** — `db.review(..., "approve")` sets `status='approved'`, stamps `publish_at`, clears `needs_rereview`.
11. **`worker.run_once()`** — from `worker.py` or the in-app background thread. Checks `publishing_paused`, selects `due_approved()`, skips `provider == 'mock'`, runs `preflight()`, then claims the asset atomically.
12. **`agents/publisher.py`** — dry-run appends to `outbox.jsonl`; live uploads the media and POSTs to Ayrshare.
13. **`db.mark_scheduled()`** — `status='scheduled'` with `post_id`, `post_url`, `post_provider`, plus an audit row with actor `worker`.
14. **Editing it now** returns it to `pending` with `needs_rereview`, and once re-approved the worker takes the **update** path, revising the existing post instead of creating a second one.

Every step from 8 onward writes a hash-chained audit row, so the whole path is
replayable and tamper-evident.
