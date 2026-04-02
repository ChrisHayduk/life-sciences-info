# Deployment Guide

This guide describes the current recommended deployment for the repository as it exists today.

## Recommended Stack

For a low-cost, low-maintenance single-user deployment:

- Frontend: Vercel
- Backend API + embedded scheduler: Render web service
- Database: Render Postgres
- Object storage: Cloudflare R2

This is the default operating model the repo now optimizes for.

## Why This Is The Recommended Path

- The backend scheduler is embedded in the API process, so you do not need separate cron or worker infrastructure for the default setup.
- Render is simple for a single Python API plus Postgres.
- Vercel is the easiest place to host the existing Next.js frontend.
- Cloudflare R2 gives you inexpensive S3-compatible storage for filing artifacts and PDFs.
- The app is already budget-limited around AI usage, so the remaining ongoing costs are mostly hosting and storage.

## What This Deployment Includes

- 1 Vercel project for `web/`
- 1 Render web service for `backend/`
- 1 Render Postgres instance
- 1 R2 bucket

## What This Deployment Does Not Need

For the default side-project setup, you do not need:

- a separate Dramatiq worker
- Redis
- a separate scheduler service
- a separate cron job service

Those pieces still exist in the repo and in `docker-compose.yml`, but they are optional and not part of the recommended production footprint.

## Before You Start

You should already have:

- an OpenAI API key
- an FMP API key if using live market caps
- AACT cloud database credentials for production clinical-trial syncing
- a Render account
- a Vercel account
- a Cloudflare account with R2 enabled

You should also decide what your SEC contact string will be. Example:

```env
SEC_USER_AGENT=LifeSciencesIntel/1.0 (you@yourdomain.com)
```

## Step 1: Create The R2 Bucket

Create one R2 bucket for filing PDFs and artifacts.

You will need:

- `OBJECT_STORE_ENDPOINT_URL`
- `OBJECT_STORE_ACCESS_KEY_ID`
- `OBJECT_STORE_SECRET_ACCESS_KEY`
- `OBJECT_STORE_BUCKET`
- `OBJECT_STORE_REGION=auto`

For Cloudflare R2:

- use the account-level S3 endpoint, not the bucket URL with the bucket name appended
- keep bucket public access disabled
- you do not need browser CORS on the bucket for the current app design

## Step 2: Create Render Postgres

Create a Postgres instance in the same region as the API service.

Recommended settings:

- Name: `life-sciences-intel-db`
- Region: same as the backend service
- Plan: `Basic-256mb` for the cheapest production starting point
- Postgres major version: `16`

After it is created, copy the internal connection string and use it as `DATABASE_URL` on the backend service.

## Step 3: Deploy The Backend On Render

### Preferred setup

Use the Blueprint in [render.yaml](../render.yaml).

Current Blueprint behavior:

- runtime: Python
- root directory: `backend`
- plan: `starter`
- build command:

```bash
pip install -e . && python -m playwright install chromium
```

- start command:

```bash
uvicorn app.main:app --host 0.0.0.0 --port $PORT
```

- health check path:

```text
/health
```

### Important deployment note

Keep the Render API service at a single instance in the recommended deployment.

Why:

- the scheduler runs inside the API process when `ENABLE_SCHEDULER=true`
- if you scale horizontally, each instance will start its own scheduler and duplicate jobs

### Required backend env vars

Set these on the Render API service:

#### Core runtime

- `DATABASE_URL`
- `SEC_USER_AGENT`
- `API_BASE_URL`
- `FRONTEND_BASE_URL`
- `CORS_ORIGINS`

Typical values:

- `API_BASE_URL=https://your-render-api-domain`
- `FRONTEND_BASE_URL=https://your-vercel-domain`
- `CORS_ORIGINS=https://your-vercel-domain`

#### OpenAI

- `OPENAI_API_KEY`
- `OPENAI_MODEL`
- `OPENAI_MODEL_SUMMARY_SHORT`
- `OPENAI_MODEL_SUMMARY_FULL`
- `OPENAI_MODEL_DIFF`
- `OPENAI_MODEL_DIGEST`
- `OPENAI_MODEL_MANUAL`
- `OPENAI_API_BASE`

Recommended defaults:

- `OPENAI_MODEL=gpt-5.4-mini`
- `OPENAI_MODEL_SUMMARY_SHORT=gpt-5.4-mini`
- `OPENAI_MODEL_SUMMARY_FULL=gpt-5.4`
- `OPENAI_MODEL_DIFF=gpt-5.4`
- `OPENAI_MODEL_DIGEST=gpt-5.4`
- `OPENAI_MODEL_MANUAL=gpt-5.4`
- `OPENAI_API_BASE=https://api.openai.com/v1`

