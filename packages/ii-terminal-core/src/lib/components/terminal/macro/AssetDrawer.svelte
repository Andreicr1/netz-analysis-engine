<script lang="ts">
	import type { CrossAssetPoint } from "./CrossAssetPanel.svelte";

	interface TimePoint {
		obs_date: string;
		value: number;
	}

	interface Props {
		asset: CrossAssetPoint | null;
		onClose: () => void;
		fetchSeries: (symbol: string) => Promise<TimePoint[]>;
	}

	let { asset, onClose, fetchSeries }: Props = $props();

	let series = $state<TimePoint[]>([]);
	let loading = $state(false);
	let activeTimeframe = $state<"1W" | "1M" | "3M" | "YTD" | "1Y" | "ALL">("3M");

	$effect(() => {
		if (!asset) {
			series = [];
			return;
		}
		let cancelled = false;
		loading = true;
		fetchSeries(asset.symbol)
			.then((data) => {
				if (!cancelled) series = data;
			})
			.finally(() => {
				if (!cancelled) loading = false;
			});
		return () => {
			cancelled = true;
		};
	});

	function cutoff(tf: typeof activeTimeframe): Date {
		const now = new Date();
		switch (tf) {
			case "1W":
				return new Date(now.getTime() - 7 * 86_400_000);
			case "1M":
				return new Date(now.getFullYear(), now.getMonth() - 1, now.getDate());
			case "3M":
				return new Date(now.getFullYear(), now.getMonth() - 3, now.getDate());
			case "YTD":
				return new Date(now.getFullYear(), 0, 1);
			case "1Y":
				return new Date(now.getFullYear() - 1, now.getMonth(), now.getDate());
			default:
				return new Date(0);
		}
	}

	const filteredSeries = $derived(series.filter((point) => new Date(point.obs_date) >= cutoff(activeTimeframe)));
	const TIMEFRAMES = ["1W", "1M", "3M", "YTD", "1Y", "ALL"] as const;
	const STAT_TIMEFRAMES = ["1W", "1M", "3M", "YTD", "1Y"] as const;
	const chartH = 120;
	const chartW = 440;
	const minVal = $derived(filteredSeries.length ? Math.min(...filteredSeries.map((point) => point.value)) : 0);
	const maxVal = $derived(filteredSeries.length ? Math.max(...filteredSeries.map((point) => point.value)) : 1);
	const valRange = $derived(maxVal - minVal || 1);
	const mainPolyline = $derived(toChartPts(filteredSeries));

	function statFor(tf: (typeof STAT_TIMEFRAMES)[number]): string {
		const points = series.filter((point) => new Date(point.obs_date) >= cutoff(tf));
		if (points.length < 2) return "-";
		const first = points[0]!.value;
		const last = points[points.length - 1]!.value;
		const change = ((last - first) / Math.abs(first)) * 100;
		return `${change >= 0 ? "+" : ""}${change.toFixed(2)}%`;
	}

	function toChartPts(points: TimePoint[]): string {
		if (points.length < 2) return "";
		return points
			.map((point, index) => {
				const x = (index / (points.length - 1)) * chartW;
				const y = chartH - 4 - ((point.value - minVal) / valRange) * (chartH - 8);
				return `${x},${y}`;
			})
			.join(" ");
	}

	function fmtAssetValue(value: number | null, unit: string): string {
		if (value === null) return "-";
		if (unit === "%") return `${value.toFixed(2)}%`;
		return value.toFixed(2);
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === "Escape" && asset) onClose();
	}
</script>

<svelte:window onkeydown={handleKeydown} />

