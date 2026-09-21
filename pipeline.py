"""Orchestrator: research -> content -> compliance -> queue (pending for human review)."""
import db
from agents import content, compliance, llm, research as research_agent

def run(brand, platforms, language, topic, use_research=False):
    lessons = db.get_lessons(brand)
    ctx = research_agent.research(f"{topic} insurance {brand} Asia") if use_research else None
    drafts = []  # (key, platform, variant, text, image_idea, provider)
    for platform in platforms:
        out = content.create(brand, platform, language, topic, lessons, ctx)
        # who answered for this platform - persisted so Review can still warn
        # about mock output on a later rerun
        provider = llm.last_provider or "mock"
        for key in ("variant_a", "variant_b"):
            v = out.get(key) or {}
            text = v.get("text", "").strip()
            if not text:
                continue
            variant = key[-1].upper()
            drafts.append((f"{platform}:{variant}", platform, variant,
                           text, v.get("image_idea", ""), provider))

    verdicts = compliance.check_batch([(d[0], d[3]) for d in drafts])

    created = []
    for key, platform, variant, text, image_idea, provider in drafts:
        ok, reasons = verdicts[key]
        aid = db.insert_asset(
            brand=brand, platform=platform, language=language, topic=topic,
            variant=variant, content=text, image_idea=image_idea,
            compliance_pass=ok, compliance_reasons="; ".join(reasons),
            status="pending" if ok else "blocked", lessons_used=len(lessons),
            provider=provider)
        if not ok:
            db.add_lesson(brand=brand, platform=platform, tag="inaccurate claim",
                          note="; ".join(reasons), bad_example=text,
                          asset_id=aid, actor="compliance")
        created.append((aid, platform, variant, ok, reasons, provider))
    return created, bool(ctx)
