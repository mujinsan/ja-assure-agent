"""Thin Gemini wrapper with a configurable model chain and a Groq fallback.

Order per call: GEMINI_MODEL -> each GEMINI_FALLBACK_MODELS entry -> Groq -> mock.
Only quota/rate-limit and model-not-found errors advance the chain; anything else
goes straight to mock so real bugs stay visible.
"""
import json, os, re
from dotenv import load_dotenv

load_dotenv()
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
FALLBACK_MODELS = [m.strip() for m in
                   os.getenv("GEMINI_FALLBACK_MODELS",
                             "gemini-3.5-flash-lite,gemini-3.5-flash").split(",")
                   if m.strip()]
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
_client = None
last_error = None     # str of the most recent failed call, None if the last call succeeded
last_provider = None  # "gemini" | "groq" | "mock" - who answered the last call
last_model = None     # the model that actually answered
exhausted_models = set()  # models known dead for the rest of this session

def live():
    return bool(os.getenv("GEMINI_API_KEY"))

def _get():
    global _client
    if _client is None:
        from google import genai
        _client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    return _client

def model_chain():
    """GEMINI_MODEL first, then the configured fallbacks, de-duplicated."""
    out = []
    for m in [MODEL] + FALLBACK_MODELS:
        if m not in out:
            out.append(m)
    return out

def _parse(text):
    text = re.sub(r"```(?:json)?|```", "", text or "").strip()
    m = re.search(r"\{.*\}", text, re.S)
    return json.loads(m.group(0) if m else text)

def _classify(e):
    """quota (retry elsewhere) | missing (model gone) | other (a real bug)."""
    s = str(e)
    if re.search(r"\b429\b|RESOURCE_EXHAUSTED|quota|rate.?limit", s, re.I):
        return "quota"
    if re.search(r"\b404\b|NOT_FOUND|not found|no longer available", s, re.I):
        return "missing"
    return "other"

def _is_daily_quota(e):
    """A per-day cap is dead until tomorrow; a per-minute cap is not."""
    return bool(re.search(r"per\s*day|perday|daily", str(e), re.I))

def _groq(full):
    """Groq's OpenAI-compatible chat completions. Raises on any failure."""
    import requests
    key = os.getenv("GROQ_API_KEY")
    if not key:
        raise RuntimeError("GROQ_API_KEY not set")
    r = requests.post(
        f"{GROQ_BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={"model": GROQ_MODEL, "messages": [{"role": "user", "content": full}]},
        timeout=60)
    r.raise_for_status()
    return _parse(r.json()["choices"][0]["message"]["content"])

def _mock(mock, error=None):
    global last_error, last_provider, last_model
    last_error, last_provider, last_model = error, "mock", None
    return mock or {}

def generate_json(prompt, system="", mock=None):
    global last_error, last_provider, last_model
    if not live():
        return _mock(mock)
    full = (system + "\n\n" if system else "") + prompt + \
        "\n\nRespond with ONLY valid JSON. No markdown fences, no commentary."

    errors = []
    for model in model_chain():
        if model in exhausted_models:
            continue
        try:
            resp = _get().models.generate_content(model=model, contents=full)
            out = _parse(resp.text)
            last_error, last_provider, last_model = None, "gemini", model
            return out
        except Exception as e:
            kind = _classify(e)
            if kind == "other":
                print(f"[llm] {model} failed, using mock: {e}")
                return _mock(mock, str(e))
            errors.append(f"{model}: {e}")
            if kind == "missing":
                exhausted_models.add(model)
                print(f"[llm] {model} unavailable - skipping it this session")
            elif _is_daily_quota(e):
                exhausted_models.add(model)
                print(f"[llm] {model} daily quota exhausted - skipping it this session")
            else:
                print(f"[llm] {model} rate limited - trying next model")

    if not errors:  # every model was skipped without being retried
        errors.append("Gemini models already exhausted this session: "
                      + ", ".join(m for m in model_chain() if m in exhausted_models))

    if os.getenv("GROQ_API_KEY"):
        print(f"[llm] Gemini chain exhausted, retrying via Groq ({GROQ_MODEL})")
        try:
            out = _groq(full)
            last_error, last_provider, last_model = None, "groq", GROQ_MODEL
            return out
        except Exception as ge:
            errors.append(f"groq: {ge}")
            print(f"[llm] Groq fallback failed: {ge}")

    print("[llm] no provider available, using mock")
    return _mock(mock, " | ".join(errors))
