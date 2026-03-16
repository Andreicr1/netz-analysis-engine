---
status: pending
priority: p2
issue_id: "065"
tags: [code-review, architecture, quality]
---

# Extract shared render_content_pdf utility

## Problem Statement

`render_pdf()` is copy-pasted across 3 content engines (investment_outlook.py, flash_report.py, manager_spotlight.py). ~55 lines duplicated 3 times = ~110 redundant lines. The only differences are the title label key and manager_spotlight's subtitle. The route dispatcher in content.py also instantiates full engine objects just to call render_pdf().

## Findings

- investment_outlook.py, flash_report.py, and manager_spotlight.py each contain nearly identical `render_pdf()` implementations
- The differences are limited to the title label key and manager_spotlight's optional subtitle
- content.py:466-492 instantiates full engine objects just to access the render_pdf method
- ~110 lines of redundant code across the three files

## Proposed Solutions

Extract `render_content_pdf(content_md, *, title, subtitle="", language)` into `vertical_engines/wealth/content_pdf.py`. Each engine keeps a thin wrapper or the route calls the shared function directly.

## Technical Details

- Affected files:
  - `investment_outlook.py:98-154`
  - `flash_report.py:120-176`
  - `manager_spotlight.py:114-173`
  - `content.py:466-492`
- New file: `vertical_engines/wealth/content_pdf.py`
- The shared function signature: `render_content_pdf(content_md, *, title, subtitle="", language)`

## Acceptance Criteria

- [ ] Shared `render_content_pdf()` function exists in `vertical_engines/wealth/content_pdf.py`
- [ ] All 3 content engines use the shared function (or thin wrappers around it)
- [ ] content.py route dispatcher calls the shared function directly without instantiating full engine objects
- [ ] ~110 redundant lines removed
- [ ] All existing tests pass
- [ ] PDF output is identical before and after refactor

## Work Log

(none yet)
