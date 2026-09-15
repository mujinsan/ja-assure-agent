"""Orchestrator: research -> content -> compliance -> queue (pending for human review)."""
import db
from agents import content, compliance, research as research_agent

def run(brand, platforms, language, topic, use_research=False):
    lessons = db.get_lessons(brand)
    ctx = research_agent.research(f"{topic} insurance {brand} Asia") if use_research else None
    drafts = []  # (key, platform, variant, text, image_idea)
    for platform in platforms:
        out = content.create(brand, platform, language, topic, lessons, ctx)
        for key in ("variant_a", "variant_b"):
            v = out.get(key) or {}
            text = v.get("text", "").strip()
            if not text:
                continue
            variant = key[-1].upper()
            drafts.append((f"{platform}:{variant}", platform, variant,
                           text, v.get("image_idea", "")))

    verdicts = compliance.check_batch([(k, t) for k, _, _, t, _ in drafts])

    created = []
    for key, platform, variant, text, image_idea in drafts:
        ok, reasons = verdicts[key]
        aid = db.insert_asset(
            brand=brand, platform=platform, language=language, topic=topic,
            variant=variant, content=text, image_idea=image_idea,
            compliance_pass=ok, compliance_reasons="; ".join(reasons),
            status="pending" if ok else "blocked", lessons_used=len(lessons))
        if not ok:
            db.add_lesson(brand=brand, platform=platform, tag="inaccurate claim",
                          note="; ".join(reasons), bad_example=text,
                          asset_id=aid, actor="compliance")
        created.append((aid, platform, variant, ok, reasons))
    return created, bool(ctx)
