"""The LLM summary feature is gone; summaries come from rules only.

Databases from before the removal still hold the old settings table with an
encrypted API key, so startup drops it.
"""
from pathlib import Path


def test_strategy_page_has_no_summary_api_settings():
    repo_root = Path(__file__).resolve().parents[2]
    template_path = repo_root / "dca_service" / "src" / "dca_service" / "templates" / "strategy.html"
    html = template_path.read_text(encoding="utf-8")

    assert "Summary API" not in html
    assert "summaryApiForm" not in html
    assert "/api/summary-api/" not in html


def test_migration_drops_the_old_summary_api_settings_table(tmp_path, monkeypatch):
    from sqlmodel import create_engine, text

    import dca_service.database as database

    old_engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with old_engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE summary_api_settings (id INTEGER PRIMARY KEY, api_key_encrypted VARCHAR)"
        ))
        conn.execute(text("INSERT INTO summary_api_settings (id, api_key_encrypted) VALUES (1, 'secret')"))
    monkeypatch.setattr(database, "engine", old_engine)

    database._drop_summary_api_settings_table()
    database._drop_summary_api_settings_table()  # idempotent

    with old_engine.connect() as conn:
        table = conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='summary_api_settings'"
        )).first()
    assert table is None
