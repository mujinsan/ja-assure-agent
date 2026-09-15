"""Content agent: brand + platform + language aware, fed with past lessons."""
from config import BRANDS, PLATFORMS
from agents.llm import generate_json

def lessons_block(lessons):
    if not lessons:
        return ""
    out = ["LESSONS FROM PAST HUMAN REVIEWS - do NOT repeat these mistakes:"]
    for l in lessons:
        out.append(f"- [{l['tag']}] {l['note'] or ''}".rstrip())
        if l.get("bad_example"):
            out.append(f"  Rejected/edited: {l['bad_example'][:200]}")
        if l.get("fixed_example"):
            out.append(f"  Human's fixed version: {l['fixed_example'][:200]}")
    return "\n".join(out)

def _mock(brand, platform, language, topic, lessons):
    learned = any(l["tag"] in ("inaccurate claim", "too salesy") for l in lessons)
    risky = "" if learned else " Guaranteed payout, 100% covered - the best cover in Asia!"
    b = BRANDS[brand]
    base = f"[{language}] {brand} | {topic}: Protecting {b['audience']} with {b['niche']}."
    return {
        "variant_a": {"text": base + " Terms and conditions apply. Talk to our team today.",
                      "image_idea": f"Clean {brand} branded visual about {topic}"},
        "variant_b": {"text": base + risky + " Learn more - T&Cs apply.",
                      "image_idea": f"Bold hook graphic: {topic}"},
    }

def create(brand, platform, language, topic, lessons, research=None):
    b = BRANDS[brand]
    system = (f"You are the social content agent for {brand}, part of JA Assure (Singapore InsurTech).\n"
              f"Niche: {b['niche']}. Voice: {b['voice']}. Audience: {b['audience']}.")
    prompt = f"""Write a {platform} post. Platform style: {PLATFORMS[platform]}.
Language: {language} - localise naturally for Southeast Asian/HK readers, don't translate literally.
Topic: {topic}
Never guarantee outcomes or claim unconditional coverage; mention T&Cs apply where coverage is discussed.
{lessons_block(lessons)}
{("Context from research:\n" + research) if research else ""}
Return JSON: {{"variant_a": {{"text": "...", "image_idea": "..."}},
              "variant_b": {{"text": "...", "image_idea": "..."}}}}
Variant A and B must use different hooks for A/B testing."""
    return generate_json(prompt, system, mock=_mock(brand, platform, language, topic, lessons))
