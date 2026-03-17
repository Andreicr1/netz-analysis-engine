---
status: complete
priority: p2
issue_id: "158"
tags: [code-review, performance, admin]
---

# SSE worker log stream has no max connection limit

## Problem Statement
`/admin/health/workers/logs` SSE endpoint creates one Redis pubsub per client with no concurrency limit. 100 open tabs = 100 Redis connections.

## Findings
- `backend/app/domains/admin/routes/health.py`: `stream_worker_logs` has no semaphore
- Plan specified max 10 concurrent SSE connections with 429 if exceeded

## Proposed Solution
Add lazy `asyncio.Semaphore(10)` guard per CLAUDE.md rules (no module-level asyncio primitives).
