"""Brand voices, platform styles and the compliance rubric."""

BRANDS = {
    "Jade": {
        "niche": "insurance for jewellers (jewellers block cover)",
        "voice": "refined, trustworthy, premium; speaks to jewellery business owners; calm expertise",
        "audience": "jewellery store owners, gold/diamond traders",
    },
    "Jaguar Transit": {
        "niche": "high-value goods in transit insurance",
        "voice": "confident, precise, logistics-savvy; focused on security and continuity",
        "audience": "couriers, logistics firms, SMEs shipping valuables",
    },
    "DoctorShield": {
        "niche": "medical indemnity insurance",
        "voice": "empathetic, professional, reassuring; respects clinicians' time",
        "audience": "doctors, clinic owners, medical professionals",
    },
}

PLATFORMS = {
    "LinkedIn": "professional, 120-200 words, insight-led, 3 hashtags max",
    "Instagram": "visual caption, 50-90 words, friendly, emojis allowed, 5-8 hashtags, include an image idea",
    "X": "under 270 characters, hook-first, 1-2 hashtags",
}

LANGUAGES = ["English", "Malay", "Bahasa Indonesia", "Thai", "Chinese"]
MARKETS = ["Singapore", "Malaysia", "Hong Kong", "Indonesia", "Thailand"]

FEEDBACK_TAGS = [
    "too salesy", "inaccurate claim", "off-brand tone",
    "wrong CTA", "poor localisation", "too long", "other",
]

COMPLIANCE_RUBRIC = """
Insurance marketing rules. An asset FAILS if it:
1. Guarantees payouts, approval, or outcomes ("guaranteed", "100% covered", "always pays").
2. Claims coverage without conditions/exclusions ("covers everything", "no exclusions").
3. Uses absolute or comparative superlatives without evidence ("best", "cheapest", "#1").
4. Creates fear or urgency in a misleading way ("act now or lose everything").
5. Promises specific premium prices or discounts not stated as indicative.
6. Gives personalised financial/legal advice.
7. Omits that terms and conditions apply when discussing coverage.
"""