{#if asset}
	<!-- svelte-ignore a11y_click_events_have_key_events a11y_no_static_element_interactions -->
	<div class="ad-backdrop" onclick={onClose}></div>

	<div class="ad-panel" role="dialog" aria-label="{asset.name} detail" aria-modal="true">
		<header class="ad-header">
			<div class="ad-head-left">
				<span class="ad-symbol">{asset.symbol}</span>
				<span class="ad-name">{asset.name}</span>
				<span class="ad-sector">{asset.sector}</span>
			</div>
			<div class="ad-head-right">
				<span class="ad-value">{fmtAssetValue(asset.lastValue, asset.unit)}</span>
				{#if asset.changePct !== null}
					<span class="ad-change" class:ad-change--up={asset.changePct > 0} class:ad-change--dn={asset.changePct < 0}>
						{(asset.changePct >= 0 ? "+" : "") + asset.changePct.toFixed(2)}%
					</span>
				{/if}
				<button type="button" class="ad-close" onclick={onClose} aria-label="Close">X</button>
			</div>
		</header>

		<div class="ad-stats">
			{#each STAT_TIMEFRAMES as tf}
				<div class="ad-stat">
					<span class="ad-stat-label">{tf}</span>
					<span class="ad-stat-value">{statFor(tf)}</span>
				</div>
			{/each}
		</div>

		<div class="ad-tf-bar">
			{#each TIMEFRAMES as tf}
				<button type="button" class="ad-tf" class:ad-tf--active={activeTimeframe === tf} onclick={() => (activeTimeframe = tf)}>{tf}</button>
			{/each}
		</div>

		<div class="ad-chart-wrap">
			{#if loading}
				<div class="ad-loading">LOADING...</div>
			{:else if filteredSeries.length < 2}
				<div class="ad-loading">NO DATA</div>
			{:else}
				<svg viewBox="0 0 {chartW} {chartH}" class="ad-chart" preserveAspectRatio="none" aria-hidden="true">
					{#if minVal < 0 && maxVal > 0}
						{@const zeroY = chartH - 4 - ((0 - minVal) / valRange) * (chartH - 8)}
						<line x1="0" y1={zeroY} x2={chartW} y2={zeroY} stroke="var(--terminal-fg-tertiary)" stroke-width="0.5" stroke-dasharray="2 3" opacity="0.4" />
					{/if}
					<polyline points={mainPolyline} fill="none" stroke="var(--terminal-accent-amber)" stroke-width="1.5" vector-effect="non-scaling-stroke" />
				</svg>
			{/if}
		</div>
	</div>
{/if}

<style>
	.ad-backdrop {
		position: fixed;
		z-index: 40;
		inset: 0;
		background: transparent;
	}
	.ad-panel {
		position: fixed;
		z-index: 50;
		top: 0;
		right: 0;
		bottom: 0;
		display: flex;
		width: 480px;
		flex-direction: column;
		gap: 1px;
		overflow-y: auto;
		border-left: var(--terminal-border-hairline);
		background: var(--terminal-bg-panel);
		font-family: var(--terminal-font-mono);
		animation: ad-slide-in var(--terminal-motion-tick) var(--terminal-motion-easing-out);
	}
	@keyframes ad-slide-in {
		from {
			transform: translateX(100%);
		}
		to {
			transform: translateX(0);
		}
	}
	.ad-header {
		display: flex;
		align-items: flex-start;
		justify-content: space-between;
		padding: var(--terminal-space-3);
		border-bottom: var(--terminal-border-hairline);
	}
	.ad-head-left,
	.ad-head-right,
	.ad-stat {
		display: flex;
		flex-direction: column;
	}
	.ad-head-right {
		align-items: flex-end;
		gap: 3px;
	}
	.ad-symbol,
	.ad-value {
		color: var(--terminal-fg-primary);
		font-size: var(--terminal-text-14);
		font-weight: 700;
	}
	.ad-name {
		color: var(--terminal-fg-secondary);
		font-size: var(--terminal-text-11);
	}
	.ad-sector,
	.ad-stat-label {
		color: var(--terminal-fg-tertiary);
		font-size: var(--terminal-text-10);
		letter-spacing: var(--terminal-tracking-caps);
	}
	.ad-value,
	.ad-change,
	.ad-stat-value {
		font-variant-numeric: tabular-nums;
	}
	.ad-change {
		color: var(--terminal-fg-tertiary);
		font-size: var(--terminal-text-11);
	}
	.ad-change--up {
		color: var(--terminal-accent-green, #4adf86);
	}
	.ad-change--dn {
		color: var(--terminal-accent-red, #f87171);
	}
	.ad-close {
		margin-top: var(--terminal-space-2);
		padding: 0;
		background: transparent;
		border: none;
		color: var(--terminal-fg-tertiary);
		cursor: pointer;
		font: inherit;
	}
	.ad-stats {
		display: grid;
		grid-template-columns: repeat(5, 1fr);
		gap: 1px;
		background: var(--terminal-bg-panel-sunken);
	}
	.ad-stat {
		align-items: center;
		gap: 2px;
		padding: var(--terminal-space-2);
		background: var(--terminal-bg-panel);
	}
	.ad-stat-value {
		color: var(--terminal-fg-primary);
		font-size: var(--terminal-text-11);
		font-weight: 600;
	}
	.ad-tf-bar {
		display: flex;
		gap: 1px;
		padding: var(--terminal-space-2) var(--terminal-space-3);
	}
	.ad-tf {
		padding: 2px var(--terminal-space-2);
		background: transparent;
		border: var(--terminal-border-hairline);
		color: var(--terminal-fg-tertiary);
		cursor: pointer;
		font: inherit;
		font-size: var(--terminal-text-10);
		letter-spacing: var(--terminal-tracking-caps);
	}
	.ad-tf--active {
		border-color: var(--terminal-accent-amber);
		color: var(--terminal-accent-amber);
	}
	.ad-chart-wrap {
		padding: var(--terminal-space-2) var(--terminal-space-3);
	}
	.ad-chart,
	.ad-loading {
		width: 100%;
		height: 120px;
	}
	.ad-chart {
		display: block;
	}
	.ad-loading {
		display: flex;
		align-items: center;
		justify-content: center;
		color: var(--terminal-fg-tertiary);
		font-size: var(--terminal-text-10);
		letter-spacing: var(--terminal-tracking-caps);
	}
</style>
