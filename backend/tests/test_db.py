from __future__ import annotations

from sqlalchemy import create_engine, inspect, text

import app.db as db_module
from app.db import normalize_database_url


def test_normalize_database_url_handles_render_postgres_urls():
    assert normalize_database_url("postgres://user:pass@host:5432/db") == "postgresql+psycopg://user:pass@host:5432/db"
    assert normalize_database_url("postgresql://user:pass@host:5432/db") == "postgresql+psycopg://user:pass@host:5432/db"
    assert normalize_database_url("postgresql+psycopg://user:pass@host:5432/db") == "postgresql+psycopg://user:pass@host:5432/db"


def test_ensure_compatible_schema_adds_missing_legacy_columns(monkeypatch):
    engine = create_engine("sqlite:///:memory:", future=True)
    monkeypatch.setattr(db_module, "engine", engine)

    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE companies (id INTEGER PRIMARY KEY, market_cap INTEGER)"))
        connection.execute(text("CREATE TABLE news_items (id INTEGER PRIMARY KEY)"))
        connection.execute(
            text(
                """
                CREATE TABLE filings (
                    id INTEGER PRIMARY KEY,
                    company_id INTEGER,
                    accession_number VARCHAR(32),
                    form_type VARCHAR(16),
                    normalized_form_type VARCHAR(16),
                    filed_at DATETIME
                )
                """
            )
        )

    db_module._ensure_compatible_schema()

    inspector = inspect(engine)
    news_columns = {column["name"] for column in inspector.get_columns("news_items")}
    filing_columns = {column["name"] for column in inspector.get_columns("filings")}

    assert "company_tag_ids" in news_columns
    assert {"item_numbers", "diff_json", "diff_status"} <= filing_columns
