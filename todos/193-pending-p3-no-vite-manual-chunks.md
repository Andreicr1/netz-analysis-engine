---
status: complete
priority: p3
issue_id: "193"
tags: [code-review, performance, frontend]
dependencies: []
---

# No Vite manual chunks for ECharts and TanStack Table

## Problem Statement

Both credit and wealth `vite.config.ts` lack `build.rollupOptions.output.manualChunks`. ECharts (~300KB minified), TanStack Table, and bits-ui are bundled into main chunk or split unpredictably. Manual chunks would enable long-term caching for heavy dependencies.

## Findings

- `frontends/wealth/vite.config.ts` — no manualChunks
- `frontends/credit/vite.config.ts` — no manualChunks
- ECharts rarely changes but app code changes frequently — should be separate chunks

## Proposed Solutions

### Option 1: Add manual chunks configuration

**Approach:** Add `build.rollupOptions.output.manualChunks` to isolate echarts and table.

**Effort:** 30 minutes

**Risk:** Low

## Technical Details

**Affected files:**
- `frontends/wealth/vite.config.ts`
- `frontends/credit/vite.config.ts`

## Acceptance Criteria

- [ ] ECharts in separate chunk
- [ ] TanStack Table in separate chunk
- [ ] Build produces correctly split bundles

## Work Log

### 2026-03-17 - Initial Discovery
**By:** Claude Code (codex review — performance-oracle agent)
