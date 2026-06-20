import os
from wc2026bot.config import load_settings

def test_load_settings_reads_env(monkeypatch):
    monkeypatch.setenv("BOT_TOKEN", "abc")
    monkeypatch.setenv("DB_PATH", "/tmp/x.db")
    s = load_settings()
    assert s.bot_token == "abc"
    assert s.db_path == "/tmp/x.db"
    assert s.footballdata_key is None

def test_load_settings_requires_token(monkeypatch):
    monkeypatch.delenv("BOT_TOKEN", raising=False)
    import pytest
    with pytest.raises(ValueError):
        load_settings()
