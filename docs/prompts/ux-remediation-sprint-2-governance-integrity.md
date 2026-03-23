# UX Remediation Sprint 2 — Governance Integrity (P1)

## Context

You are executing Sprint 2 of the Premium UX Remediation effort for the Netz Analysis Engine — a multi-tenant institutional investment platform with Credit and Wealth verticals.

Read these files before starting any work:
- `CLAUDE.md` — full project rules, architecture, critical constraints
- `docs/ux/premium-ux-remediation-execution-backlog.md` — full backlog (you are executing Phase 2: BL-06 and BL-07)

**Sprint 1 (P0 Critical Safety) is complete.** All five BL-01 through BL-05 items shipped:
- DD report approve endpoint now requires `DDReportApproveRequest` with `rationale: str` (min 10, max 2000). Tests updated.
- DD report approve/reject both use `ConsequenceDialog` with mandatory rationale.
- Universe approve/reject both use `ConsequenceDialog` with mandatory rationale.
- Universe backend rejects invalid decision values with 422 (explicit validation, no silent fallback).
- No new database migrations were needed in Sprint 1. The `DDReport` model has `rejection_reason` (Text, nullable) and `approved_by`/`approved_at` fields. There is no `approval_rationale` column — approval rationale is currently only logged via structlog. Sprint 2 should add proper audit trail storage.

---

## What you are fixing

This sprint covers **BL-06** and **BL-07** — Governance Integrity items that make Wealth's status management and audit trail match Credit's structural maturity.

### BL-06 — Wealth Status Enums and Database Constraints

**Problem:** `DDReport.status` (`String(30)`, server_default `"draft"`) and `UniverseApproval.decision` (`String(30)`, server_default `"pending"`) are bare string fields. Any value is accepted by the database. Credit defines all workflow states as Python enums with compile-time validation. A typo in a Wealth status string would pass all type checks silently.

**Files to modify:**
- `backend/app/domains/wealth/enums.py` (NEW) — create `DDReportStatus` and `UniverseDecision` enums
- `backend/app/domains/wealth/models/dd_report.py` — use enum for `status` column
- `backend/app/domains/wealth/models/universe_approval.py` — use enum for `decision` column
- `backend/app/domains/wealth/routes/dd_reports.py` — validate against enum
- `backend/app/domains/wealth/routes/universe.py` — validate against enum (update `_APPROVE_DECISIONS` set to use enum)
- `backend/app/domains/wealth/schemas/` — update response models if needed
- New Alembic migration — add `CheckConstraint` on both columns

**Enum definitions:**
```python
from enum import Enum

class DDReportStatus(str, Enum):
    draft = "draft"
    generating = "generating"
    ready_for_review = "ready_for_review"
    pending_approval = "pending_approval"
    approved = "approved"
    rejected = "rejected"
    published = "published"

class UniverseDecision(str, Enum):
    pending = "pending"
    approved = "approved"
    watchlist = "watchlist"
    rejected = "rejected"
```

**Data audit before migration:** Run these queries to check existing values:
```sql
SELECT DISTINCT status FROM dd_reports;
SELECT DISTINCT decision FROM universe_approvals;
```

**Acceptance criteria:**
- Both enums are `str, Enum` subclasses (JSON-serializable)
- Database columns have `CheckConstraint` enforcing valid values
- Alembic migration passes on existing data
- All routes that mutate status/decision validate against enum
- Existing tests pass; add new tests for enum validation rejection
- Use `lower_case` values (matches existing Wealth data, documented divergence from Credit's `UPPER_CASE`)

---

### BL-07 — Wealth Audit Trail: Event Logging and Query Endpoints

**Problem:** Wealth tracks only final state (`approved_by`, `approved_at` on DD reports; final `decision` on universe approvals). No event history. Credit has full `AuditEvent` infrastructure. The backend already has `write_audit_event()` in `backend/app/core/db/audit.py` — Wealth simply does not use it.

**Files to modify:**
- `backend/app/core/db/audit.py` — read to understand `write_audit_event()` API
- `backend/app/core/db/models.py` — read `AuditEvent` model structure
- `backend/app/domains/wealth/routes/dd_reports.py` — add audit event logging on status changes (approve, reject)
- `backend/app/domains/wealth/routes/universe.py` — add audit event logging on decisions
- New route endpoints:
  - `GET /dd-reports/{report_id}/audit-trail` — returns chronological event list
  - `GET /universe/funds/{instrument_id}/audit-trail` — returns chronological event list

**Important from Sprint 1:** The DD report approve endpoint now accepts `body: DDReportApproveRequest` with `rationale`. The rationale should be stored in the audit event (not just logged). The reject endpoint uses `body: DDReportRejectRequest` with `reason` field.

**Acceptance criteria:**
- `AuditEvent` rows created for: DD report status changes, universe approval decisions
- Each event records: actor, timestamp, old value, new value, rationale (when captured)
- Query endpoints return chronological event lists
- Audit events are immutable (no UPDATE/DELETE)
- Existing tests pass; add tests for audit trail endpoints

---

## Execution strategy — parallel agents

Use `model: sonnet` for all agents.

### Phase 1 — Research (1 agent)

**Agent R — Read audit infrastructure**
- Read `backend/app/core/db/audit.py` and `backend/app/core/db/models.py` to understand `AuditEvent` model and `write_audit_event()` API
- Read `backend/app/domains/wealth/models/universe_approval.py` to understand current model
- Report findings (field names, parameters, any Credit-specific assumptions)

### Phase 2 — Backend implementation (2 agents in parallel)

**Agent A — BL-06: Enums + migration**
- Create `enums.py`, update models, update routes, create Alembic migration
- Depends on: nothing (self-contained)

**Agent B — BL-07: Audit trail logging + query endpoints**
- Add `write_audit_event()` calls to DD report and universe routes
- Add query endpoints for audit trail
- Depends on: Agent R findings (AuditEvent API)

### Phase 3 — Verification

- Run `make check` (lint + architecture + typecheck + test)
- Verify new migration can be generated cleanly

---

## Critical rules (from CLAUDE.md)

- **Async-first:** All route handlers use `async def` + `AsyncSession`
- **Pydantic schemas:** All routes use `response_model=` and return via `model_validate()`
- **lazy="raise":** All relationships. Forces explicit `selectinload()`/`joinedload()`
- **expire_on_commit=False:** Always
- **SET LOCAL not SET:** RLS context must use `SET LOCAL` (transaction-scoped)
- **Current migration head:** `0004_vertical_configs` (may have advanced — check with `alembic heads`)
- Do not add features beyond scope. This sprint is strictly BL-06 and BL-07.

---

## What to do when this sprint is done

After completing all items and verifying:

1. Run `make check` to confirm all gates pass
2. Commit with a descriptive message covering BL-06 and BL-07
3. **Prepare a handoff prompt** for Sprint 3 — System Legibility (P2), covering:
   - BL-08: Evidence Pack Inspector: IC Memos
   - BL-09: Evidence Pack Inspector: DD Reports
   - BL-10: AI-Generated Content Markers
   - BL-11: Persistent Provenance Visibility on Document List Pages
   - BL-12: StatusBadge Unknown State Dev Warning

   Save to `docs/prompts/ux-remediation-sprint-3-system-legibility.md`. Same structure: context, findings from Sprint 2, exact files, required changes, acceptance criteria, verification, execution strategy.

Do not implement Sprint 3. Only prepare its prompt.
