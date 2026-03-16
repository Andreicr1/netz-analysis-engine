---
status: pending
priority: p3
issue_id: "089"
tags: [code-review, quality, typing]
dependencies: []
---

# Improve Type Annotations in Admin Schemas

## Problem Statement
Several admin schemas use imprecise types:
- `PromptPreviewRequest.sample_data: dict` should be `dict[str, Any]` (prompts/schemas.py)
- `TenantDetail.configs: list[dict[str, Any]]` should use a proper typed model (admin/schemas.py)
- `WorkerStatus.status: str` should be `Literal["healthy", "degraded", "error", "unknown"]` (admin/schemas.py)
- `PromptInfo.source_level` and `PromptContent.source_level` should be `Literal["org", "global", "filesystem"]` (prompts/schemas.py)

## Findings
- **Source:** Kieran Python Reviewer (HIGH for sample_data, MEDIUM for others)

## Proposed Solutions
Add proper type annotations and create `TenantConfigInfo` model for typed config entries.
- **Effort:** Small (30 min)

## Acceptance Criteria
- [ ] All dict fields have type parameters
- [ ] Status/source_level fields use Literal types
- [ ] TenantDetail.configs uses a typed Pydantic model
