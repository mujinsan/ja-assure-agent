"""Standalone Groq connectivity check. Never prints the API key itself."""
import os, sys, traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import load_dotenv

load_dotenv(ROOT / ".env")

key = os.getenv("GROQ_API_KEY") or ""
print(f"key present: {bool(key)}  length: {len(key)}  prefix: {key[:4]!r}")
print(f"looks like a Groq key (gsk_ prefix): {key.startswith('gsk_')}")

if not key:
    print("No GROQ_API_KEY loaded - the fallback leg is dormant.")
    raise SystemExit(1)

from agents import llm
print(f"model: {llm.GROQ_MODEL}")

try:
    import requests
    r = requests.get(f"{llm.GROQ_BASE_URL}/models",
                     headers={"Authorization": f"Bearer {key}"}, timeout=30)
    r.raise_for_status()
    ids = sorted(m["id"] for m in r.json().get("data", []))
    print(f"models visible to this key: {len(ids)}")
    print(f"configured model available: {llm.GROQ_MODEL in ids}")
    if llm.GROQ_MODEL not in ids:
        print("  pick one of:", ", ".join(i for i in ids if "llama" in i) or ids[:5])
except Exception:
    print("--- could not list models ---")
    traceback.print_exc()

try:
    out = llm._groq('Reply with JSON exactly: {"ping": "pong"}')
    print("--- SUCCESS ---")
    print("parsed response:", out)
except Exception:
    print("--- FAILURE ---")
    traceback.print_exc()
    raise SystemExit(2)
