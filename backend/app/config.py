from functools import lru_cache
from pathlib import Path
from typing import Annotated, List, Literal

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(Path(__file__).resolve().parents[2] / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Life Sciences Intelligence"
    api_prefix: str = "/api/v1"
    database_url: str = "sqlite:///./data/app.db"
    redis_url: str = "redis://localhost:6379/0"
    sec_user_agent: str = "LifeSciencesIntel/0.1 (contact: ops@example.com)"
    sec_base_url: str = "https://data.sec.gov"
    sec_tickers_url: str = "https://www.sec.gov/files/company_tickers_exchange.json"
    openai_api_key: str | None = None
    openai_api_base: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-5-mini"
    market_data_provider: Literal["fmp", "alpha_vantage", "none"] = "fmp"
    clinical_trials_provider: Literal["aact_cloud", "ctgov_api", "none"] = "aact_cloud"
    aact_db_host: str = "aact-db.ctti-clinicaltrials.org"
    aact_db_port: int = 5432
    aact_db_name: str = "aact"
    aact_db_user: str | None = None
    aact_db_password: str | None = None
    clinical_trials_recent_days: int = 730
    fmp_api_key: str | None = None
    fmp_base_url: str = "https://financialmodelingprep.com/stable"
    alpha_vantage_api_key: str | None = None
    alpha_vantage_base_url: str = "https://www.alphavantage.co/query"
    object_store_endpoint_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("OBJECT_STORE_ENDPOINT_URL", "S3_ENDPOINT_URL"),
    )
    object_store_access_key_id: str | None = Field(
        default=None,
        validation_alias=AliasChoices("OBJECT_STORE_ACCESS_KEY_ID", "S3_ACCESS_KEY_ID"),
    )
    object_store_secret_access_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("OBJECT_STORE_SECRET_ACCESS_KEY", "S3_SECRET_ACCESS_KEY"),
    )
    object_store_region: str | None = Field(
        default=None,
        validation_alias=AliasChoices("OBJECT_STORE_REGION", "AWS_REGION"),
    )
    object_store_bucket: str = Field(
        default="life-sciences-docs",
        validation_alias=AliasChoices("OBJECT_STORE_BUCKET", "S3_BUCKET"),
    )
    local_artifact_dir: str = "./data/artifacts"
    frontend_base_url: str = "http://localhost:3000"
    api_base_url: str = "http://localhost:8000"
    cors_origins: Annotated[List[str], NoDecode] = Field(default_factory=lambda: ["http://localhost:3000"])
    admin_api_token: str | None = None
    enable_scheduler: bool = False
    enable_browser_pdf_rendering: bool = True
    browser_pdf_timeout_seconds: float = 45.0
    max_filing_summaries_per_day: int = 3
    max_news_summaries_per_day: int = 7
    max_override_summaries_per_day: int = 2
    max_filing_summaries_per_run: int = 2
    max_news_summaries_per_run: int = 4
    company_ir_top_company_limit: int = 25
    catalyst_lookahead_days: int = 180
    recent_catalyst_days: int = 90
    news_summary_backlog_days: int = 3
    filing_summary_backlog_days: int = 14
    timezone: str = "America/New_York"
    digest_weekday: str = "mon"
    digest_hour: int = 8
    digest_minute: int = 0
    sec_rate_limit_delay_seconds: float = 0.2
    source_fetch_timeout_seconds: float = 30.0
    summary_prompt_version: str = "2026-03-28.v2"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value):
        if value is None or value == "":
            return ["http://localhost:3000"]
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("market_data_provider", mode="before")
    @classmethod
    def normalize_market_data_provider(cls, value):
        if value is None or value == "":
            return "fmp"
        return str(value).strip().lower()

    @field_validator("clinical_trials_provider", mode="before")
    @classmethod
    def normalize_clinical_trials_provider(cls, value):
        if value is None or value == "":
            return "aact_cloud"
        return str(value).strip().lower()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
