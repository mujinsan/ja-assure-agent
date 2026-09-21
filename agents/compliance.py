"""Compliance gate: deterministic rule layer + LLM rubric layer. Either can block."""
import re
from config import COMPLIANCE_RUBRIC
from agents.llm import generate_json, live

HARD_RULES = [
    (r"\bguarantee(d|s)?\b", "Guarantees an outcome"),
    # "ensure(s) [that] ... <coverage word>" inside one sentence = a coverage promise.
    # Benign uses like "ensure you read the T&Cs" stay allowed.
    (r"\bensures?\b(\s+that\b)?[^.!?]{0,40}?"
     r"\b(cover(s|ed|age)?|payout|paid|claims?|compensat\w*|protect(s|ed|ion)?|reimburs\w*)\b",
     "Guarantees an outcome"),
    (r"100\s*%\s*(covered|coverage|protection)", "Claims total coverage"),
    (r"\b(covers everything|no exclusions|always pays?)\b", "Unconditional coverage claim"),
    (r"\b(best|cheapest|#1|number one)\b", "Unsubstantiated superlative"),
    (r"\b(act now or|lose everything)\b", "Misleading urgency/fear"),
]

def hard_reasons(text):
    """Deterministic regex layer. Always per-variant, never batched."""
    return [msg for pat, msg in HARD_RULES if re.search(pat, text, re.I)]

def _summarise(hits, limit=52):
    """One short line for a narrow grid cell: name the first hit, count the rest.

    De-duplicates first: two rules can share a label (the guarantee rule and the
    "ensure ... covered" rule both report "Guarantees an outcome"), and showing
    the same phrase twice reads as a bug.
    """
    seen = []
    for h in hits:
        if h not in seen:
            seen.append(h)
    first = seen[0]
    if len(first) > limit:
        first = first[:limit - 1].rstrip() + "…"
    return first if len(seen) == 1 else f"{first} +{len(seen) - 1} more"

def split_reasons(reasons_text):
    """Split a stored compliance_reasons string into the two UI layers.

    Input is what db stores: reasons joined by "; ", where entries from the LLM
    rubric carry an "LLM: " prefix and everything else came from HARD_RULES.
    An empty string means the asset passed both layers.

      "Guarantees an outcome; LLM: reads as a hard sell"

    Returns (rule_line, rule_ok, ai_line, ai_ok) for theme.compliance_boxes():
    a short human sentence per layer plus whether that layer passed.
    """
    parts = [p.strip() for p in (reasons_text or "").split(";") if p.strip()]
    rule_hits = [p for p in parts if not p.startswith("LLM:")]
    ai_hits = [p[4:].strip() for p in parts if p.startswith("LLM:")]

    total = len(HARD_RULES)
    rule_line = _summarise(rule_hits) if rule_hits else f"{total} of {total} rules passed"
    ai_line = _summarise(ai_hits) if ai_hits else "No issues flagged"
    return (rule_line, not rule_hits, ai_line, not ai_hits)

def check_batch(items):
    """items: list of (key, text). One LLM call for the whole run.

    Returns {key: (ok, reasons)}. The regex layer still runs per variant.
    """
    reasons = {key: hard_reasons(text) for key, text in items}
    if live() and items:
        blocks = "\n\n".join(f'VARIANT {key}:\n"""{text}"""' for key, text in items)
        r = generate_json(
            f"{COMPLIANCE_RUBRIC}\n\nJudge each variant below independently.\n\n{blocks}\n"
            'Return JSON: {"results": [{"variant": "<key>", "pass": true/false,'
            ' "reasons": ["..."]}]} with one entry per variant.')
        for res in (r or {}).get("results", []):
            key = str(res.get("variant", "")).strip()
            if key in reasons and not res.get("pass", True):
                reasons[key] += [f"LLM: {x}" for x in res.get("reasons", [])]
    return {key: (len(v) == 0, v) for key, v in reasons.items()}

def check(text):
    reasons = hard_reasons(text)
    if live():
        r = generate_json(
            f"{COMPLIANCE_RUBRIC}\n\nAsset:\n\"\"\"{text}\"\"\"\n"
            'Return JSON: {"pass": true/false, "reasons": ["..."]}')
        if r and not r.get("pass", True):
            reasons += [f"LLM: {x}" for x in r.get("reasons", [])]
    return (len(reasons) == 0), reasons