#### Market data

- `MARKET_DATA_PROVIDER`
- `FMP_API_KEY`
- `FMP_BASE_URL`

Recommended defaults:

- `MARKET_DATA_PROVIDER=fmp`
- `FMP_BASE_URL=https://financialmodelingprep.com/stable`

Optional compatibility fallback:

- `ALPHA_VANTAGE_API_KEY`
- `ALPHA_VANTAGE_BASE_URL`

#### Clinical trials

- `CLINICAL_TRIALS_PROVIDER`
- `AACT_DB_HOST`
- `AACT_DB_PORT`
- `AACT_DB_NAME`
- `AACT_DB_USER`
- `AACT_DB_PASSWORD`
- `CLINICAL_TRIALS_RECENT_DAYS`

Recommended defaults:

- `CLINICAL_TRIALS_PROVIDER=aact_cloud`
- `AACT_DB_HOST=aact-db.ctti-clinicaltrials.org`
- `AACT_DB_PORT=5432`
- `AACT_DB_NAME=aact`
- `CLINICAL_TRIALS_RECENT_DAYS=730`

Legacy/manual fallback:

- `CLINICAL_TRIALS_PROVIDER=ctgov_api`

Production note:

- The app is now designed to use the AACT cloud database as the primary trial source on Render.
- Direct ClinicalTrials.gov API polling remains available as a fallback/debug path, but it is not the recommended production mode.

#### Object storage

- `OBJECT_STORE_ENDPOINT_URL`
- `OBJECT_STORE_ACCESS_KEY_ID`
- `OBJECT_STORE_SECRET_ACCESS_KEY`
- `OBJECT_STORE_BUCKET`
- `OBJECT_STORE_REGION`

Recommended R2 default:

- `OBJECT_STORE_REGION=auto`

#### Security / admin

- `ADMIN_API_TOKEN`

#### Scheduler and PDF rendering

- `ENABLE_SCHEDULER=true`
- `ENABLE_BROWSER_PDF_RENDERING=true`
- `BROWSER_PDF_TIMEOUT_SECONDS=45`

#### Daily digest email delivery

- `DIGEST_EMAIL_ENABLED=false`
- `DIGEST_EMAIL_TO=chris.hayduk1@gmail.com`
- `DIGEST_EMAIL_FROM=chris.hayduk1@gmail.com`
- `SMTP_HOST=smtp.gmail.com`
- `SMTP_PORT=587`
- `SMTP_USERNAME=chris.hayduk1@gmail.com`
- `SMTP_PASSWORD`
- `SMTP_USE_STARTTLS=true`

Production note:

- The daily digest still builds when email delivery is disabled or incomplete.
- Once SMTP is configured and `DIGEST_EMAIL_ENABLED=true`, the weekday daily digest job builds or reuses the digest and emails it to `DIGEST_EMAIL_TO`.

#### AI budget and prioritization

- `DAILY_AI_BUDGET_USD=1.00`
- `AI_BUDGET_NEWS_SHARE=0.45`
- `AI_BUDGET_FILING_SHARE=0.25`
- `AI_BUDGET_DIFF_SHARE=0.10`
- `AI_BUDGET_OVERRIDE_SHARE=0.10`
- `AI_BUDGET_DIGEST_SHARE=0.10`
- `MAX_FILING_SUMMARIES_PER_DAY=16`
- `MAX_NEWS_SUMMARIES_PER_DAY=38`
- `MAX_OVERRIDE_SUMMARIES_PER_DAY=8`
- `MAX_FILING_SUMMARIES_PER_RUN=3`
- `MAX_NEWS_SUMMARIES_PER_RUN=8`
- `MAX_FILING_FULL_AI_PER_DAY=4`
- `MAX_FILING_SHORT_AI_PER_DAY=12`
- `MAX_NEWS_FULL_AI_PER_DAY=8`
- `MAX_NEWS_SHORT_AI_PER_DAY=30`
- `MAX_FILING_DIFFS_PER_DAY=8`
- `MAX_DIGEST_GENERATIONS_PER_DAY=2`
- `FILING_SUMMARY_BACKLOG_DAYS=21`
- `NEWS_SUMMARY_BACKLOG_DAYS=5`
- `COMPANY_IR_TOP_COMPANY_LIMIT=50`
- `CATALYST_LOOKAHEAD_DAYS=180`
- `RECENT_CATALYST_DAYS=90`

#### Digest schedule and general runtime defaults

