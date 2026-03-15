---
status: pending
priority: p2
issue_id: "030"
tags: [code-review, security, tenant-isolation, pre-existing]
dependencies: []
---

## Problem Statement

PRE-EXISTING issue (documented as F1 in plan). The SSE endpoint `/jobs/{job_id}/stream` authenticates the caller but never verifies they own the job. Any authenticated tenant can subscribe to any job's Redis channel. The pipeline emits `doc_type`, classification confidence, and chunk counts via SSE, leaking potentially sensitive document metadata across tenants.

## Findings

- The SSE endpoint at `backend/app/main.py` lines 197-204 checks authentication but performs no authorization against the job's owning organization.
- Redis pub/sub channels are keyed by `job_id` alone, with no tenant namespace.
- Pipeline SSE events contain document metadata: document type classification, confidence scores, chunk counts, and processing stage details.
- Any authenticated user who guesses or enumerates a `job_id` (UUIDs, but still) can subscribe to another tenant's processing stream.

## Proposed Solutions

1. When the pipeline starts a job, store a `job:{job_id}` → `org_id` mapping in Redis (with TTL matching job lifetime).
2. In the SSE endpoint, after authentication, look up the job's `org_id` from Redis and compare against the authenticated user's `organization_id`.
3. Return HTTP 403 if the job does not belong to the authenticated tenant.
4. Optionally namespace Redis channels as `{org_id}:job:{job_id}` for defense-in-depth.

## Technical Details

- File: `backend/app/main.py` lines 197-204
- The Redis key should have a TTL (e.g., 1 hour) to prevent stale mappings from accumulating.
- The ownership check must happen before subscribing to the Redis channel to prevent even momentary data leakage.

## Acceptance Criteria

- SSE stream returns 403 if `job_id` does not belong to the authenticated tenant.
- Job-to-org mapping is stored in Redis when the pipeline job is created.
- No cross-tenant SSE subscription is possible.
