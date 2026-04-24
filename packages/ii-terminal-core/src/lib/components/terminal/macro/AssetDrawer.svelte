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
	const chartH = 260;
	const chartW = 680;
	const minVal = $derived(filteredSeries.length ? Math.min(...filteredSeries.map((point) => point.value)) : 0);
	const maxVal = $derived(filteredSeries.length ? Math.max(...filteredSeries.map((point) => point.value)) : 1);
	const valRange = $derived(maxVal - minVal || 1);
	const mainPolyline = $derived(toChartPts(filteredSeries));
	const latestValue = $derived(series.length ? series[series.length - 1]!.value : asset?.lastValue ?? null);
	const seriesHigh = $derived(series.length ? Math.max(...series.map((point) => point.value)) : null);
	const seriesLow = $derived(series.length ? Math.min(...series.map((point) => point.value)) : null);

	function statFor(tf: (typeof STAT_TIMEFRAMES)[number]): string {
		const points = series.filter((point) => new Date(point.obs_date) >= cutoff(tf));
		if (points.length < 2) return "-";
		const first = points[0]!.value;
		const last = points[points.length - 1]!.value;
		const change = ((last - first) / Math.abs(first)) * 100;
		return `${change >= 0 ? "+" : ""}${change.toFixed(2)}%`;
	}

	function statTone(value: string): "up" | "dn" | "flat" {
		if (value.startsWith("+")) return "up";
		if (value.startsWith("-")) return "dn";
		return "flat";
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
	<button type="button" class="ad-backdrop" onclick={onClose} aria-label="Close asset detail"></button>

	<div class="ad-panel" role="dialog" aria-label="{asset.name} detail" aria-modal="true">
		<header class="ad-header">
			<div class="ad-head-left">
				<span class="ad-name">{asset.name}</span>
				<span class="ad-meta">{asset.symbol} · {asset.sector} · {asset.unit || "IDX"}</span>
			</div>
			<div class="ad-head-right">
				<span class="ad-value">{fmtAssetValue(latestValue, asset.unit)}</span>
				{#if asset.changePct !== null}
					<span class="ad-change" class:ad-change--up={asset.changePct > 0} class:ad-change--dn={asset.changePct < 0}>
						{(asset.changePct >= 0 ? "+" : "") + asset.changePct.toFixed(2)}%
					</span>
				{/if}
				<button type="button" class="ad-close" onclick={onClose} aria-label="Close">X</button>
			</div>
		</header>

		<div class="ad-body">
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
						<g class="ad-grid">
							<line x1="0" y1="54" x2={chartW} y2="54" />
							<line x1="0" y1="130" x2={chartW} y2="130" />
							<line x1="0" y1="206" x2={chartW} y2="206" />
						</g>
						{#if minVal < 0 && maxVal > 0}
							{@const zeroY = chartH - 4 - ((0 - minVal) / valRange) * (chartH - 8)}
							<line x1="0" y1={zeroY} x2={chartW} y2={zeroY} stroke="var(--ii-text-muted)" stroke-width="0.5" stroke-dasharray="2 3" opacity="0.4" />
						{/if}
						<polyline points={mainPolyline} fill="none" stroke="var(--ii-brand-primary)" stroke-width="1.7" vector-effect="non-scaling-stroke" />
					</svg>
				{/if}
			</div>

			<div class="ad-stats">
				{#each STAT_TIMEFRAMES as tf}
					{@const stat = statFor(tf)}
					<div class="ad-stat">
						<span class="ad-stat-label">{tf}</span>
						<span class="ad-stat-value" class:ad-stat-value--up={statTone(stat) === "up"} class:ad-stat-value--dn={statTone(stat) === "dn"}>{stat}</span>
					</div>
				{/each}
				<div class="ad-stat">
					<span class="ad-stat-label">52W HIGH</span>
					<span class="ad-stat-value">{fmtAssetValue(seriesHigh, asset.unit)}</span>
				</div>
				<div class="ad-stat">
					<span class="ad-stat-label">52W LOW</span>
					<span class="ad-stat-value">{fmtAssetValue(seriesLow, asset.unit)}</span>
				</div>
				<div class="ad-stat">
					<span class="ad-stat-label">LAST</span>
					<span class="ad-stat-value">{fmtAssetValue(latestValue, asset.unit)}</span>
				</div>
			</div>

			<section class="ad-notes" aria-label="Macro notes">
				<h2>MACRO NOTES</h2>
				<p>· Regime sensitivity: HIGH to inflation shocks</p>
				<p>· Current quadrant exposure: OVERHEATING - typically bearish for duration</p>
				<p>· 60-day correlation with DXY: 0.35</p>
			</section>
		</div>

		<footer class="ad-footer">
			<button type="button" class="ad-action" onclick={onClose}>CLOSE</button>
			<button type="button" class="ad-action">CREATE ALERT</button>
			<button type="button" class="ad-action ad-action--primary">ADD TO WATCHLIST</button>
		</footer>
	</div>
{/if}

<style>
	.ad-backdrop {
		position: fixed;
		z-index: 40;
		inset: 0;
		padding: 0;
		border: 0;
		background: transparent;
	}
	.ad-panel {
		position: fixed;
		z-index: 50;
		top: 0;
		right: 0;
		bottom: 0;
		display: flex;
		width: min(760px, 92vw);
		flex-direction: column;
		overflow: hidden;
		border-left: 1px solid var(--ii-border-strong);
		background: var(--ii-surface);
		box-shadow: -16px 0 36px rgba(0, 0, 0, 0.22);
		font-family: var(--ii-font-mono);
		animation: ad-slide-in 120ms ease-out;
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
		min-height: 132px;
		padding: 32px 28px 22px;
		border-bottom: 1px solid var(--ii-border-subtle);
	}
	.ad-head-left,
	.ad-head-right,
	.ad-stat {
		display: flex;
		flex-direction: column;
	}
	.ad-head-right {
		align-items: flex-end;
		gap: 6px;
	}
	.ad-name,
	.ad-value {
		color: var(--ii-text-primary);
		font-size: 29px;
		font-weight: 400;
		letter-spacing: 0;
	}
	.ad-meta,
	.ad-stat-label {
		color: var(--ii-text-muted);
		font-size: 12px;
		letter-spacing: var(--ii-terminal-tr-caps);
	}
	.ad-value,
	.ad-change,
	.ad-stat-value {
		font-variant-numeric: tabular-nums;
	}
	.ad-change {
		color: var(--ii-text-muted);
		font-size: 14px;
	}
	.ad-change--up {
		color: var(--ii-success);
	}
	.ad-change--dn {
		color: var(--ii-danger);
	}
	.ad-close {
		margin-top: 12px;
		padding: 0;
		background: transparent;
		border: none;
		color: var(--ii-text-muted);
		cursor: pointer;
		font: inherit;
	}
	.ad-body {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
	}
	.ad-tf-bar {
		display: flex;
		gap: 3px;
		padding: 16px 28px 0;
	}
	.ad-tf {
		height: 28px;
		min-width: 48px;
		padding: 0 12px;
		background: var(--ii-surface-alt);
		border: 1px solid var(--ii-border-subtle);
		color: var(--ii-text-muted);
		cursor: pointer;
		font: inherit;
		font-size: 12px;
		letter-spacing: var(--ii-terminal-tr-caps);
	}
	.ad-tf--active {
		border-color: var(--ii-brand-primary);
		color: var(--ii-brand-primary);
	}
	.ad-chart-wrap {
		padding: 18px 28px 8px;
	}
	.ad-chart,
	.ad-loading {
		width: 100%;
		height: 300px;
	}
	.ad-chart {
		display: block;
	}
	.ad-grid line {
		stroke: var(--ii-terminal-hair);
		stroke-dasharray: 2 5;
		stroke-width: 0.6;
		opacity: 0.8;
	}
	.ad-loading {
		display: flex;
		align-items: center;
		justify-content: center;
		border: 1px solid var(--ii-border-subtle);
		color: var(--ii-text-muted);
		font-size: 10px;
		letter-spacing: var(--ii-terminal-tr-caps);
	}
	.ad-stats {
		display: grid;
		grid-template-columns: repeat(4, minmax(0, 1fr));
		gap: 1px;
		padding: 0 0 0;
		border-top: 1px solid var(--ii-border-subtle);
		border-bottom: 1px solid var(--ii-border-subtle);
		background: var(--ii-border-subtle);
	}
	.ad-stat {
		gap: 10px;
		min-height: 78px;
		padding: 16px 22px;
		background: var(--ii-surface-alt);
	}
	.ad-stat-value {
		color: var(--ii-text-primary);
		font-size: 20px;
		font-weight: 700;
	}
	.ad-stat-value--up {
		color: var(--ii-success);
	}
	.ad-stat-value--dn {
		color: var(--ii-danger);
	}
	.ad-notes {
		padding: 24px 28px;
		border-bottom: 1px solid var(--ii-border-subtle);
	}
	.ad-notes h2 {
		margin: 0 0 14px;
		color: var(--ii-text-secondary);
		font-size: 13px;
		letter-spacing: var(--ii-terminal-tr-caps);
	}
	.ad-notes p {
		margin: 8px 0;
		color: var(--ii-text-primary);
		font-size: 15px;
		line-height: 1.45;
	}
	.ad-notes :global(.ad-em) {
		color: var(--ii-brand-primary);
	}
	.ad-footer {
		display: flex;
		flex-shrink: 0;
		justify-content: flex-end;
		gap: 12px;
		padding: 18px 20px;
		border-top: 1px solid var(--ii-border-subtle);
		background: var(--ii-surface);
	}
	.ad-action {
		height: 42px;
		padding: 0 28px;
		border: 1px solid var(--ii-border-subtle);
		background: var(--ii-surface-alt);
		color: var(--ii-text-secondary);
		cursor: pointer;
		font: inherit;
		font-size: 13px;
		font-weight: 700;
		letter-spacing: var(--ii-terminal-tr-caps);
	}
	.ad-action--primary {
		border-color: var(--ii-brand-primary);
		background: var(--ii-brand-primary);
		color: var(--ii-bg);
	}
</style>
