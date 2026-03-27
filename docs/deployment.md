# Deployment Guide

## Recommended Stack

This repository is prepared for a low-maintenance deployment built around:

- Vercel for the `web/` Next.js frontend
- Render for the `backend/` FastAPI API and managed Postgres
- Cloudflare R2 for filing artifacts and generated PDFs

This keeps the always-on footprint small:

- one frontend service
- one backend service
- one Postgres database
- one object storage bucket

The backend scheduler runs inside the single Render API service, so you do not need a dedicated worker, Redis, or separate cron service for the default side-project deployment.

## Why This Stack

- Vercel is the easiest place to host the existing Next.js app.
- Render Blueprints give you one-click provisioning for the Python API and Postgres from [render.yaml](/Users/christopherhayduk/Desktop/life-sciences-info/render.yaml).
- Cloudflare R2 is S3-compatible and inexpensive for document storage.
- Embedded scheduling keeps the operational surface area small.

## Step 1: Create the R2 Bucket

Create one R2 bucket for artifacts and collect these values:

- `OBJECT_STORE_ENDPOINT_URL`
- `OBJECT_STORE_ACCESS_KEY_ID`
- `OBJECT_STORE_SECRET_ACCESS_KEY`
- `OBJECT_STORE_BUCKET`

For R2, set:

- `OBJECT_STORE_REGION=auto`

## Step 2: Deploy the Backend on Render

Use the Blueprint in [render.yaml](/Users/christopherhayduk/Desktop/life-sciences-info/render.yaml).

Set these required environment variables during Blueprint creation:

- `SEC_USER_AGENT`
- `OPENAI_API_KEY`
- `MARKET_DATA_PROVIDER`
- `FMP_API_KEY`
- `OBJECT_STORE_ENDPOINT_URL`
- `OBJECT_STORE_ACCESS_KEY_ID`
- `OBJECT_STORE_SECRET_ACCESS_KEY`
- `OBJECT_STORE_BUCKET`
- `FRONTEND_BASE_URL`
- `API_BASE_URL`
- `CORS_ORIGINS`
- `ADMIN_API_TOKEN`

Notes:

- `ENABLE_SCHEDULER` is already set to `true` in the Blueprint.
- `MARKET_DATA_PROVIDER=fmp` is the intended production default.
- `ENABLE_BROWSER_PDF_RENDERING` is already set to `true` in the Blueprint.
- The backend build now installs Chromium so HTML SEC filings can be rendered directly to PDF instead of going through the text fallback path.
- Keep the Render API service at a single instance so scheduled jobs do not run more than once.
- The backend health check path is `/health`.

## Step 3: Deploy the Frontend on Vercel

Create a Vercel project from this repository with the root directory set to `web`.

Set:

- `NEXT_PUBLIC_API_BASE_URL=https://your-render-api-domain/api/v1`

After Vercel gives you the frontend URL, update the backend service values:

- `FRONTEND_BASE_URL=https://your-vercel-domain`
- `CORS_ORIGINS=https://your-vercel-domain`

If you later add a custom domain, update all three values accordingly:

- `FRONTEND_BASE_URL`
- `CORS_ORIGINS`
- `NEXT_PUBLIC_API_BASE_URL`

## Step 4: Run the Initial Backfill

After the backend is live, open a Render shell for the API service and run:

```bash
cd /opt/render/project/src/backend
python -m app.bootstrap --sync-limit 300 --backfill-companies 25 --max-filings-per-company 8
```

For a lighter initial pass, use:

```bash
cd /opt/render/project/src/backend
python -m app.bootstrap --focus-tickers PFE,MRK,AMGN,GILD,VRTX,REGN,ABT,MDT,ISRG,DHR --sync-limit 100 --backfill-companies 10 --max-filings-per-company 8
```

## Step 5: Protect Admin Endpoints

Set `ADMIN_API_TOKEN` on the backend. All `/admin/*` routes now require it.

You can send it either as:

- `X-Admin-Token: <token>`
- `Authorization: Bearer <token>`

Example:

```bash
curl -X POST "https://your-render-api-domain/api/v1/admin/ingest-news" \
  -H "X-Admin-Token: $ADMIN_API_TOKEN"
```

## Ongoing Operations

The backend service will automatically:

- poll SEC filings every 30 minutes
- ingest news every 6 hours
- sync the issuer universe weekly
- refresh market caps weekly
- build the weekly digest every Monday at 8:00 AM America/New_York

Manual maintenance commands are available in [backend/app/jobs.py](/Users/christopherhayduk/Desktop/life-sciences-info/backend/app/jobs.py):

- `python -m app.jobs sync-universe`
- `python -m app.jobs refresh-market-caps --all`
- `python -m app.jobs poll-sec-filings`
- `python -m app.jobs ingest-news`
- `python -m app.jobs build-weekly-digest`
- `python -m app.jobs backfill-company <company_id> --max-filings 8`
- `python -m app.jobs resummarize filing <item_id>`
- `python -m app.jobs reprocess-filing <item_id>`
- `python -m app.jobs reprocess-company-filings <company_id> --limit 25`
- `python -m app.jobs refresh-all-data --sync-limit 5000 --company-count 250 --years-back 3`

If you need to overwrite older bad PDFs, parsed sections, and stale market caps in place, use:

```bash
cd /opt/render/project/src/backend
python -m app.jobs refresh-all-data --sync-limit 5000 --company-count 250 --years-back 3 --skip-news --skip-digest
```

If you only need to refresh company market caps without touching filings, use:

```bash
cd /opt/render/project/src/backend
python -m app.jobs refresh-market-caps --all --progress-every 50
```

Then optionally refresh news and rebuild the digest:

```bash
cd /opt/render/project/src/backend
python -m app.jobs ingest-news
python -m app.jobs build-weekly-digest
```

## What You Do Not Need For This Deployment

For the default side-project setup, you do not need:

- a separate Dramatiq worker
- Redis
- a separate scheduler service

Those pieces remain in the codebase for future scale-out, but the recommended deployment path avoids them to reduce cost and upkeep.
