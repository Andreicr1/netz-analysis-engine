<!--
  Return Statistics Panel — eVestment Sections I-V.
  16-metric grid: absolute return/risk measures, risk-adjusted ratios, proficiency, regression.
  Split into Absolute (left) and Relative (right) sub-sections.
-->
<script lang="ts">
	import { formatPercent, formatNumber, plColor } from "@investintell/ui";
	import type { ReturnStatistics } from "$wealth/types/entity-analytics";

	interface Props {
		stats: ReturnStatistics;
	}

	let { stats }: Props = $props();

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
	<h2 class="ea-panel-title">Return Statistics</h2>
	<p class="ea-panel-sub">eVestment Sections I-V &middot; Monthly aggregated</p>

	<div class="ea-rs-layout">
		<!-- Absolute Metrics -->
		<div class="ea-rs-group">
			<h3 class="ea-rs-group-title">Absolute Return & Risk</h3>
			<div class="ea-stats-grid">
				<div class="ea-stat">
					<span class="ea-stat-label">Arith. Mean (M)</span>
					<span class="ea-stat-value" style:color={plColor(stats.arithmetic_mean_monthly)}>
						{fmtPct(stats.arithmetic_mean_monthly)}
					</span>
				</div>
				<div class="ea-stat">
					<span class="ea-stat-label">Geom. Mean (M)</span>
					<span class="ea-stat-value" style:color={plColor(stats.geometric_mean_monthly)}>
						{fmtPct(stats.geometric_mean_monthly)}
					</span>
				</div>
				<div class="ea-stat">
					<span class="ea-stat-label">Avg Gain (M)</span>
					<span class="ea-stat-value" style:color="var(--ii-success)">
						{fmtPct(stats.avg_monthly_gain)}
					</span>
				</div>
				<div class="ea-stat">
					<span class="ea-stat-label">Avg Loss (M)</span>
					<span class="ea-stat-value" style:color="var(--ii-danger)">
						{fmtPct(stats.avg_monthly_loss)}
					</span>
				</div>
				<div class="ea-stat">
					<span class="ea-stat-label">Gain/Loss</span>
					<span class="ea-stat-value">{fmtNum(stats.gain_loss_ratio)}</span>
				</div>
				<div class="ea-stat">
					<span class="ea-stat-label">Gain Std Dev</span>
					<span class="ea-stat-value">{fmtPct(stats.gain_std_dev)}</span>
				</div>
				<div class="ea-stat">
					<span class="ea-stat-label">Loss Std Dev</span>
					<span class="ea-stat-value">{fmtPct(stats.loss_std_dev)}</span>
				</div>
				<div class="ea-stat">
					<span class="ea-stat-label">Downside Dev</span>
					<span class="ea-stat-value">{fmtPct(stats.downside_deviation)}</span>
				</div>
				<div class="ea-stat">
					<span class="ea-stat-label">Semi Dev</span>
					<span class="ea-stat-value">{fmtPct(stats.semi_deviation)}</span>
				</div>
				<div class="ea-stat">
					<span class="ea-stat-label">Sterling</span>
					<span class="ea-stat-value">{fmtNum(stats.sterling_ratio)}</span>
				</div>
				<div class="ea-stat">
					<span class="ea-stat-label">Omega</span>
					<span class="ea-stat-value">{fmtNum(stats.omega_ratio)}</span>
				</div>
			</div>
		</div>

		<!-- Relative Metrics -->
		<div class="ea-rs-group">
			<h3 class="ea-rs-group-title">Relative & Risk-Adjusted</h3>
			<div class="ea-stats-grid">
				<div class="ea-stat">
					<span class="ea-stat-label">Treynor</span>
					<span class="ea-stat-value">{fmtNum(stats.treynor_ratio)}</span>
				</div>
				<div class="ea-stat">
					<span class="ea-stat-label">Jensen Alpha</span>
					<span class="ea-stat-value" style:color={plColor(stats.jensen_alpha)}>
						{fmtPct(stats.jensen_alpha)}
					</span>
				</div>
				<div class="ea-stat">
					<span class="ea-stat-label">R&sup2;</span>
					<span class="ea-stat-value">{fmtNum(stats.r_squared, 4)}</span>
				</div>
				<div class="ea-stat">
					<span class="ea-stat-label">Up Pct Ratio</span>
					<span class="ea-stat-value">{stats.up_percentage_ratio != null ? fmtNum(stats.up_percentage_ratio, 1) + "%" : "\u2014"}</span>
				</div>
				<div class="ea-stat">
					<span class="ea-stat-label">Down Pct Ratio</span>
					<span class="ea-stat-value">{stats.down_percentage_ratio != null ? fmtNum(stats.down_percentage_ratio, 1) + "%" : "\u2014"}</span>
				</div>
			</div>
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

	.ea-rs-layout {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 24px;
	}

	@media (max-width: 768px) {
		.ea-rs-layout {
			grid-template-columns: 1fr;
		}
	}

	.ea-rs-group-title {
		font-size: 0.75rem;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--ii-text-secondary);
		margin: 0 0 12px;
	}

	.ea-stats-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
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
