"""Heuristic reason-tag suggestion. Pure functions, no LLM."""
import pytest

import review


def asset(content, platform="LinkedIn", language="English", reasons=""):
    return {"content": content, "platform": platform, "language": language,
            "compliance_reasons": reasons}


CLEAN = "Indemnity cover protects your practice. T&Cs apply. Talk to our team."


def test_no_signal_returns_none():
    assert review.suggest_tag(asset(CLEAN)) is None


def test_compliance_warning_wins():
    assert review.suggest_tag(
        asset(CLEAN, reasons="Guarantees an outcome")) == "inaccurate claim"


def test_llm_only_warning_still_counts():
    assert review.suggest_tag(asset(CLEAN, reasons="LLM: too pushy")) == "inaccurate claim"


@pytest.mark.parametrize("text", ["Act now! " + CLEAN, CLEAN + " Amazing!! Really!"])
def test_salesy_markers(text):
    assert review.suggest_tag(asset(text)) == "too salesy"


def test_single_exclamation_is_not_salesy():
    assert review.suggest_tag(asset(CLEAN + " Great!")) is None


def test_too_long_uses_the_platform_limit():
    limit, unit = review.platform_limit("LinkedIn")
    assert (limit, unit) == (200, "words")
    long_text = ("word " * (limit + 5)) + "talk to us"
    assert review.suggest_tag(asset(long_text)) == "too long"


def test_x_limit_is_characters():
    assert review.platform_limit("X") == (270, "chars")
    assert review.suggest_tag(asset("x" * 300 + " contact us", platform="X")) == "too long"


def test_missing_cta():
    assert review.suggest_tag(
        asset("Indemnity cover protects your practice. T&Cs apply.")) == "wrong CTA"


def test_tcs_apply_is_not_a_cta():
    # "apply" in "T&Cs apply" must not be mistaken for a call to action
    assert review.has_no_cta("Cover protects your practice. T&Cs apply.") is True


def test_closing_question_counts_as_a_cta():
    assert review.has_no_cta(
        "Risk is real. What has worked in your clinic? #Tag #Tag2") is False


def test_priority_order_every_rule_evaluated():
    # salesy + too long + no CTA + non-English + compliance all match at once
    everything = asset("Act now!! " + ("word " * 210), language="Thai",
                       reasons="Guarantees an outcome")
    assert review.suggest_tag(everything) == "inaccurate claim"
    del everything["compliance_reasons"]
    assert review.suggest_tag(everything) == "too salesy"