- `TIMEZONE=America/New_York`
- `DIGEST_WEEKDAY=mon`
- `DIGEST_HOUR=8`
- `DIGEST_MINUTE=0`
- `ENABLE_DAILY_DIGEST=true`
- `DAILY_DIGEST_HOUR=7`
- `SEC_RATE_LIMIT_DELAY_SECONDS=0.2`
- `SOURCE_FETCH_TIMEOUT_SECONDS=30`
- `SUMMARY_PROMPT_VERSION=2026-03-28.v2`

### Notes on startup and health

The backend now initializes DB setup and scheduler startup in a background thread so Render can detect the port quickly.

`/health` returns:

- `status`
- `ready`
- `db_ready`
- `scheduler_enabled`
- `startup_error`

If Render shows the service as up but something still looks wrong, check `/health` first.

## Step 4: Deploy The Frontend On Vercel

Create a Vercel project using `web/` as the root directory.

Set this frontend env var:

```env
NEXT_PUBLIC_API_BASE_URL=https://your-render-api-domain/api/v1
```

That is the only required frontend env var today.

After Vercel gives you the public frontend URL, update the backend service:

- `FRONTEND_BASE_URL=https://your-frontend-domain`
- `CORS_ORIGINS=https://your-frontend-domain`

If you later add a custom domain, update:

- `NEXT_PUBLIC_API_BASE_URL`
- `FRONTEND_BASE_URL`
- `CORS_ORIGINS`

## Step 5: Seed The Initial Data

The scheduler keeps data current, but it does not perform the initial historical backfill for you.

You should run one manual seed after deployment.

### Fast starter seed

Use `app.bootstrap` for the simplest first pass:

```bash
cd /opt/render/project/src/backend
python -m app.bootstrap --sync-limit 300 --backfill-companies 25 --max-filings-per-company 8
```

### Focused starter seed

Useful when you want the first experience to be populated with major names only:

```bash
cd /opt/render/project/src/backend
python -m app.bootstrap \
  --focus-tickers PFE,MRK,AMGN,GILD,VRTX,REGN,ABT,MDT,ISRG,DHR \
  --sync-limit 100 \
  --backfill-companies 10 \
  --max-filings-per-company 8
```

### Three-year historical seed

```bash
cd /opt/render/project/src/backend
python -m app.bootstrap --sync-limit 1000 --sync-progress-every 25 --backfill-companies 100 --years-back 3 --skip-digest
```

Important:

- historical backfills do not automatically summarize every filing
- that behavior is intentional and keeps OpenAI spend low

## Step 6: Protect The Admin Surface

If `ADMIN_API_TOKEN` is set, all `/admin/*` routes require it.

Supported auth forms:

- `X-Admin-Token: <token>`
- `Authorization: Bearer <token>`

Example:

```bash
curl -X POST "https://your-api-domain/api/v1/admin/ingest-news" \
  -H "X-Admin-Token: $ADMIN_API_TOKEN"
```

## Scheduled Jobs In Production

When `ENABLE_SCHEDULER=true`, the Render API service automatically runs:

- `poll-sec-filings` every 30 minutes
- `ingest-news` every 6 hours
- `poll-regulatory-events` every 12 hours
- `poll-trials` every 7 days
- `sync-universe` every 7 days
- `refresh-market-caps` every 7 days
- `send-daily-digest-email` on weekdays at `DAILY_DIGEST_HOUR` when `ENABLE_DAILY_DIGEST=true`
- `build-weekly-digest` on the configured weekday/time

Two important notes:

- market-cap refresh is separate from universe sync
- trial polling is now part of the default weekly schedule

## Current Data Source Behavior In Production

### Filings

The ingestion pipeline currently covers:

- `10-K`, `10-Q`, `20-F`, `40-F`
- periodic-equivalent `6-K`
- material `8-K` event categories that matter for life sciences monitoring

### News

The news layer ingests:

- public trade press feeds
- FDA feeds
- official company IR / press-release sources

IR source handling supports:

- direct RSS
- HTML investor-news pages
- per-company overrides through `extra_metadata["ir_feed_url"]`
- per-company overrides through `extra_metadata["ir_news_page_url"]`
- richer multi-source overrides through `extra_metadata["ir_sources"]`

### Regulatory events

The app separately stores FDA advisory-calendar events instead of relying on news coverage alone.

These events show up in:

- the dashboard
- company timelines
- watchlist timelines
- catalyst panels

### Trials

Trial data is intended to come from the AACT cloud database, which mirrors ClinicalTrials.gov in a database-friendly form.

The production sync:

- queries AACT directly per company
- matches against canonical names, aliases, and optional `extra_metadata["trial_sponsor_aliases"]`
- keeps only current and recent studies in the primary app table
- skips cleanly without deleting existing rows if the provider is misconfigured or a company-level sync fails

