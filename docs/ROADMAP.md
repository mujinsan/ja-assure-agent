# Roadmap

What exists today, what is not built, and what production would require.

---

## Built

Generation with brand/platform/language awareness and A/B variants; a two-layer
compliance gate; human review with heuristic tag suggestion; a lessons feedback
loop; versioned editing with a re-review rule; scheduled auto-publish through a
dry-run or Ayrshare adapter; media generation (image chain, video render) and
validated uploads; a hash-chained audit log; two independent publishing gates.

---

## Not built yet

### Lead generation agent

Take an approved post's engagement and identify prospects worth contacting.
Needs platform read APIs (Ayrshare exposes comments and analytics), a scoring
model against the brand's ICP, and a CRM destination. **The compliance gate must
apply to outbound DMs too** — a personalised message making a coverage promise
is the same regulatory problem as a public post, so route it through
`compliance.check()` rather than bypassing it because it is one-to-one.

### Competitor digest

Scheduled research runs against named competitors, diffed week over week, to
surface positioning changes and content gaps. `agents/research.py` already has
the sanitise/fence boundary this would need. The open question is storage:
digests are documents, not assets, and do not belong in the `assets` table.

### Multi-user auth and roles

The single largest gap. Today there are no users: `edited_by` and `actor` record
a constant string, so the audit log proves *what* happened, not *who* did it.
Minimum viable shape:

- Identity (OAuth against the company IdP rather than local accounts).
- Roles: `creator` (generate, edit), `reviewer` (approve, reject),
  `publisher` (arm live posting). Separating reviewer from publisher is the
  point — it makes the two gates two *people*, not two clicks.
- Real identity threaded into `apply_edit(edited_by=...)` and `db.log(actor=...)`.

Until this exists, deploy only where every user is trusted to publish.

### Real scheduling

`publish_at` exists and the worker honours it, but scheduling is
poll-and-compare. Production needs a proper scheduler: timezone-aware slots (a
Singapore clinic audience is not a Hong Kong one), per-platform cadence limits,
a calendar view, and recurring campaigns. Ayrshare's own `scheduleDate` could
carry the final hop, which would also survive the worker being down.

### Postgres

SQLite is a genuine constraint, not just an aesthetic one — the background
thread and any second worker contend on one file, which is why `db.conn()`
carries a busy timeout. The schema ports directly; `init()`'s ALTER-based
migrations should become a real migration tool (Alembic) at the same time.

---

## What production would need

Beyond the above, in rough priority order:

1. **Authentication** — nothing else matters until the app knows who is acting.
2. **Inspect Ayrshare's `blocked` field.** A post the platform refuses comes
   back with an id and an empty `postIds`, and the worker records it as
   `scheduled`. Observed in practice. An asset should only become `scheduled`
   when the platform confirms. This is the same class of bug as the original
   silent-mock-fallback: a success recorded over a real failure.
3. **Cost controls** — per-hour call ceilings and a spend alarm. Nothing
   currently caps API usage.
4. **SRI on CDN scripts** (see SECURITY.md §7).
5. **Object storage for media** — local disk does not survive a restart, and
   Ayrshare needs publicly reachable URLs.
6. **Observability** — structured logs, publish success/failure rates, model
   fallback frequency. The `[llm]` and `[worker]` prints are developer aids,
   not telemetry.
7. **A real test of the live publish path.** Every automated test stubs the
   transport; the live Ayrshare path has never been exercised end to end in CI,
   and cannot be without a sandbox account.
8. **Human-facing compliance reporting** — the audit chain is machine-verifiable
   but there is no export a compliance officer could read.
9. **Content calendar and campaign grouping** — assets are currently independent
   rows with no notion of a campaign.
10. **Localisation review** — `poor localisation` is currently suggested for
    *every* non-English asset, correct or not. A useful version would detect
    that a non-English language was requested but English copy came back.

---

## Known sharp edges to fix first

Small, well-understood, and each one already has a reproduction:

- The `blocked`-field gap above.
- `poor localisation` firing on every non-English asset.
- `wrong CTA` suggested on roughly half of all assets — either the rule is too
  aggressive or the content genuinely lacks CTAs; needs a human judgement call.
- Orphaned media files in `media/` from assets whose `image_path` was wiped by
  the (now fixed) widget-state bug. The paths survive in `asset_versions`, so a
  repair script could restore them.
- Video renders at the voiceover's length (~16s) rather than a target ~10s.
