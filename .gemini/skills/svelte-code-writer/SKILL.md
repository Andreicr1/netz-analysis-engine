# svelte-code-writer

CLI tools for Svelte 5 documentation lookup and code analysis. MUST be used whenever creating, editing or analyzing any Svelte component (.svelte) or Svelte module (.svelte.ts/.svelte.js). If possible, this skill should be executed within the svelte-file-editor agent for optimal results.

## Overview

You have access to `@sveltejs/mcp` CLI for Svelte-specific assistance. Use these commands via npx:

### Available Commands

#### `npx @sveltejs/mcp list-sections`
Lists all available Svelte 5 and SvelteKit documentation sections with titles and paths.
**Use this FIRST** to discover all available documentation sections.
When asked about Svelte or SvelteKit topics, ALWAYS use this at the start to find relevant sections.

#### `npx @sveltejs/mcp get-documentation "<section1>,<section2>,..."`
Retrieves full documentation content for specified sections.
After calling list-sections, you MUST analyze the returned sections (especially the `use_cases` field)
and fetch ALL documentation sections relevant to the user's task.

#### `npx @sveltejs/mcp svelte-autofixer '<svelte code>'`
Analyzes Svelte code and suggests fixes for common issues.

```bash
# Analyze inline code (escape $ as \$)
npx @sveltejs/mcp svelte-autofixer '<script>let count = \$state(0);</script>'

# Analyze a file
npx @sveltejs/mcp svelte-autofixer ./src/lib/Component.svelte

# Target Svelte 4
npx @sveltejs/mcp svelte-autofixer ./Component.svelte --svelte-version 4
```

> **Important:** When passing code with runes ($state, $derived, etc.) via the terminal,
> escape the $ character as \$ to prevent shell variable substitution.

## Workflow Rules

- **Uncertain about syntax?** Run `list-sections` then `get-documentation` for relevant topics
- **Reviewing/debugging?** Run `svelte-autofixer` on the code to detect issues
- **Always validate** — Run `svelte-autofixer` before finalizing any Svelte component

## Project-Specific Context (netz-analysis-engine)

This project uses **SvelteKit 2 + Svelte 5** with the following stack:
- TypeScript (strict)
- Tailwind CSS 4
- shadcn-svelte components
- Apache ECharts via `svelte-echarts`
- Clerk authentication (`svelte-clerk`)
- paraglide-js for i18n
- SSE via `fetch()` + `ReadableStream` (NOT `EventSource` — cannot send auth headers)

### Key patterns for this project

**Stores:** Use Svelte writable stores for CVaR, regime, drift, jobs data.
All stores must expose: `status: 'loading' | 'ready' | 'error' | 'stale'`, `lastUpdated`, `error`.

**SSE streaming:**
```typescript
// CORRECT — use fetch + ReadableStream for authenticated SSE
const response = await fetch('/api/v1/jobs/{id}/stream', {
  headers: { Authorization: `Bearer ${token}` }
});
const reader = response.body!.getReader();

// WRONG — EventSource cannot send auth headers
// const es = new EventSource('/api/v1/jobs/{id}/stream');
```

**Numeric formatting:**
```typescript
// Always use tabular-nums for financial data
// font-variant-numeric: tabular-nums
```

**No localStorage/sessionStorage** — use Svelte state only.
