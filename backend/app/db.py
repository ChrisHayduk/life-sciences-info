from collections.abc import Generator
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalize_database_url(database_url: str) -> str:
    if database_url.startswith("postgresql+"):
        return database_url
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


settings = get_settings()
database_url = normalize_database_url(settings.database_url)

if database_url.startswith("sqlite:///"):
    sqlite_path = Path(database_url.replace("sqlite:///", "", 1))
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)

connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
engine = create_engine(database_url, future=True, connect_args=connect_args, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_session() -> Generator[Session, None, None]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def init_db() -> None:
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    _ensure_compatible_schema()


def _ensure_compatible_schema() -> None:
    inspector = inspect(engine)
    if inspector.has_table("companies"):
        market_cap_column = next(
            (column for column in inspector.get_columns("companies") if column["name"] == "market_cap"),
            None,
        )
        if market_cap_column is not None:
            type_name = market_cap_column["type"].__class__.__name__.upper()
            if type_name not in {"BIGINTEGER", "BIGINT"} and engine.dialect.name == "postgresql":
                with engine.begin() as connection:
                    connection.execute(text("ALTER TABLE companies ALTER COLUMN market_cap TYPE BIGINT"))

    _add_missing_columns(
        table_name="news_items",
        columns={
            "company_tag_ids": "JSON",
        },
    )
    _add_missing_columns(
        table_name="filings",
        columns={
            "item_numbers": "JSON",
            "diff_json": "JSON",
            "diff_status": "VARCHAR(32)",
        },
    )


def _add_missing_columns(*, table_name: str, columns: dict[str, str]) -> None:
    inspector = inspect(engine)
    if not inspector.has_table(table_name):
        return

    existing_columns = {column["name"] for column in inspector.get_columns(table_name)}
    missing_columns = {name: sql_type for name, sql_type in columns.items() if name not in existing_columns}
    if not missing_columns:
        return

    with engine.begin() as connection:
        for column_name, sql_type in missing_columns.items():
            connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {sql_type}"))
