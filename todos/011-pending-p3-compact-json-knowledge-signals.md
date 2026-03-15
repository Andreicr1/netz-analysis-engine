---
status: pending
priority: p3
issue_id: "011"
tags: [code-review, performance]
dependencies: []
---

# Knowledge signals use indented JSON — compact format saves 30-40%

## Problem Statement
`json.dumps(signal, indent=2)` adds whitespace to machine-consumed data. At scale, this wastes ~30-40% storage and degrades DuckDB scan performance.

## Proposed Solutions
Use `json.dumps(signal, separators=(",", ":"))` for compact serialization. Same for `outcome_recorder.py`.

Future sprint: batch signals into daily Parquet files instead of per-signal JSON.

## Acceptance Criteria
- [ ] JSON output uses compact separators
