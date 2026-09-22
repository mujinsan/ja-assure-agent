# Architecture

## End-to-end flow

```mermaid
flowchart TD
    UI["Streamlit UI<br/>app.py"] -->|Run pipeline| P["pipeline.run()"]

    P --> R{"Use live research?"}
    R -->|yes| RA["agents/research.py<br/>Tavily search"]
    RA --> SAN["sanitise() + fence()<br/>untrusted web content"]
    R -->|no| C
    SAN --> C["agents/content.py<br/>brand + platform + language<br/>A/B variants"]

    L[("lessons<br/>past human feedback")] -.->|injected as guidance| C
    C --> LLM["agents/llm.py<br/>GEMINI_MODEL then fallbacks then Groq then mock"]
    LLM --> C

    C --> CB["agents/compliance.py<br/>check_batch(): ONE call per run"]
    CB --> RULES["Layer 1: HARD_RULES regex<br/>per variant"]
    CB --> RUBRIC["Layer 2: LLM rubric<br/>batched"]
    RULES --> V{"Either layer blocks?"}
    RUBRIC --> V

    V -->|yes| B["status = blocked"]
    V -->|no| PEND["status = pending"]
    B -->|lesson recorded| L

    PEND --> REV["Review tab<br/>human reads, edits, tags"]
    B --> REV

    REV -->|reject or edit| L
    REV -->|edit caption or media| RE["review.apply_edit()<br/>new version, re-run BOTH layers"]
    RE -->|was signed off| PEND
    REV -->|approve| APP["status = approved<br/>publish_at stamped"]

    APP --> W["worker.run_once()"]
    W --> G1{"publishing_paused?"}
    G1 -->|yes| STOP["nothing publishes"]
    G1 -->|no| G2{"publish_at due<br/>and provider not mock?"}
    G2 -->|no| STOP
    G2 -->|yes| PF["publisher.preflight()<br/>platform linked? Instagram media?"]
    PF -->|blocked| F["status = failed<br/>reason in post_error"]
    PF -->|ok| CLAIM["claim_asset()<br/>UPDATE WHERE status='approved'"]
    CLAIM --> PUB{"live_posting AND key?"}
    PUB -->|no| DRY["dry-run<br/>append to outbox.jsonl"]
    PUB -->|yes| AYR["Ayrshare REST<br/>upload media then POST /post"]
    DRY --> SCHED["status = scheduled<br/>post_id, post_url, post_provider"]
    AYR --> SCHED
    AYR -->|ValidationError| F

    SCHED --> AUD[("audit_log<br/>hash-chained")]
    B --> AUD
    APP --> AUD
    F --> AUD
```

The dotted line is the feedback loop: every rejection, edit or compliance block
becomes a row in `lessons`, which `agents/content.py` injects into the next
generation for that brand.

## Database

```mermaid
erDiagram
    ASSETS ||--o{ ASSET_VERSIONS : "has versions"
    ASSETS ||--o{ AUDIT_LOG : "is audited by"
    LESSONS }o--|| ASSETS : "derived from reviews of"

    ASSETS {
        int id PK
        text created_at
        text brand
        text platform
        text language
        text topic
        text variant
        text content "current caption"
        text original_content "as generated"
        text image_idea
        int compliance_pass
        text compliance_reasons "both layers, LLM prefixed"
        text status "pending blocked approved posting scheduled rejected failed"
        text feedback_tag
        text feedback_note
        int lessons_used
        text provider "gemini groq mock - who WROTE it"
        text post_provider "dry-run ayrshare - who PUBLISHED it"
        text post_error
        text publish_at "worker may publish from"
        text post_url
        text image_path
        text video_path
        int needs_rereview
        text reviewed_at
        text post_id
    }

    ASSET_VERSIONS {
        int id PK
        int asset_id FK
        int version
        text caption
        text image_path
        text video_path
        text edited_by
        text ts
    }

    LESSONS {
        int id PK
        text created_at
        text brand
        text platform
        text tag
        text note
        text bad_example
        text fixed_example
    }

    AUDIT_LOG {
        int id PK
        text ts
        int asset_id FK
        text action
        text actor "system reviewer compliance worker human"
        text detail
        text prev_hash "chain link"
        text hash "sha256 of this row"
    }

    SETTINGS {
        text key PK "publishing_paused or live_posting"
        text value
    }
```

`SETTINGS` has no foreign keys — it holds the two global publishing switches so
every session and every worker process reads the same state.

## Status lifecycle

```mermaid
stateDiagram-v2
    [*] --> pending: generated, both layers passed
    [*] --> blocked: a compliance layer blocked it
    pending --> approved: human approves
    pending --> rejected: human rejects
    blocked --> pending: edited and now passes
    approved --> posting: worker claims it
    posting --> scheduled: published
    posting --> failed: publish rejected
    failed --> approved: re-approved after a fix
    scheduled --> pending: edited after publishing
    approved --> pending: edited after approval
```

An edit to anything a human already signed off (`approved`, `posting`,
`scheduled`, `failed`) returns it to `pending` and raises `needs_rereview`.

## Two independent publishing gates

Both default to the safe position and are stored in `settings`, not in memory,
so a second worker process or a second browser session cannot disagree:

| Gate | Default | Effect |
|---|---|---|
| `publishing_paused` | off | When on, **nothing** publishes — dry-run included |
| `live_posting` | **off** | Real posting needs this **and** `AYRSHARE_API_KEY` |

With a key present but `live_posting` off, the publisher is `dry-run` and makes
zero API calls.
