# @investintell/eslint-plugin-netz-runtime

ESLint rules that enforce the Netz Stability Guardrails runtime contract (design spec §5.3, charter `docs/reference/stability-guardrails.md`).

## Rules

| Rule | Principle | Severity v1 | Purpose |
| --- | --- | --- | --- |
| `no-unsafe-derived` | P4 | `error` | Reject `$derived(x.y)` patterns where `x` is not narrowed or optional-chained. Prevents the "black screen FactSheet" class of crashes. |
| `require-load-timeout` | P6 | `error` | Reject SvelteKit `+page.{ts,server.ts}` load functions that call `fetch` / api-client methods without passing `AbortSignal.timeout(...)`. Prevents pages that hang forever waiting for a dead upstream. |
| `require-tick-buffer-dispose` | P4 | `error` | Reject files that call `createTickBuffer(...)` without a matching `.dispose()` somewhere in the same module. Prevents RAF / interval leaks. |
| `require-svelte-boundary` | P3 | `warn` (promote to `error` in hardening sprint) | Reject `+page.svelte` / `+layout.svelte` files whose source text contains a component tag but no `<svelte:boundary>`. Text-level heuristic — the hardening sprint will replace this with a Svelte-parser rule. |

## Install

Plugin is consumed as a workspace dependency from the monorepo root:

```json
{
  "devDependencies": {
    "@investintell/eslint-plugin-netz-runtime": "workspace:*"
  }
}
```

Then in `eslint.config.js`:

```js
import netzRuntime from "@investintell/eslint-plugin-netz-runtime";

export default [
  {
    plugins: { "netz-runtime": netzRuntime },
    rules: {
      "netz-runtime/no-unsafe-derived": "error",
      "netz-runtime/require-load-timeout": "error",
      "netz-runtime/require-tick-buffer-dispose": "error",
      "netz-runtime/require-svelte-boundary": "warn",
    },
  },
];
```

## Philosophy

The rules are heuristic, not complete. They favour **false negatives over false positives**: it is better to occasionally miss a violation than to make developers `// eslint-disable` legitimate code (which creates alert fatigue and erodes the charter). When a rule fires, it always links to the relevant `stability-guardrails.md` section for the "why".

See the design spec §6.1 risk R1.9 for the rationale behind `warn` severity on the text-level rule.
