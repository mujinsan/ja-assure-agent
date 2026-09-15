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

