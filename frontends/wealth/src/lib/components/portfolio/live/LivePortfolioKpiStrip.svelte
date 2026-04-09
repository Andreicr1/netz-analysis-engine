<!--
  LivePortfolioKpiStrip — Phase 8 Live Workbench header KPI row.

  Six KPI cards spanning the top of the main content area. Reads
  the selected live portfolio's schema fields + optional
  optimization metadata stored on ``fund_selection_schema.optimization``
  when available. No backend fetches — everything is projected from
  the portfolio ORM row that the sidebar selects.

  KPIs (density-tight, monitoring-first):
    1. Fund count          — how many constituents
    2. Total weight        — should be ~100% (warning if not)
    3. Expected return     — from optimization metadata
    4. Portfolio volatility — from optimization metadata
    5. CVaR 95%            — from optimization metadata
    6. Inception date      — when the portfolio went live

  Per CLAUDE.md:
    - DL16: every number via @investintell/ui formatters
    - OD-26: strict "—" fallbacks when metadata is missing
    - No ECharts: this is pure KPI presentation (user constraint)
-->
<script lang="ts">
	import {
		formatPercent,
		formatNumber,
		formatShortDate,
	} from "@investintell/ui";
	import type { ModelPortfolio } from "$lib/types/model-portfolio";

	interface Props {
		portfolio: ModelPortfolio;
	}

	let { portfolio }: Props = $props();

	const funds = $derived(portfolio.fund_selection_schema?.funds ?? []);
	const fundCount = $derived(funds.length);
	const totalWeight = $derived(
		funds.reduce((acc, f) => acc + (f.weight ?? 0), 0),
	);
	const optimization = $derived(portfolio.fund_selection_schema?.optimization ?? null);

	const weightAccent = $derived.by<"ok" | "warn">(() => {
		if (totalWeight >= 0.98 && totalWeight <= 1.02) return "ok";
		return "warn";
	});

	const cvarAccent = $derived.by<"ok" | "warn" | "danger">(() => {
		if (!optimization || optimization.cvar_95 === null) return "ok";
		if (optimization.cvar_within_limit) return "ok";
		return "danger";
	});
</script>

<section class="lks-root" aria-label="Portfolio KPIs">
	<div class="lks-card">
		<span class="lks-kicker">Funds</span>
		<span class="lks-value">{fundCount}</span>
		<span class="lks-meta">constituents</span>
	</div>

	<div class="lks-card">
		<span class="lks-kicker">Total weight</span>
		<span class="lks-value" data-accent={weightAccent}>
			{formatPercent(totalWeight, 2)}
		</span>
		<span class="lks-meta">
			{weightAccent === "ok" ? "within tolerance" : "outside [98%, 102%]"}
		</span>
	</div>

	<div class="lks-card">
		<span class="lks-kicker">Expected return</span>
		<span class="lks-value">
			{optimization && optimization.expected_return !== null
				? formatPercent(optimization.expected_return, 2)
				: "—"}
		</span>
		<span class="lks-meta">annualized, ex ante</span>
	</div>

	<div class="lks-card">
		<span class="lks-kicker">Volatility</span>
		<span class="lks-value">
			{optimization && optimization.portfolio_volatility !== null
				? formatPercent(optimization.portfolio_volatility, 2)
				: "—"}
		</span>
		<span class="lks-meta">annualized</span>
	</div>

	<div class="lks-card">
		<span class="lks-kicker">Tail loss (95%)</span>
		<span class="lks-value" data-accent={cvarAccent}>
			{optimization && optimization.cvar_95 !== null
				? formatPercent(optimization.cvar_95, 2)
				: "—"}
		</span>
		<span class="lks-meta">
			{#if optimization?.cvar_limit !== null && optimization?.cvar_limit !== undefined}
				limit {formatPercent(optimization.cvar_limit, 2)}
			{:else}
				no limit set
			{/if}
		</span>
	</div>

	<div class="lks-card">
		<span class="lks-kicker">Sharpe</span>
		<span class="lks-value">
			{optimization && optimization.sharpe_ratio !== null
				? formatNumber(optimization.sharpe_ratio, 2)
				: "—"}
		</span>
		<span class="lks-meta">
			{#if portfolio.inception_date}
				live since {formatShortDate(portfolio.inception_date)}
			{:else}
				live portfolio
			{/if}
		</span>
	</div>
</section>

<style>
	.lks-root {
		display: grid;
		grid-template-columns: repeat(6, minmax(0, 1fr));
		gap: 12px;
		font-family: "Urbanist", system-ui, sans-serif;
	}
	@container (max-width: 1100px) {
		.lks-root {
			grid-template-columns: repeat(3, minmax(0, 1fr));
		}
	}
	@container (max-width: 640px) {
		.lks-root {
			grid-template-columns: repeat(2, minmax(0, 1fr));
		}
	}

	.lks-card {
		display: flex;
		flex-direction: column;
		gap: 4px;
		padding: 14px 16px;
		background: #141519;
		border: 1px solid var(--ii-border-subtle, rgba(64, 66, 73, 0.4));
		border-radius: 8px;
		min-width: 0;
	}

	.lks-kicker {
		font-size: 10px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--ii-text-muted, #85a0bd);
	}

	.lks-value {
		font-size: 20px;
		font-weight: 700;
		font-variant-numeric: tabular-nums;
		color: var(--ii-text-primary, #ffffff);
		line-height: 1.1;
	}
	.lks-value[data-accent="ok"] {
		color: var(--ii-text-primary, #ffffff);
	}
	.lks-value[data-accent="warn"] {
		color: var(--ii-warning, #f0a020);
	}
	.lks-value[data-accent="danger"] {
		color: var(--ii-danger, #fc1a1a);
	}

	.lks-meta {
		font-size: 10px;
		color: var(--ii-text-muted, #85a0bd);
		text-transform: capitalize;
	}
</style>
