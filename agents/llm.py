"""Thin Gemini wrapper with a configurable model chain and a Groq fallback.

Order per call: GEMINI_MODEL -> each GEMINI_FALLBACK_MODELS entry -> Groq -> mock.
Quota, model-not-found and transient errors (503, timeouts, connection drops)
advance the chain; a 503 also earns one 2s retry on the same model first.
Anything else goes straight to mock so real bugs stay visible rather than being
retried into silence. Mock is only reached once every provider has failed.
"""
import json, os, re, time
from dotenv import load_dotenv

load_dotenv()
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
FALLBACK_MODELS = [m.strip() for m in
                   os.getenv("GEMINI_FALLBACK_MODELS",
                             "gemini-3.5-flash-lite,gemini-3.5-flash").split(",")
                   if m.strip()]
GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-120b")
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
_client = None
last_error = None     # str of the most recent failed call, None if the last call succeeded
last_provider = None  # "gemini" | "groq" | "mock" - who answered the last call
last_model = None     # the model that actually answered
last_summary = None   # one-line human summary of the last fallback, for the UI
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
    """quota | missing | transient | other.

    The first three are fallback-worthy. "other" is a real bug and goes straight
    to mock so it stays visible instead of being retried into silence.
    """
    s = str(e)
    if re.search(r"\b429\b|RESOURCE_EXHAUSTED|quota|rate.?limit", s, re.I):
        return "quota"
    if re.search(r"\b404\b|NOT_FOUND|not found|no longer available", s, re.I):
        return "missing"
    # 502/503/504 are gateway-level "try again"; a bare 500 is not, it stays
    # "other" so a genuine server bug is shown rather than retried into silence.
    if re.search(r"\b50[234]\b|UNAVAILABLE|high demand|overload|"
                 r"timed?.?out|timeout|deadline|connection|network|"
                 r"ConnectError|ReadError|SSL", s, re.I):
        return "transient"
    return "other"

def _is_busy(e):
    """A 503-style 'try again' - worth one immediate retry on the same model."""
    return bool(re.search(r"\b503\b|UNAVAILABLE|high demand|overload", str(e), re.I))

def _is_daily_quota(e):
    """A per-day cap is dead until tomorrow; a per-minute cap is not."""
    return bool(re.search(r"per\s*day|perday|daily", str(e), re.I))

def _code(e):
    m = re.search(r"\b([45]\d\d)\b", str(e))
    return m.group(1) if m else "error"

_WORD = {"429": "quota exhausted", "503": "busy", "502": "busy", "504": "busy",
         "500": "error", "404": "model gone"}

def _phrase(e):
    """Short human reason for the UI: 'busy (503)', 'timed out', 'unreachable'."""
    code = _code(e)
    if code in _WORD:
        return f"{_WORD[code]} ({code})"
    s = str(e)
    if re.search(r"timed?.?out|timeout|deadline", s, re.I):
        return "timed out"
    if re.search(r"connection|network|ConnectError|SSL", s, re.I):
        return "unreachable"
    return f"failed ({code})" if code != "error" else "failed"

def _call_gemini(model, full):
    """One model. A 503 gets a single retry after 2s before we give up on it."""
    for attempt in (0, 1):
        try:
            resp = _get().models.generate_content(model=model, contents=full)
            return _parse(resp.text)
        except Exception as e:
            if attempt == 0 and _is_busy(e):
                print(f"[llm] {model} busy ({_code(e)}) - retrying once in 2s")
                time.sleep(2)
                continue
            raise

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
    global last_error, last_provider, last_model, last_summary
    if not live():
        return _mock(mock)
    full = (system + "\n\n" if system else "") + prompt + \
        "\n\nRespond with ONLY valid JSON. No markdown fences, no commentary."

    errors, first = [], None
    for model in model_chain():
        if model in exhausted_models:
            continue
        try:
            out = _call_gemini(model, full)
            last_error, last_provider, last_model = None, "gemini", model
            last_summary = (None if not errors else
                            f"{MODEL} {first} - answered by {model}")
            return out
        except Exception as e:
            kind = _classify(e)
            if kind == "other":
                print(f"[llm] {model} failed, using mock: {e}")
                last_summary = f"{model} error - mock output"
                return _mock(mock, str(e))
            errors.append(f"{model}: {e}")
            first = first or _phrase(e)
            # Only a daily cap or a retired model is dead for the session.
            # A 503 or a per-minute 429 is temporary - try it again next run.
            if kind == "missing":
                exhausted_models.add(model)
                print(f"[llm] {model} unavailable - skipping it this session")
            elif kind == "quota" and _is_daily_quota(e):
                exhausted_models.add(model)
                print(f"[llm] {model} daily quota exhausted - skipping it this session")
            else:
                print(f"[llm] {model} {_phrase(e)} - trying next provider")

    if not errors:  # every model was skipped without being retried
        errors.append("Gemini models already exhausted this session: "
                      + ", ".join(m for m in model_chain() if m in exhausted_models))

    if os.getenv("GROQ_API_KEY"):
        print(f"[llm] Gemini chain exhausted, retrying via Groq ({GROQ_MODEL})")
        try:
            out = _groq(full)
            last_error, last_provider, last_model = None, "groq", GROQ_MODEL
            last_summary = f"Gemini {first or 'unavailable'} - answered by groq"
            return out
        except Exception as ge:
            errors.append(f"groq: {ge}")
            print(f"[llm] Groq fallback failed: {ge}")

    print("[llm] no provider available, using mock")
    last_summary = "All providers failed - mock output"
    return _mock(mock, " | ".join(errors))
