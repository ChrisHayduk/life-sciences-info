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
    from app import models  # noqa: F401

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

    _add_missing_model_columns()


def _add_missing_model_columns() -> None:
    inspector = inspect(engine)
    for table in Base.metadata.sorted_tables:
        if not inspector.has_table(table.name):
            continue

        existing_columns = {column["name"] for column in inspector.get_columns(table.name)}
        missing_columns = [column for column in table.columns if column.name not in existing_columns]
        if not missing_columns:
            continue

        with engine.begin() as connection:
            for column in missing_columns:
                connection.execute(text(_add_column_sql(table.name, column)))

def _add_column_sql(table_name: str, column) -> str:
    preparer = engine.dialect.identifier_preparer
    table_sql = preparer.quote(table_name)
    column_sql = preparer.quote(column.name)
    column_type = column.type.compile(dialect=engine.dialect)
    statement = f"ALTER TABLE {table_sql} ADD COLUMN {column_sql} {column_type}"
    default_sql = _default_sql(column)
    if default_sql is not None:
        statement += f" DEFAULT {default_sql}"
    return statement


def _default_sql(column) -> str | None:
    default = column.default
    if default is None or not getattr(default, "is_scalar", False):
        return None

    value = default.arg
    literal_processor = column.type.literal_processor(engine.dialect)
    if literal_processor is not None:
        return literal_processor(value)
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    return None
