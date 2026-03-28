# Life Sciences Intelligence Platform

Private single-tenant monitoring platform for public life sciences issuers. The project combines:

- SEC periodic filings ingestion for core life sciences companies
- OpenAI-generated filing and news summaries
- Ranking by market cap plus filing/article importance
- Weekly in-app digest generation
- React web UI for filings, news, companies, and digests

## Stack

- Backend: FastAPI, SQLAlchemy, PostgreSQL
- Storage: S3-compatible object storage (Cloudflare R2, AWS S3, or MinIO locally)
- Frontend: Next.js + TypeScript
- Scheduling: APScheduler with optional Dramatiq/Redis for async work

## Repo Layout

- `backend/` FastAPI app, workers, ingestion services, tests
- `web/` Next.js app
- `docker-compose.yml` local infrastructure and app services

## Quick Start

1. Copy `.env.example` to `.env` and set `SEC_USER_AGENT`, `OPENAI_API_KEY`, `MARKET_DATA_PROVIDER`, and `FMP_API_KEY`.
2. Start local infrastructure:

```bash
docker compose up --build
```

3. Visit [http://localhost:3000](http://localhost:3000) for the web app and [http://localhost:8000/docs](http://localhost:8000/docs) for the API docs.

## Recommended Deployment

The repo is prepared for a low-maintenance production path:

- Vercel for the frontend in `web/`
- Render for the backend in `backend/` plus managed Postgres
- Cloudflare R2 for filing artifacts and PDFs

See the full guide in [docs/deployment.md](/Users/christopherhayduk/Desktop/life-sciences-info/docs/deployment.md).

## Local Development Without Docker

Backend:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

One-command local bootstrap:

```bash
cp .env.example .env
cd backend
python -m app.bootstrap --sync-limit 250 --backfill-companies 10
```

This path uses local SQLite and filesystem artifacts if Docker/Postgres/object storage are unavailable.

Worker:

```bash
cd backend
source .venv/bin/activate
dramatiq app.workers
```

Frontend:

```bash
cd web
npm install
npm run dev
```

## Core Background Jobs

- `sync_universe` refreshes covered SEC issuers and applies manual overrides
- `refresh_market_caps` refreshes cached company market caps using the configured market-data provider
- `backfill_company` loads historical target filings for one company
- `poll_sec_filings` finds newly filed periodic reports
- `ingest_news` pulls RSS/news sources and summarizes new stories
- `summarize_pending` processes queued filings/news within the configured daily and per-run budgets
- `build_weekly_digest` creates the Monday 8:00 AM ET digest
- `python -m app.jobs ...` runs these tasks directly for deployment or maintenance
- `python -m app.jobs refresh-all-data ...` resyncs companies, refreshes market caps, rebuilds stored filings in place, and backfills anything missing

## Minimal Local Configuration

If Docker is unavailable, use a local `.env` with:

```env
DATABASE_URL=sqlite:///./data/app.db
REDIS_URL=redis://localhost:6379/0
LOCAL_ARTIFACT_DIR=./backend/data/artifacts
API_BASE_URL=http://localhost:8000
FRONTEND_BASE_URL=http://localhost:3000
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api/v1
CORS_ORIGINS=http://localhost:3000
ADMIN_API_TOKEN=
MARKET_DATA_PROVIDER=none
MAX_FILING_SUMMARIES_PER_DAY=3
MAX_NEWS_SUMMARIES_PER_DAY=7
MAX_OVERRIDE_SUMMARIES_PER_DAY=2
MAX_FILING_SUMMARIES_PER_RUN=2
MAX_NEWS_SUMMARIES_PER_RUN=4
COMPANY_IR_TOP_COMPANY_LIMIT=25
CATALYST_LOOKAHEAD_DAYS=180
RECENT_CATALYST_DAYS=90
```

## Notes

- `6-K` items are admitted only when heuristics indicate a periodic-results equivalent.
- Material `8-K` items are now ingested for results, financings, leadership changes, strategic transactions, and other high-signal event categories.
- If OpenAI credentials are missing, the app falls back to deterministic local summaries for development and tests.
- `MARKET_DATA_PROVIDER=fmp` is the recommended production default. `alpha_vantage` and `none` remain available for migration or low-cost fallback modes.
- `FMP_API_KEY` powers the batched market-cap refresh flow. `ALPHA_VANTAGE_API_KEY` is optional and only used if `MARKET_DATA_PROVIDER=alpha_vantage`.
- Historical backfills now queue summaries instead of immediately calling OpenAI. Automated summarization is budget-limited, watchlist-aware, and uses a small daily override pool for especially important items.
- `python -m app.jobs summarize-pending filing --limit 5 --include-historical` is the manual escape hatch when you want to spend budget on backlog items.
- Official company press release feeds are supported through a mix of starter built-in mappings and company overrides. Per-company overrides can use `Company.extra_metadata["ir_feed_url"]`, `["ir_news_page_url"]`, or a richer `["ir_sources"]` list when a company exposes an HTML investor-news page instead of RSS.
- The platform now tracks FDA advisory-calendar events as a dedicated official catalyst source, stores them separately from news, and surfaces them in dashboard, company, and watchlist timelines.
- Company pages and watchlist briefings now include structured catalyst cards built from official news, FDA calendar events, material event filings, and upcoming or recently updated ClinicalTrials.gov milestones.
- Private single-user deployments can request one-off summaries directly from filing and news views; those on-demand summaries consume the small override budget instead of opening the full backlog.
- Use `OBJECT_STORE_*` env vars for any S3-compatible provider. Legacy `S3_*` names are still accepted for backward compatibility.
- If object storage settings are absent, artifact storage falls back to the local filesystem.
- `OBJECT_STORE_REGION=auto` is the right default for Cloudflare R2.
- `CORS_ORIGINS` accepts a comma-separated list for split frontend/API deployments.
- `ADMIN_API_TOKEN` protects the `/admin/*` routes when set.
- `ENABLE_BROWSER_PDF_RENDERING=true` lets the backend use Playwright + Chromium to render SEC HTML filings directly to PDF. If browser rendering is unavailable, the app falls back to the internal text-based PDF generator.
- The UI now centers on three surfaces: a dashboard briefing, watchlist briefings, and company pages with merged filings/news/trials timelines.
