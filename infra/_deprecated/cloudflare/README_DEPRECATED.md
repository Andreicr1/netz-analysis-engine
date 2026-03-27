# Deprecated — Cloudflare Cron + Container Workers

**Deprecated on:** 2026-03-26
**Replaced by:** Railway Cron Jobs (`railway.toml` at repo root)

## What this was

- `cron/` — Cloudflare Scheduled Worker (`netz-cron`) that dispatched background workers
  via `POST /internal/workers/dispatch` with `X-Worker-Secret` header.
- `workers/` — Cloudflare Container (`netz-workers`) running the same FastAPI image with
  scale-to-zero (30min idle). `WORKERS_ORIGIN` pointed to
  `https://netz-workers.andrei-rachadel.workers.dev`.
- `gateway/` — Cloudflare Worker acting as API gateway, blocking `/internal/*` without secret.

## Why deprecated

Backend migrated to Railway Pro, co-located with Timescale Cloud. The Cloudflare hop
(CF Cron -> CF Container -> Railway) added unnecessary latency and complexity.
Railway Cron Jobs invoke workers directly via `python -m app.workers.cli <name>` —
no HTTP overhead, no WORKER_DISPATCH_SECRET needed for scheduled runs.

## Can I delete this?

Yes, after confirming Railway Cron Jobs are running successfully in production.
Kept for historical reference and rollback safety.
