# Life Sciences Intelligence Platform

Private, single-user intelligence workspace for staying current on public life sciences companies without paying terminal-level costs.

The product is organized around two loops:

- Global awareness through a dashboard that separates `what changed today` from `what matters this week`
- Focused follow-up through watchlists and company pages

The app combines SEC filings, public industry news, official company IR updates, FDA advisory-calendar events, and AACT-backed ClinicalTrials.gov data into one ranked workflow with lightweight AI summaries and strict cost controls.

## What The Product Does

### Core surfaces

- `Dashboard`
  - latest filings and news from the last 24 hours
  - most important filings and news for the current week window
  - watchlist highlights
  - upcoming FDA regulatory events
  - recent clinical-trial updates
  - latest weekly digest
  - AI budget and queue status
- `Watchlists`
  - starter presets: `Large-cap pharma`, `Smid-cap biotech`, and `My tracked names`
  - grouped filings, news, trials, catalysts, and a merged timeline
- `Companies`
  - at-a-glance company snapshot
  - grouped filings by form type
  - recent news
  - catalyst summary
  - merged filing/news/trial/regulatory timeline
  - pipeline grouped from AACT-backed ClinicalTrials.gov data
- `Filings`
  - searchable filings archive with freshness and importance sorting
- `News`
  - ranked news archive with source, freshness, and personal relevance filters
- `Trials`
  - current and recent clinical-trial archive linked to covered companies
- `Digests`
  - weekly in-app briefings assembled from stored items and summaries

### Covered data

- SEC issuer universe filtered to core life sciences SIC codes
- Periodic and periodic-equivalent filings:
  - `10-K`, `10-Q`, `20-F`, `40-F`
  - qualifying `6-K` / `6-K/A`
  - material `8-K` / `8-K/A` event categories such as earnings, financings, leadership changes, strategic transactions, partnerships, and regulatory outcomes
- News and regulator feeds:
  - Fierce Pharma
  - Fierce Biotech
  - FDA Press Releases
  - FDA Drug Approvals
  - STAT News
  - Endpoints News
  - BioPharma Dive
  - GEN News
- Official company IR / press-release sources
  - starter built-in support for selected large-cap names
  - per-company overrides via `extra_metadata["ir_feed_url"]`, `extra_metadata["ir_news_page_url"]`, or `extra_metadata["ir_sources"]`
- FDA advisory-calendar events as a dedicated structured source
- AACT cloud database as the primary ClinicalTrials.gov mirror for production trial sync
- optional direct ClinicalTrials.gov v2 API fallback for manual/debug use

## How The Pipeline Works

The repo is intentionally optimized for low recurring cost.

### Tier 1: cheap ingest

- SEC metadata and filing documents
- article bodies and feed metadata
- regulatory calendar metadata
- clinical trial records from the configured trial provider
- company tagging and raw artifacts

### Tier 2: cheap enrichment

- topic tags
- source type and event type
- priority reasons
- filing diffs and extracted facts
- catalyst generation
- dedupe groups

### Tier 3: LLM enrichment

Only selected fresh, high-priority items are summarized automatically.

Default daily AI budget:

- `3` filing summaries/day
- `7` news summaries/day
- `2` override summaries/day for manual or high-signal requests

Important cost-control behavior:

- historical backfills do not auto-summarize everything they ingest
- new filings and news enter a pending queue first
- automated jobs summarize only the top-ranked pending items within per-run and per-day limits
- manual summarize actions from filing/news detail pages consume the override budget instead of opening the whole backlog

### Summary tiers

- `no_ai`
  - rule-based fallback summary, extracted facts, and priority reason only
- `short_ai`
  - shorter AI summary for medium-priority items
- `full_ai`
  - full structured summary for top items and digest inputs

## Ranking And Explainability

The app uses separate ranking modes depending on the surface:

- `importance`
  - global dashboard panels and digests
- `freshness`
  - newest activity views
