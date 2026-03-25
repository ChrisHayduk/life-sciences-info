from __future__ import annotations

from app.db import normalize_database_url


def test_normalize_database_url_handles_render_postgres_urls():
    assert normalize_database_url("postgres://user:pass@host:5432/db") == "postgresql+psycopg://user:pass@host:5432/db"
    assert normalize_database_url("postgresql://user:pass@host:5432/db") == "postgresql+psycopg://user:pass@host:5432/db"
    assert normalize_database_url("postgresql+psycopg://user:pass@host:5432/db") == "postgresql+psycopg://user:pass@host:5432/db"
