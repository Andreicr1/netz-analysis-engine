<!--
  Active Share Panel — eVestment p.73.
  Active share metric + overlap + efficiency + position counts.
-->
<script lang="ts">
	import { formatNumber, formatPercent } from "@investintell/ui";
	import type { ActiveShareResult } from "$lib/types/analytics";

	interface Props {
		activeShare: ActiveShareResult;
	}

	let { activeShare }: Props = $props();

	function fmtPct(v: number): string {
		return formatPercent(v / 100, 2, "en-US", false);
	}

	function fmtNum(v: number | null, decimals = 2): string {
		if (v == null) return "\u2014";
		return formatNumber(v, decimals, "en-US");
	}

	let asColor = $derived(
		activeShare.active_share >= 60 ? "var(--ii-success)" :
		activeShare.active_share >= 30 ? "var(--ii-warning)" :
		"var(--ii-danger)"
	);

	let asLabel = $derived(
		activeShare.active_share >= 80 ? "Stock Picker" :
		activeShare.active_share >= 60 ? "Active" :
		activeShare.active_share >= 30 ? "Moderately Active" :
		"Closet Indexer"
	);
</script>

<section class="ea-panel">
	<h2 class="ea-panel-title">Active Share</h2>
	<p class="ea-panel-sub">
		Holdings-based overlap analysis &middot;
		{#if activeShare.as_of_date}
			As of {activeShare.as_of_date}
		{/if}
	</p>

	<div class="as-hero">
		<div class="as-ring">
			<span class="as-ring-value" style:color={asColor}>{fmtPct(activeShare.active_share)}</span>
			<span class="as-ring-label">Active Share</span>
			<span class="as-ring-badge" style:color={asColor}>{asLabel}</span>
		</div>
	</div>

	<div class="as-stats">
		<div class="ea-stat">
			<span class="ea-stat-label">Overlap</span>
			<span class="ea-stat-value">{fmtPct(activeShare.overlap)}</span>
		</div>
		<div class="ea-stat">
			<span class="ea-stat-label">Efficiency</span>
			<span class="ea-stat-value">{fmtNum(activeShare.active_share_efficiency)}</span>
		</div>
		<div class="ea-stat">
			<span class="ea-stat-label">Portfolio Pos.</span>
			<span class="ea-stat-value">{activeShare.n_portfolio_positions}</span>
		</div>
		<div class="ea-stat">
			<span class="ea-stat-label">Benchmark Pos.</span>
			<span class="ea-stat-value">{activeShare.n_benchmark_positions}</span>
		</div>
		<div class="ea-stat">
			<span class="ea-stat-label">Common Pos.</span>
			<span class="ea-stat-value">{activeShare.n_common_positions}</span>
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

	.as-hero {
		display: flex;
		justify-content: center;
		margin-bottom: 20px;
	}

	.as-ring {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 4px;
	}

	.as-ring-value {
		font-size: 2.5rem;
		font-weight: 800;
		font-variant-numeric: tabular-nums;
	}

	.as-ring-label {
		font-size: 0.75rem;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--ii-text-muted);
	}

	.as-ring-badge {
		font-size: 0.7rem;
		font-weight: 700;
		padding: 2px 10px;
		border-radius: 6px;
		background: color-mix(in srgb, currentColor 10%, transparent);
	}

	.as-stats {
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
