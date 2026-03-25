from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

from app.db import Base, get_session
from app.main import app
from app.models import Company


@pytest.fixture
def db_session(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_ARTIFACT_DIR", str(tmp_path / "artifacts"))
    monkeypatch.setenv("OPENAI_API_KEY", "")
    monkeypatch.setenv("ALPHA_VANTAGE_API_KEY", "")
    from app.config import get_settings

    get_settings.cache_clear()
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    Base.metadata.create_all(bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


@pytest.fixture
def client(db_session, monkeypatch):
    def override_get_session():
        yield db_session

    app.dependency_overrides[get_session] = override_get_session
    monkeypatch.setattr("app.main.init_db", lambda: None)
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def company(db_session):
    company = Company(
        cik="0000000123",
        ticker="ABIO",
        name="Apex Bio",
        exchange="NASDAQ",
        sic="2836",
        sic_description="BIOLOGICAL PRODUCTS",
        market_cap=1_500_000_000,
        market_cap_source="test",
        market_cap_updated_at=datetime.now(timezone.utc),
        is_active=True,
    )
    db_session.add(company)
    db_session.commit()
    db_session.refresh(company)
    return company