- `personal`
  - watchlist- and company-relevant surfaces

Most list/detail payloads now include lightweight explanation metadata such as:

- `source_type`
- `event_type`
- `priority_reason`
- `summary_tier`
- `is_official_source`
- `dedupe_group_id`
- `freshness_bucket`
- `score_explanation`

This lets the UI explain why something is showing up without spending extra AI calls.

## Architecture

### Recommended production deployment

The repo is now optimized for a low-maintenance side-project deployment:

- Frontend: Vercel
- Backend API: Render web service
- Database: Render Postgres
- Object storage: Cloudflare R2
- Scheduler: embedded inside the single backend API instance

You do not need Redis, Dramatiq workers, or a separate scheduler service for the recommended deployment.

### Optional full local stack

`docker-compose.yml` still provisions a fuller local environment with:

- Postgres
- Redis
- MinIO
- API
- Dramatiq worker
- separate scheduler process
- web frontend

That setup is useful for local experimentation and future scale-out, but it is not the recommended production path.

## Repo Layout

- `backend/`
  - FastAPI application
  - ingestion, ranking, summary, and storage services
  - CLI jobs and bootstrap entrypoints
  - tests
- `web/`
  - Next.js application
  - dashboard, watchlists, company, filings, news, trials, and digest routes
- `docs/deployment.md`
  - step-by-step production deployment guide
- `docker-compose.yml`
  - optional local full-stack environment
- `render.yaml`
  - Render Blueprint for the recommended backend deployment

## Quick Start

### Option A: local development with Docker Compose

1. Copy the example env file:

```bash
cp .env.example .env
```

2. Set at least:

- `SEC_USER_AGENT`
- `OPENAI_API_KEY` if you want live OpenAI summaries
- `MARKET_DATA_PROVIDER`
- `FMP_API_KEY` if using FMP market caps

3. Start the stack:

```bash
docker compose up --build
```

4. Open:

