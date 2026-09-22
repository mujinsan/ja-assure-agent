"""The deterministic rule layer. No LLM, no network."""
import pytest

from agents import compliance


@pytest.mark.parametrize("text,rule", [
    ("Guaranteed payout on every claim.", "Guarantees an outcome"),
    ("Your practice is 100% covered.", "Claims total coverage"),
    ("This policy covers everything.", "Unconditional coverage claim"),
    ("The best cover in Asia.", "Unsubstantiated superlative"),
    ("Act now or lose everything.", "Misleading urgency/fear"),
    ("We ensure your claim is paid.", "Guarantees an outcome"),
])
def test_hard_rules_block(text, rule):
    assert rule in compliance.hard_reasons(text)


@pytest.mark.parametrize("text", [
    "Indemnity cover protects your practice. T&Cs apply.",
    "Please ensure you read the terms before applying.",
    "We work hard to ensure quality care for every patient.",
])
def test_clean_copy_passes(text):
    assert compliance.hard_reasons(text) == []


def test_ensure_only_fires_as_a_coverage_promise():
    # the verb alone is fine; it is only a problem next to a coverage word
    assert compliance.hard_reasons("Ensure your details are up to date.") == []
    assert "Guarantees an outcome" in compliance.hard_reasons(
        "We ensure your clinic is covered.")


def test_hard_matches_are_ordered_and_non_overlapping():
    text = "Guaranteed payout, 100% covered - the best cover in Asia!"
    spans = compliance.hard_matches(text)
    assert spans, "expected at least one match"
    for (s, e, _), (s2, _e2, _r) in zip(spans, spans[1:]):
        assert e <= s2, "spans must not overlap"
        assert s < e


def test_split_reasons_separates_the_two_layers():
    rule_line, rule_ok, ai_line, ai_ok = compliance.split_reasons(
        "Guarantees an outcome; LLM: reads as a hard sell")
    assert rule_ok is False and ai_ok is False
    assert "Guarantees an outcome" in rule_line
    assert "hard sell" in ai_line


def test_split_reasons_clean_asset():
    rule_line, rule_ok, ai_line, ai_ok = compliance.split_reasons("")
    assert rule_ok and ai_ok
    assert str(len(compliance.HARD_RULES)) in rule_line


def test_split_reasons_deduplicates_shared_labels():
    # the guarantee rule and the "ensure ... covered" rule share a label
    line, _, _, _ = compliance.split_reasons(
        "Guarantees an outcome; Guarantees an outcome")
    assert line.count("Guarantees an outcome") == 1
