# JA Assure - AI Marketing Agent (Project 1: The Brain)

Multi-agent pipeline: **Research -> Content -> Compliance gate -> Human review -> Approved queue**,
with a closed feedback loop: every rejection or edit becomes a "lesson" injected into future generations.

## Run
```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env    # add GEMINI_API_KEY (free at aistudio.google.com)
streamlit run app.py
```
No key? It runs in **mock mode** so the demo still works.

## Architecture
| File | Role |
|---|---|
| `pipeline.py` | Orchestrator |
| `agents/research.py` | Tavily search; web text sanitised + fenced as untrusted (prompt-injection defence) |
| `agents/content.py` | Brand/platform/language-aware generation, A/B variants, lessons injected as few-shot guidance |
| `agents/compliance.py` | Two layers: deterministic regex rules + LLM rubric. Either blocks |
| `db.py` | SQLite. `assets` = contract with Project 2; `lessons` = feedback memory; `audit_log` |
| `app.py` | Streamlit review dashboard + learning curve |

`assets.status`: `pending -> approved -> scheduled` (or `blocked` / `rejected`).

## Security
Secrets in env vars only. Scraped content is treated as untrusted data. Every create/approve/reject is audit-logged.
Nothing is publishable without human approval.

## Roadmap (hackathon day)
Video/Reels (script -> TTS -> MoviePy), lead-gen agent, competitor digest, Project 2 poster worker (Buffer API).

## Project 2: worker

The posting worker drains the approved queue.

```bash
python worker.py          # poll every POLL_SECONDS (default 10)
python worker.py --once   # single pass, then exit
```

It polls `assets` for `status='approved'` and claims each one with a
conditional `UPDATE ... WHERE status='approved'`, so two workers racing on the
same asset produce exactly one winner and nothing is ever posted twice. On
success the asset becomes `scheduled` with a `post_id` and `post_provider`; on
failure it retries three times with backoff, then becomes `failed` with the
reason in `post_error`. Every transition is written to the hash-chained audit
log with actor `worker`.

Providers live in `agents/publisher.py`:

- **dry-run** (default) appends each post to `outbox.jsonl` and returns a
  `dry-<uuid8>` id. No network, no keys, safe for demos.
- **ayrshare** is used only when `AYRSHARE_API_KEY` is set, and posts through
  Ayrshare's REST API.

Assets whose content came from the mock template are never published, and only
`approved` assets are ever picked up. The Approved queue tab has a
**Run worker once** button for a single pass without leaving the app.
