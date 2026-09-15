"""Standalone Gemini connectivity check. Never prints the API key itself."""
import os, sys, traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

key = os.getenv("GEMINI_API_KEY") or ""
model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

print(f"key present: {bool(key)}  length: {len(key)}  prefix: {key[:4]!r}")
print(f"looks like a Google API key (AIza prefix): {key.startswith('AIza')}")
print(f"model: {model}")

try:
    import importlib.metadata as md
    print(f"google-genai version: {md.version('google-genai')}")
except Exception as e:
    print(f"could not read google-genai version: {e}")

if not key:
    print("No GEMINI_API_KEY loaded - stopping.")
    raise SystemExit(1)

try:
    from google import genai
    client = genai.Client(api_key=key)
    resp = client.models.generate_content(model=model, contents="Reply with exactly: pong")
    print("--- SUCCESS ---")
    print(repr(resp.text))
except Exception:
    print("--- FAILURE ---")
    traceback.print_exc()
    raise SystemExit(2)
