"""Heuristic reason-tag suggestion for the Review tab. No LLM calls.

Every rule is evaluated against the asset; the winner is chosen by PRIORITY,
not by which rule happens to be written first.
"""
import re
from config import PLATFORMS

# Most specific / most serious first.
PRIORITY = ["inaccurate claim", "too salesy", "too long", "wrong CTA",
            "poor localisation", "off-brand tone"]

SALESY = re.compile(r"\bact now\b|\bdon'?t miss\b|\blimited time\b", re.I)

# Deliberately excludes a bare "apply": "T&Cs apply" is on nearly every asset
# by compliance requirement, and would mask a genuinely missing CTA.
CTA = re.compile(
    r"\b(learn more|find out more|talk to|speak to|contact|get in touch|book|"
    r"enquire|enquiry|call us|dm us|message us|visit|sign up|apply now|"
    r"get a quote|request a quote|explore|discover more|reach out)\b", re.I)


def platform_limit(platform):
    """(limit, unit) parsed from the platform style string in config.

    Parsed rather than duplicated so the numbers can't drift from the text the
    content agent is actually prompted with. Returns (None, None) if absent.
    """
    style = PLATFORMS.get(platform, "") or ""
    m = re.search(r"(\d+)(?:\s*[-–]\s*(\d+))?\s*words", style, re.I)
    if m:
        return int(m.group(2) or m.group(1)), "words"
    m = re.search(r"(\d+)\s*characters", style, re.I)
    if m:
        return int(m.group(1)), "chars"
    return None, None


def is_too_long(text, platform):
    limit, unit = platform_limit(platform)
    if not limit:
        return False
    size = len(text.split()) if unit == "words" else len(text)
    return size > limit


def is_too_salesy(text):
    return bool(SALESY.search(text)) or text.count("!") >= 2


def has_compliance_warning(asset):
    """Either layer flagged something - the stored reasons string is non-empty."""
    return bool((asset.get("compliance_reasons") or "").strip())


def has_no_cta(text):
    """Trailing hashtags aren't an ask, but a closing question is."""
    core = re.sub(r"(?:#\w+\s*)+$", "", (text or "").strip()).strip()
    if CTA.search(core):
        return False
    return not core.endswith("?")


def is_non_english(asset):
    return (asset.get("language") or "English") != "English"


def suggest_tag(asset):
    """Best-guess reason tag for an asset, or None if nothing matches."""
    text = asset.get("content") or ""
    platform = asset.get("platform") or ""

    hits = set()
    if has_compliance_warning(asset):
        hits.add("inaccurate claim")
    if is_too_salesy(text):
        hits.add("too salesy")
    if is_too_long(text, platform):
        hits.add("too long")
    if has_no_cta(text):
        hits.add("wrong CTA")
    if is_non_english(asset):
        hits.add("poor localisation")

    for tag in PRIORITY:
        if tag in hits:
            return tag
    return None
