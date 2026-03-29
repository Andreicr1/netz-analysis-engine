# @investintell/ui

Design system do InvestIntell — construido sobre shadcn-svelte (Bits UI).

## Tokens

Prefixo: `--ii-*`
Fonte: Geist + Geist Mono
Modo: Light default + `.dark`

## shadcn-svelte components

Import from specific paths:

```svelte
<script>
  import { Button } from "@investintell/ui/components/ui/button";
  import * as Dialog from "@investintell/ui/components/ui/dialog";
  import * as Card from "@investintell/ui/components/ui/card";
</script>
```

All 56 shadcn-svelte components available in `src/lib/components/ui/`.

## Analytical components

```svelte
<script>
  import { MetricCard, StatusBadge, RegimeBanner } from "@investintell/ui";
</script>
```

See `src/lib/components/analytical/` — ECharts-based financial analysis components.

## Charts

```svelte
<script>
  import { TimeSeriesChart, CorrelationHeatmap } from "@investintell/ui/charts";
</script>
```

## Utilities

```svelte
<script>
  import { formatCurrency, formatPercent, cn } from "@investintell/ui";
</script>
```

## Token migration from @netz/ui

| @netz/ui | @investintell/ui |
|---|---|
| `--netz-brand-primary` | `--ii-brand-primary` |
| `--netz-text-primary` | `--ii-text-primary` |
| `--netz-surface` | `--ii-surface` |
| `--netz-border` | `--ii-border` |
| `--netz-success` | `--ii-success` |
| `.netz-ui-*` classes | `.ii-ui-*` classes |
| `netz-animate-*` | `ii-animate-*` |
| IBM Plex Sans | Geist |
| IBM Plex Mono | Geist Mono |
