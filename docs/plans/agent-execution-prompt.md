Execute the next valid task or an explicitly selected task from docs/plans/ux-remediation-plan.md

## Source hierarchy (read all before selecting task)
1. docs/plans/ux-remediation-plan.md — task order, dependencies, scope, acceptance criteria, DoD
2. docs/audit/endpoint_coverage_audit.md — endpoint coverage, phantom calls, disconnected endpoints
3. docs/audit/backend-system-map-v2.md — canonical flows, runtime boundaries, transitional/legacy zones
4. docs/audit/backend-architecture-audit-v2.md — validated claims, contradictions, resolved/open risks
5. docs/audit/frontend-type-inventory.md — type readiness: READY / PARTIALLY_READY / BLOCKED_BY_TYPES

If any required file cannot be found or read, stop and report. If backend code conflicts with all documents, follow the code and report the mismatch.

## Execution contract (non-negotiable)
This prompt is a non-negotiable execution contract. Deviation is a failure condition, not a judgment call.
If you find yourself reasoning about whether a rule should apply — stop. Report the blocker instead.

- Implementation only. No re-planning, no architecture redesign, no backlog reshaping.
- Respect all dependencies, backend gates, and shared primitive sequencing strictly.
- Preserve existing behavior outside task scope.
- Never invent fields, states, actions, or backend behavior outside real contracts.
- Never expose raw enums or backend-internal language to users.
- Never hide technical failures on operational surfaces or convert degraded states into empty states.
- Never bypass shared API clients, canonical stores, shared formatters, or approved live-data paths.
- Never implement against transitional or legacy paths (see system-map-v2 §5 for classification).
- If any task touches the admin frontend, audit all `{@html}` usage in scope before proceeding.
- Execute serially.

## Task selection
- With explicit task id: execute only that task.
- Without task id: select the next executable task from the plan.
- Executable = all plan dependencies satisfied + type inventory classifies it READY or PARTIALLY_READY.
- BLOCKED_BY_TYPES: stop and report the exact missing contract or type artifact.

## Type readiness gate
- Check frontend-type-inventory.md before writing any code.
- READY → proceed. PARTIALLY_READY → proceed only if gaps are small, in-scope, and plan-allowed.
- BLOCKED_BY_TYPES → stop and report. Do not compensate with `any`, unsafe casts, or invented shapes.
- Run `make types` if required by the task or type inventory preconditions. Stop if it fails.

## Implementation steps
1. Read all 5 source documents in order.
2. Select task. Verify dependencies and type readiness.
3. Run `make types` if required.
4. Inspect current code paths in scope before editing.
5. Implement fully. No placeholders for in-scope endpoints.
6. Add or update required tests.
7. Run narrowest sufficient validation. If it fails, stop and report — do not claim completion.
8. Verify acceptance criteria against code and tests.
9. Commit as a focused incremental commit.
10. Stop. Do not continue to the next task.

## Domain rules
- Credit: action-first, audit-first, consequence-aware, decision-safe.
- Wealth: backend-authoritative freshness only — never `Date.now()` for operational truth.
- Admin: tenant scope always explicit, degraded states always visible, technical truth never hidden.
- All domains: handle loading / empty / error / degraded / stale / success states.
- Role-gated actions must be hidden or disabled per current contracts.
- Consequential actions require governed confirmation where the plan requires it.
- All financial values, dates, and labels use canonical shared formatters.

## Output (only these fields)
current branch | default branch | branch created or reused | selected task id
dependency check | type readiness | scoped coverage check | canonical path alignment
make types result (if run) | files changed | tests added/updated | validation result
acceptance criteria result | commit hash and message | blocked items or risks | next recommended task

Do not output reasoning, narrative, backlog summaries, or unrelated repository information.