- web: [http://localhost:3000](http://localhost:3000)
- API docs: [http://localhost:8000/docs](http://localhost:8000/docs)
- health: [http://localhost:8000/health](http://localhost:8000/health)
- MinIO console: [http://localhost:9001](http://localhost:9001)

Notes:

- The local backend Docker image does not install Chromium by default.
- If browser-based HTML-to-PDF rendering is unavailable, the backend falls back to its internal text-based PDF generator.
- The Docker Compose setup includes Redis and Dramatiq even though the recommended production deployment does not require them.

### Option B: local development without Docker

Backend:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m playwright install chromium
uvicorn app.main:app --reload
```

Frontend:

```bash
cd web
npm install
npm run dev
```

One-command starter seed:

```bash
cd backend
python -m app.bootstrap --sync-limit 250 --backfill-companies 10
```

This path works with SQLite and filesystem artifacts if Postgres or object storage are unavailable.

## Bootstrap And Maintenance Commands

### First-time local seed

Use `app.bootstrap` when you want one opinionated setup flow:

```bash
cd backend
python -m app.bootstrap --sync-limit 250 --backfill-companies 10
```

Helpful flags:

- `--sync-progress-every 25`
- `--focus-tickers PFE,MRK,AMGN`
- `--years-back 3`
- `--skip-news`
- `--skip-digest`

### Ongoing maintenance

Use `app.jobs` for targeted operational tasks:

```bash
cd backend
python -m app.jobs sync-universe --limit 1000 --progress-every 50
python -m app.jobs refresh-market-caps --all --progress-every 50
python -m app.jobs poll-sec-filings
python -m app.jobs ingest-news
python -m app.jobs poll-regulatory-events
python -m app.jobs poll-trials
python -m app.jobs poll-trials --focus-tickers MRK,PFE
python -m app.jobs build-daily-digest
python -m app.jobs build-weekly-digest
```

Additional high-value commands:

```bash
cd backend
python -m app.jobs backfill-top-companies --count 25 --years-back 3
python -m app.jobs summarize-pending filing --limit 5 --include-historical
python -m app.jobs summarize-pending news --limit 10
python -m app.jobs retag-news-companies --all
python -m app.jobs reprocess-filing 123
python -m app.jobs reprocess-company-filings 45 --limit 25
python -m app.jobs refresh-all-data --sync-limit 5000 --company-count 250 --years-back 3 --skip-news --skip-digest
```

Key behavior to know:

- `sync-universe` only refreshes the covered company universe
- `refresh-market-caps` is now separate and reranks dependent filings/news
- `poll-sec-filings` discovers only new filings and summarizes only within budget
- `ingest-news` ingests only new stories and summarizes only within budget
- `poll-regulatory-events` syncs FDA advisory-calendar events
- `poll-trials` syncs current and recent trials through the configured provider, with `aact_cloud` as the intended production default

## Current Scheduler Behavior

When `ENABLE_SCHEDULER=true`, the backend API process starts an embedded APScheduler instance.

Scheduled jobs:

- SEC filing polling every 30 minutes
- news ingestion every 6 hours
- FDA regulatory-event polling every 12 hours
- trial polling every 7 days through the configured provider
- universe sync every 7 days
- market-cap refresh every 7 days
- weekly digest build on the configured weekday/time

Important operational note:

- Keep the API at a single instance in the recommended deployment, or you will run duplicate scheduled jobs.

## Configuration

### Required backend env vars for real production use

- `DATABASE_URL`
- `SEC_USER_AGENT`
- `OPENAI_API_KEY`
- `MARKET_DATA_PROVIDER`
- `FMP_API_KEY` when `MARKET_DATA_PROVIDER=fmp`
- `CLINICAL_TRIALS_PROVIDER`
- `AACT_DB_USER` and `AACT_DB_PASSWORD` when `CLINICAL_TRIALS_PROVIDER=aact_cloud`
- `OBJECT_STORE_ENDPOINT_URL`
- `OBJECT_STORE_ACCESS_KEY_ID`
- `OBJECT_STORE_SECRET_ACCESS_KEY`
- `OBJECT_STORE_BUCKET`
- `FRONTEND_BASE_URL`
- `API_BASE_URL`
- `CORS_ORIGINS`

### Recommended backend env vars

- `ADMIN_API_TOKEN`
- `ENABLE_SCHEDULER=true`
- `ENABLE_BROWSER_PDF_RENDERING=true`
- `OBJECT_STORE_REGION=auto` for Cloudflare R2
- `OPENAI_MODEL=gpt-5.4-mini`
- `OPENAI_MODEL_SUMMARY_SHORT=gpt-5.4-mini`
- `OPENAI_MODEL_SUMMARY_FULL=gpt-5.4`
- `OPENAI_MODEL_DIFF=gpt-5.4`
- `OPENAI_MODEL_DIGEST=gpt-5.4`
- `OPENAI_MODEL_MANUAL=gpt-5.4`
- `CLINICAL_TRIALS_PROVIDER=aact_cloud`
- `AACT_DB_HOST=aact-db.ctti-clinicaltrials.org`
- `AACT_DB_PORT=5432`
- `AACT_DB_NAME=aact`

### Cost-control env vars

- `DAILY_AI_BUDGET_USD`
- `AI_BUDGET_NEWS_SHARE`
- `AI_BUDGET_FILING_SHARE`
- `AI_BUDGET_DIFF_SHARE`
- `AI_BUDGET_OVERRIDE_SHARE`
- `AI_BUDGET_DIGEST_SHARE`
- `MAX_FILING_SUMMARIES_PER_DAY`
- `MAX_NEWS_SUMMARIES_PER_DAY`
- `MAX_OVERRIDE_SUMMARIES_PER_DAY`
- `MAX_FILING_SUMMARIES_PER_RUN`
- `MAX_NEWS_SUMMARIES_PER_RUN`
- `MAX_FILING_FULL_AI_PER_DAY`
- `MAX_FILING_SHORT_AI_PER_DAY`
- `MAX_NEWS_FULL_AI_PER_DAY`
- `MAX_NEWS_SHORT_AI_PER_DAY`
- `MAX_FILING_DIFFS_PER_DAY`
- `MAX_DIGEST_GENERATIONS_PER_DAY`
- `FILING_SUMMARY_BACKLOG_DAYS`
- `NEWS_SUMMARY_BACKLOG_DAYS`
- `COMPANY_IR_TOP_COMPANY_LIMIT`
- `CATALYST_LOOKAHEAD_DAYS`
- `RECENT_CATALYST_DAYS`

### Advanced / optional backend env vars

- `OPENAI_API_BASE`
- `FMP_BASE_URL`
- `ALPHA_VANTAGE_API_KEY`
- `ALPHA_VANTAGE_BASE_URL`
- `AACT_DB_HOST`
- `AACT_DB_PORT`
- `AACT_DB_NAME`
- `CLINICAL_TRIALS_RECENT_DAYS`
- `REDIS_URL`
- `LOCAL_ARTIFACT_DIR`
- `BROWSER_PDF_TIMEOUT_SECONDS`
- `TIMEZONE`
- `DIGEST_WEEKDAY`
- `DIGEST_HOUR`
- `DIGEST_MINUTE`
- `ENABLE_DAILY_DIGEST`
- `DAILY_DIGEST_HOUR`
- `SEC_RATE_LIMIT_DELAY_SECONDS`
- `SOURCE_FETCH_TIMEOUT_SECONDS`
- `SUMMARY_PROMPT_VERSION`

### Frontend env vars

The frontend only needs:

- `NEXT_PUBLIC_API_BASE_URL`

## Health, Admin, And Diagnostics

### Health endpoint

`/health` returns:

- `status`
- `ready`
- `db_ready`
- `scheduler_enabled`
- `startup_error`

This is the right place to diagnose Render cold starts and background runtime issues.

### Admin routes

If `ADMIN_API_TOKEN` is set, `/admin/*` routes require either:

- `X-Admin-Token: <token>`
- `Authorization: Bearer <token>`

Useful admin endpoints include:

- `/api/v1/admin/sync-universe`
- `/api/v1/admin/refresh-market-caps`
- `/api/v1/admin/poll-filings`
- `/api/v1/admin/ingest-news`
- `/api/v1/admin/poll-regulatory-events`
- `/api/v1/admin/retag-news-companies`
- `/api/v1/admin/summarize-pending/{kind}`
- `/api/v1/admin/build-daily-digest`
- `/api/v1/admin/build-weekly-digest`
- `/api/v1/admin/poll-trials`
- `/api/v1/admin/usage-stats`

## Key Notes And Caveats

- `OBJECT_STORE_*` is the preferred storage naming. Legacy `S3_*` env names are still accepted.
- If object storage is not configured, artifacts fall back to the local filesystem.
- If `OPENAI_API_KEY` is missing, the backend falls back to deterministic local summaries.
- `MARKET_DATA_PROVIDER=fmp` is the intended production default.
- `CLINICAL_TRIALS_PROVIDER=aact_cloud` is the intended production default for trials.
- If AACT credentials are missing, trial sync skips cleanly and leaves existing trial rows untouched.
- Market-data failures do not block SEC or news ingestion.
- Historical backfills queue summaries rather than spending AI immediately.
- Company pages and watchlist briefings now use explicit company tagging for news instead of loose string matching.
- FDA advisory-calendar events are a dedicated official source and are not just news articles.
- Official company IR sources support both RSS feeds and HTML investor-news pages.
- The filings archive exists at `/filings` even though the main sidebar emphasizes dashboard, watchlists, companies, news, trials, and digests.

## Deployment

For the recommended cheap, low-maintenance production stack, see [docs/deployment.md](docs/deployment.md).
