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

1. Copy `.env.example` to `.env` and set `SEC_USER_AGENT`, `OPENAI_API_KEY`, and `ALPHA_VANTAGE_API_KEY`.
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
- `backfill_company` loads historical target filings for one company
- `poll_sec_filings` finds newly filed periodic reports
- `ingest_news` pulls RSS/news sources and summarizes new stories
- `build_weekly_digest` creates the Monday 8:00 AM ET digest
- `python -m app.jobs ...` runs these tasks directly for deployment or maintenance

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
```

## Notes

- `6-K` items are admitted only when heuristics indicate a periodic-results equivalent.
- If OpenAI credentials are missing, the app falls back to deterministic local summaries for development and tests.
- Use `OBJECT_STORE_*` env vars for any S3-compatible provider. Legacy `S3_*` names are still accepted for backward compatibility.
- If object storage settings are absent, artifact storage falls back to the local filesystem.
- `OBJECT_STORE_REGION=auto` is the right default for Cloudflare R2.
- `CORS_ORIGINS` accepts a comma-separated list for split frontend/API deployments.
- `ADMIN_API_TOKEN` protects the `/admin/*` routes when set.
