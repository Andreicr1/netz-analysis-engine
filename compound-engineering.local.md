---
review_agents:
  - security-sentinel
  - architecture-strategist
  - performance-oracle
  - pattern-recognition-specialist
---

## Review Context

This is a multi-tenant institutional investment platform (credit + wealth verticals) with:
- FastAPI async backend with RLS (Row-Level Security)
- SvelteKit frontends (admin, credit, wealth) using Svelte 5 runes
- ECharts for charts (svelte-echarts), no Chart.js
- No localStorage for portfolio data — in-memory stores + SSE + polling
- Clerk JWT authentication
- ADLS Gen2 data lake (feature-flagged)

Key rules from CLAUDE.md:
- async-first, lazy="raise" on relationships, SET LOCAL for RLS
- Never expose prompt content in client responses
- All CSS via var(--netz-*) tokens
- ConfirmDialog for destructive actions
- Pessimistic UI by default (wait for server response)
