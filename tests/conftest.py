"""Shared fixtures. Every test runs against a throwaway database and never
touches the network: the LLM rubric layer and any publisher are stubbed off.
"""
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


@pytest.fixture()
def tmpdb(tmp_path, monkeypatch):
    """A fresh SQLite file per test, with db re-pointed at it."""
    path = tmp_path / "test.db"
    monkeypatch.setenv("DB_PATH", str(path))
    monkeypatch.setenv("MEDIA_DIR", str(tmp_path / "media"))
    monkeypatch.setenv("OUTBOX_PATH", str(tmp_path / "outbox.jsonl"))
    # publishing must never be live inside tests
    monkeypatch.delenv("AYRSHARE_API_KEY", raising=False)

    import db
    monkeypatch.setattr(db, "DB_PATH", str(path))
    db.init()
    return db


@pytest.fixture()
def offline(monkeypatch):
    """Force the deterministic path: no LLM rubric call, no network."""
    from agents import compliance
    monkeypatch.setattr(compliance, "live", lambda: False)
    return compliance


@pytest.fixture()
def make_asset(tmpdb):
    """Insert an asset and return its id."""
    def _make(**kw):
        row = dict(
            brand="DoctorShield", platform="LinkedIn", language="English",
            topic="indemnity", variant="A",
            content="Indemnity cover protects your practice. T&Cs apply. Talk to our team.",
            image_idea="", compliance_pass=True, compliance_reasons="",
            status="pending", lessons_used=0, provider="gemini")
        row.update(kw)
        return tmpdb.insert_asset(**row)
    return _make


@pytest.fixture()
def get_asset(tmpdb):
    def _get(asset_id):
        return [a for a in tmpdb.list_assets() if a["id"] == asset_id][0]
    return _get
