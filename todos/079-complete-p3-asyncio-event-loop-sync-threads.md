---
status: pending
priority: p3
issue_id: "079"
tags: [code-review, architecture]
---

# 079: asyncio.new_event_loop in sync threads

## Problem Statement

fact_sheets.py and fact_sheet_gen.py create throwaway event loops inside sync threads to call async `storage.write()`. This is a fragile pattern that can cause issues with nested loops and resource cleanup.

## Findings

- `fact_sheets.py:306-313` — creates `asyncio.new_event_loop()` in sync thread to call async storage
- `fact_sheet_gen.py:133-139` — same pattern, throwaway event loop for async storage write
- Throwaway loops risk resource leaks and conflict with existing event loops

## Proposed Solutions

Either:
1. Add a `StorageClient.write_sync()` method that handles the async-to-sync bridge internally
2. Return `BytesIO` to the async calling context and perform the storage write there

Option 2 is cleaner — keeps async/sync boundaries explicit.

## Acceptance Criteria

- [ ] No `asyncio.new_event_loop()` calls in fact_sheets.py or fact_sheet_gen.py
- [ ] Storage writes happen in the async context or via a dedicated sync adapter
- [ ] PDF generation tests still pass
