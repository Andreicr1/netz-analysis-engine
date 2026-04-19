<!--
  Risk Statistics Grid — 10-metric card grid for entity analytics.
  Displays annualized return, volatility, Sharpe, Sortino, Calmar, max drawdown,
  alpha, beta, tracking error, information ratio.
-->
<script lang="ts">
	import { formatPercent, formatNumber, formatDate, plColor } from "@investintell/ui";
	import type { RiskStatistics } from "$wealth/types/entity-analytics";

	interface Props {
		stats: RiskStatistics;
		asOfDate: string;
	}

	let { stats, asOfDate }: Props = $props();

	function fmtPct(v: number | null): string {
		if (v == null) return "\u2014";
		return formatPercent(v, 2, "en-US", true);
	}

	function fmtNum(v: number | null, decimals = 2): string {
		if (v == null) return "\u2014";
		return formatNumber(v, decimals, "en-US");
	}
</script>

<section class="ea-panel">
	<h2 class="ea-panel-title">Risk Statistics</h2>
	<p class="ea-panel-sub">{stats.n_observations} trading days &middot; as of {formatDate(asOfDate, "medium", "en-US")}</p>
	<div class="ea-stats-grid">
		<div class="ea-stat">
			<span class="ea-stat-label">Ann. Return</span>
			<span class="ea-stat-value" style:color={plColor(stats.annualized_return)}>
				{fmtPct(stats.annualized_return)}
			</span>
		</div>
		<div class="ea-stat">
			<span class="ea-stat-label">Ann. Volatility</span>
			<span class="ea-stat-value">{fmtPct(stats.annualized_volatility)}</span>
		</div>
		<div class="ea-stat">
			<span class="ea-stat-label">Sharpe</span>
			<span class="ea-stat-value">{fmtNum(stats.sharpe_ratio)}</span>
		</div>
		<div class="ea-stat">
			<span class="ea-stat-label">Sortino</span>
			<span class="ea-stat-value">{fmtNum(stats.sortino_ratio)}</span>
		</div>
		<div class="ea-stat">
			<span class="ea-stat-label">Calmar</span>
			<span class="ea-stat-value">{fmtNum(stats.calmar_ratio)}</span>
		</div>
		<div class="ea-stat">
			<span class="ea-stat-label">Max Drawdown</span>
			<span class="ea-stat-value" style:color="var(--ii-danger)">
				{fmtPct(stats.max_drawdown)}
			</span>
		</div>
		<div class="ea-stat">
			<span class="ea-stat-label">Alpha</span>
			<span class="ea-stat-value" style:color={plColor(stats.alpha)}>
				{fmtPct(stats.alpha)}
			</span>
		</div>
		<div class="ea-stat">
			<span class="ea-stat-label">Beta</span>
			<span class="ea-stat-value">{fmtNum(stats.beta)}</span>
		</div>
		<div class="ea-stat">
			<span class="ea-stat-label">Tracking Error</span>
			<span class="ea-stat-value">{fmtPct(stats.tracking_error)}</span>
		</div>
		<div class="ea-stat">
			<span class="ea-stat-label">Info Ratio</span>
			<span class="ea-stat-value">{fmtNum(stats.information_ratio)}</span>
		</div>
	</div>
</section>

<style>
	.ea-panel {
		background: var(--ii-surface-elevated);
		border: 1px solid var(--ii-border);
		border-radius: 12px;
		padding: clamp(16px, 1rem + 0.5vw, 28px);
		margin-bottom: 16px;
	}

	.ea-panel-title {
		font-size: 0.9rem;
		font-weight: 700;
		color: var(--ii-text-primary);
		margin: 0 0 4px;
	}

	.ea-panel-sub {
		font-size: 0.75rem;
		color: var(--ii-text-muted);
		margin: 0 0 16px;
	}

	.ea-stats-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));
		gap: 12px;
	}

	.ea-stat {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.ea-stat-label {
		font-size: 0.7rem;
		font-weight: 500;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--ii-text-muted);
	}

	.ea-stat-value {
		font-size: 1.1rem;
		font-weight: 700;
		color: var(--ii-text-primary);
		font-variant-numeric: tabular-nums;
	}
</style>