The direct ClinicalTrials.gov API remains available as `CLINICAL_TRIALS_PROVIDER=ctgov_api` for fallback/debug use, but it is not the recommended production path on Render.

## Manual Operations You Will Actually Use

All commands below assume:

```bash
cd /opt/render/project/src/backend
```

### Universe and market caps

```bash
python -m app.jobs sync-universe --limit 1000 --progress-every 50
python -m app.jobs refresh-market-caps --all --progress-every 50
```

Use `sync-universe` when you want to refresh the covered company set.

Use `refresh-market-caps` when you want to update market caps and rerank filings/news without touching raw documents.

### Filing backfills and refreshes

```bash
python -m app.jobs backfill-top-companies --count 25 --years-back 3
python -m app.jobs backfill-company 123 --years-back 3
python -m app.jobs refresh-all-data --sync-limit 5000 --company-count 250 --years-back 3 --skip-news --skip-digest
python -m app.jobs reprocess-filing 456
python -m app.jobs reprocess-company-filings 123 --limit 25
```

Use `refresh-all-data` when you want an in-place overwrite of stored filings, parsed text, market-cap ranking, and PDFs.

### News and tagging

```bash
python -m app.jobs ingest-news
python -m app.jobs retag-news-companies --all
```

`retag-news-companies` is the maintenance path for normalizing company links on stored news items and reranking them.

### Regulatory events and trials

```bash
python -m app.jobs poll-regulatory-events
python -m app.jobs poll-trials
python -m app.jobs poll-trials --focus-tickers MRK,PFE
```

### Budget-aware backlog work

```bash
python -m app.jobs summarize-pending filing --limit 5 --include-historical
python -m app.jobs summarize-pending news --limit 10
```

This is the manual escape hatch when you want to spend a little AI budget on the pending queue after a historical backfill.

### Daily and weekly digests

```bash
python -m app.jobs build-daily-digest
python -m app.jobs send-daily-digest-email
python -m app.jobs send-daily-digest-email --force
python -m app.jobs build-weekly-digest
```

## Recommended Operational Workflow

### Initial launch

1. Deploy backend, Postgres, R2, and frontend.
2. Confirm `/health` returns `ready=true` and no `startup_error`.
3. Run a focused or moderate bootstrap.
4. Optionally create the starter watchlists from the UI or `POST /api/v1/watchlists/starter`.
5. Let the scheduler take over.

### Ongoing use

In normal operation, you should rarely need more than:

- automatic scheduler runs
- occasional `refresh-market-caps --all`
- occasional `retag-news-companies --all`
- a targeted `backfill-company` when you add or care about a specific name
- occasional manual summaries for queued items you decide to read

## Cost And Reliability Guidance

### Keep costs low

- leave the default summary budgets in place unless you have a clear reason to raise them
- prefer targeted backfills over full-universe refreshes
- use `refresh-market-caps` instead of `refresh-all-data` when you only need reranking
- avoid bulk `resummarize` unless prompt versions or parsing logic truly changed

### Keep the deployment stable

- keep the Render API on one instance
- use Chromium-enabled builds for best PDF fidelity
- use focused or batched refreshes if your instance is memory-constrained
- the Blueprint starts on Render `starter`; for large `refresh-all-data` runs or mass PDF rerenders, a temporary upgrade to a higher-memory plan can be worth it

### Understand local vs production PDF behavior

- Render Blueprint installs Chromium during build
- the local backend Docker image does not
- if browser rendering is unavailable, the app falls back to internal PDF generation

## Troubleshooting

### The service deploys but looks half-ready

Check:

- `GET /health`

Look for:

- `ready`
- `db_ready`
- `startup_error`

### Market caps are missing

Run:

```bash
cd /opt/render/project/src/backend
python -m app.jobs refresh-market-caps --all --progress-every 50
```

If the provider is failing, market-data errors will no longer block SEC or news ingestion.

### PDFs look wrong

Confirm:

- `ENABLE_BROWSER_PDF_RENDERING=true`
- Chromium was installed during build

Then rerun:

```bash
cd /opt/render/project/src/backend
python -m app.jobs reprocess-filing <filing_id>
```

### AI usage seems too high

Check:

- automated budgets
- whether a bulk refresh or resummarize job was run manually
- `/api/v1/admin/usage-stats`

Historical backfills alone should not automatically summarize everything.

## Local Full-Stack Alternative

If you want a fuller local environment for development or debugging, use:

```bash
docker compose up --build
```

That local stack includes:

- Postgres
- Redis
- MinIO
- API
- worker
- scheduler
- web

This is useful for development, but it is intentionally more complex than the recommended production deployment.
