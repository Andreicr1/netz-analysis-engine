<script lang="ts">
	import { getContext } from "svelte";
	import { formatNumber, formatPercent } from "@investintell/ui";

	interface Props {
		fundId: string | null;
		ticker: string | null;
		label?: string;
	}

	interface NavPoint {
		nav_date: string;
		nav: number;
		return_1d: number | null;
	}

	interface MonthlyPoint {
		month: string;
		compound_return: number;
	}

	interface RollingPoint {
		date: string;
		rolling_vol: number | null;
		rolling_sharpe: number | null;
	}

	interface Distribution {
		bins: number[];
		counts: number[];
		mean: number | null;
	}

	interface RiskMetricsPayload {
		sharpe_1y: number | null;
		volatility_1y: number | null;
		max_drawdown_1y: number | null;
		return_1y: number | null;
		manager_score: number | null;
		blended_momentum_score: number | null;
		peer_count: number | null;
		peer_strategy: string | null;
	}

	interface ReturnsRiskPayload {
		window: string;
		nav_series: NavPoint[];
		monthly_returns: MonthlyPoint[];
		rolling_metrics: RollingPoint[];
		return_distribution: Distribution;
		risk_metrics: RiskMetricsPayload | null;
		disclosure: { has_nav: boolean };
	}

	type WindowKey = "1y" | "3y" | "5y" | "max";

	let { fundId, ticker, label = "—" }: Props = $props();

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const apiBase = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";

	let activeWindow = $state<WindowKey>("3y");
	let data = $state<ReturnsRiskPayload | null>(null);
	let loading = $state(false);
	let error = $state<string | null>(null);

	function percent(value: number | null | undefined, digits = 1): string {
		if (value == null) return "—";
		return formatPercent(Math.abs(value) > 1 ? value / 100 : value, digits);
	}

	function valueClass(value: number | null | undefined): string {
		if (value == null) return "";
		if (value > 0) return "pos";
		if (value < 0) return "neg";
		return "";
	}

	function cleanLabel(value: string | null | undefined): string {
		if (!value) return "—";
		const normalized = value
			.replace(/[_/]+/g, " ")
			.replace(/\s+/g, " ")
			.trim();
		if (!normalized) return "—";
		const tokenMap: Record<string, string> = {
			ETF: "ETF",
			ADR: "ADR",
			REIT: "REIT",
			UCITS: "UCITS",
			NAV: "NAV",
			AUM: "AUM",
			CIK: "CIK",
			"13F": "13F",
			USA: "US",
			US: "US",
			EMEA: "EMEA",
			APAC: "APAC",
		};
		return normalized
			.split(" ")
			.map((word) => {
				const upper = word.toUpperCase();
				if (tokenMap[upper]) return tokenMap[upper];
				if (/^[A-Z0-9-]{2,}$/.test(word)) return upper;
				return word.charAt(0).toUpperCase() + word.slice(1).toLowerCase();
			})
			.join(" ");
	}

	$effect(() => {
		const id = fundId;
		const windowKey = activeWindow;
		if (!id) {
			data = null;
			error = null;
			loading = false;
			return;
		}

		let cancelled = false;
		const controller = new AbortController();
		loading = true;
		error = null;

		(async () => {
			try {
				const token = await getToken();
				const response = await fetch(
					`${apiBase}/wealth/discovery/funds/${encodeURIComponent(id)}/analysis/returns-risk?window=${windowKey}`,
					{
						headers: { Authorization: `Bearer ${token}` },
						signal: controller.signal,
					},
				);
				if (!response.ok) {
					throw new Error(`Returns/Risk fetch failed: HTTP ${response.status}`);
				}
				const payload = (await response.json()) as ReturnsRiskPayload;
				if (cancelled) return;
				data = payload;
			} catch (fetchError: unknown) {
				if (cancelled) return;
				if (fetchError instanceof DOMException && fetchError.name === "AbortError") return;
				error = fetchError instanceof Error ? fetchError.message : "Failed to load Returns/Risk.";
				data = null;
			} finally {
				if (!cancelled) loading = false;
			}
		})();

		return () => {
			cancelled = true;
			controller.abort();
		};
	});

	const hasNav = $derived(!!data?.disclosure?.has_nav && (data?.nav_series.length ?? 0) > 1);

	const normalizedSeries = $derived.by(() => {
		const navSeries = data?.nav_series ?? [];
		if (navSeries.length < 2) return [];
		const firstNav = navSeries[0]?.nav ?? 1;
		let runningPeak = 1;
		return navSeries.map((point) => {
			const ratio = firstNav > 0 ? point.nav / firstNav : 1;
			runningPeak = Math.max(runningPeak, ratio);
			return {
				date: point.nav_date,
				growth: ratio - 1,
				drawdown: ratio / runningPeak - 1,
			};
		});
	});

	function buildPolyline(values: number[], width: number, height: number): string {
		if (values.length === 0) return "";
		const min = Math.min(...values);
		const max = Math.max(...values);
		const span = max - min || 1;
		return values
			.map((value, index) => {
				const x = values.length === 1 ? width / 2 : (index / (values.length - 1)) * width;
				const y = height - ((value - min) / span) * height;
				return `${x},${y}`;
			})
			.join(" ");
	}

	const growthPolyline = $derived(buildPolyline(normalizedSeries.map((point) => point.growth), 820, 250));
	const drawdownPolyline = $derived(buildPolyline(normalizedSeries.map((point) => point.drawdown), 820, 92));

	const recentMonthly = $derived.by(() =>
		[...(data?.monthly_returns ?? [])]
			.slice(-24)
			.reverse(),
	);

	const distributionBars = $derived.by(() => {
		const distribution = data?.return_distribution;
		if (!distribution) return [];
		const maxCount = Math.max(...distribution.counts, 1);
		return distribution.bins.map((bin, index) => ({
			bin,
			count: distribution.counts[index] ?? 0,
			width: `${((distribution.counts[index] ?? 0) / maxCount) * 100}%`,
		}));
	});

	const rollingSummary = $derived.by(() => {
		const metrics = data?.rolling_metrics ?? [];
		if (metrics.length === 0) return [];
		return metrics.slice(-6).reverse();
	});

	const summaryCards = $derived.by(() => {
		const metrics = data?.risk_metrics;
		if (!metrics) return [];
		return [
			{ label: "1Y RETURN", value: percent(metrics.return_1y, 1), className: valueClass(metrics.return_1y) },
			{ label: "VOLATILITY", value: percent(metrics.volatility_1y, 1), className: "" },
			{ label: "SHARPE", value: metrics.sharpe_1y != null ? formatNumber(metrics.sharpe_1y, 2) : "—", className: valueClass(metrics.sharpe_1y) },
			{ label: "MAX DD", value: percent(metrics.max_drawdown_1y, 1), className: "neg" },
			{ label: "SCORE", value: metrics.manager_score != null ? formatNumber(metrics.manager_score, 0) : "—", className: "" },
			{ label: "MOMENTUM", value: metrics.blended_momentum_score != null ? formatNumber(metrics.blended_momentum_score, 0) : "—", className: valueClass(metrics.blended_momentum_score) },
		];
	});
</script>

<div class="rr-root">
	<div class="rr-header">
		<div class="rr-title-block">
			<div class="rr-title">RETURNS / RISK</div>
			<div class="rr-subtitle">{ticker ?? "—"} · {cleanLabel(label)}</div>
		</div>
		<div class="rr-window-bar">
			{#each ([
				{ key: "1y", label: "1Y" },
				{ key: "3y", label: "3Y" },
				{ key: "5y", label: "5Y" },
				{ key: "max", label: "MAX" },
			] as const) as item (item.key)}
				<button
					type="button"
					class="rr-window-btn"
					class:rr-window-btn--active={activeWindow === item.key}
					onclick={() => (activeWindow = item.key)}
				>
					{item.label}
				</button>
			{/each}
		</div>
	</div>

	{#if loading}
		<div class="rr-message">Loading Returns / Risk...</div>
	{:else if error}
		<div class="rr-message rr-message--error">{error}</div>
	{:else if !data}
		<div class="rr-message">No data loaded.</div>
	{:else if !hasNav}
		<div class="rr-message">This fund does not expose public NAV history for advanced return studies.</div>
	{:else}
		<div class="rr-grid">
			<section class="rr-panel rr-hero">
				<div class="rr-panel-head">
					<span>COMPOUND RETURN</span>
					<span>{cleanLabel(data.risk_metrics?.peer_strategy ?? "UNCLASSIFIED")} · {data.risk_metrics?.peer_count ?? 0} PEERS</span>
				</div>
				<div class="rr-hero-chart">
					<svg viewBox="0 0 820 360" preserveAspectRatio="none" role="img" aria-label="Compound return and drawdown">
						<g class="rr-gridline">
							<line x1="0" x2="820" y1="64" y2="64"></line>
							<line x1="0" x2="820" y1="132" y2="132"></line>
							<line x1="0" x2="820" y1="200" y2="200"></line>
							<line x1="0" x2="820" y1="292" y2="292"></line>
						</g>
						<polyline class="rr-growth" points={growthPolyline}></polyline>
						<polyline class="rr-drawdown" points={drawdownPolyline} transform="translate(0, 268)"></polyline>
					</svg>
				</div>
				<div class="rr-hero-footer">
					<div class="rr-range">
						<span>START</span>
						<strong>{normalizedSeries[0]?.date ?? "—"}</strong>
					</div>
					<div class="rr-range">
						<span>LATEST</span>
						<strong>{normalizedSeries[normalizedSeries.length - 1]?.date ?? "—"}</strong>
					</div>
				</div>
			</section>

			<section class="rr-panel rr-summary">
				<div class="rr-panel-head">
					<span>RISK SNAPSHOT</span>
					<span>{activeWindow.toUpperCase()}</span>
				</div>
				<div class="rr-summary-grid">
					{#each summaryCards as card (card.label)}
						<div class="rr-summary-card">
							<div class="rr-summary-label">{card.label}</div>
							<div class={`rr-summary-value ${card.className}`}>{card.value}</div>
						</div>
					{/each}
				</div>
				<div class="rr-mini-table">
					<div class="rr-table-head">
						<span>ROLLING WINDOW</span>
						<span>VOL</span>
						<span>SHARPE</span>
					</div>
					{#each rollingSummary as item (item.date)}
						<div class="rr-table-row">
							<span>{item.date}</span>
							<span>{percent(item.rolling_vol, 1)}</span>
							<span class={valueClass(item.rolling_sharpe)}>{item.rolling_sharpe != null ? formatNumber(item.rolling_sharpe, 2) : "—"}</span>
						</div>
					{/each}
				</div>
			</section>

			<section class="rr-panel rr-monthly">
				<div class="rr-panel-head">
					<span>MONTHLY TAPE</span>
					<span>LAST 24 OBSERVATIONS</span>
				</div>
				<div class="rr-month-grid">
					{#each recentMonthly as month (month.month)}
						<div class={`rr-month-cell ${valueClass(month.compound_return)}`}>
							<span>{month.month}</span>
							<strong>{percent(month.compound_return, 1)}</strong>
						</div>
					{/each}
				</div>
			</section>

			<section class="rr-panel rr-dist">
				<div class="rr-panel-head">
					<span>RETURN DISTRIBUTION</span>
					<span>MEAN {percent(data.return_distribution.mean, 2)}</span>
				</div>
				<div class="rr-dist-list">
					{#each distributionBars as bar, index (index)}
						<div class="rr-dist-row">
							<span class="rr-dist-bin">{percent(bar.bin, 1)}</span>
							<div class="rr-dist-track">
								<div class="rr-dist-fill" style={`width:${bar.width}`}></div>
							</div>
							<span class="rr-dist-count">{bar.count}</span>
						</div>
					{/each}
				</div>
			</section>
		</div>
	{/if}
</div>

<style>
	.rr-root {
		display: flex;
		flex-direction: column;
		width: 100%;
		height: 100%;
		min-width: 0;
		min-height: 0;
		background: var(--terminal-bg-panel);
		font-family: var(--terminal-font-mono);
	}

	.rr-header {
		display: flex;
		align-items: flex-end;
		justify-content: space-between;
		gap: 18px;
		padding: 10px 12px 8px;
		border-bottom: var(--terminal-border-hairline);
	}

	.rr-title-block {
		display: flex;
		flex-direction: column;
		gap: 3px;
		min-width: 0;
	}

	.rr-title,
	.rr-panel-head span:first-child {
		color: var(--terminal-fg-primary);
		font-size: var(--terminal-text-10);
		font-weight: 700;
		letter-spacing: 0.1em;
	}

	.rr-subtitle,
	.rr-panel-head span:last-child,
	.rr-summary-label,
	.rr-table-head,
	.rr-range span,
	.rr-dist-count,
	.rr-dist-bin {
		color: var(--terminal-fg-muted);
		font-size: 9px;
		letter-spacing: 0.06em;
		text-transform: uppercase;
		font-variant-numeric: tabular-nums;
	}

	.rr-window-bar {
		display: flex;
		gap: 6px;
	}

	.rr-window-btn {
		height: 22px;
		padding: 0 10px;
		border: 1px solid var(--terminal-fg-disabled);
		background: transparent;
		color: var(--terminal-fg-secondary);
		font-family: inherit;
		font-size: 9px;
		letter-spacing: 0.08em;
		cursor: pointer;
	}

	.rr-window-btn--active {
		border-color: var(--terminal-accent-amber);
		color: var(--terminal-accent-amber);
	}

	.rr-message {
		display: flex;
		align-items: center;
		justify-content: center;
		height: 100%;
		padding: 24px;
		color: var(--terminal-fg-secondary);
		font-size: var(--terminal-text-11);
		text-align: center;
	}

	.rr-message--error {
		color: var(--terminal-status-error);
	}

	.rr-grid {
		flex: 1;
		min-height: 0;
		display: grid;
		grid-template-columns: minmax(0, 1.7fr) minmax(320px, 0.9fr);
		grid-template-rows: minmax(0, 1.15fr) minmax(240px, 0.85fr);
		gap: 1px;
		background: var(--terminal-fg-disabled);
	}

	.rr-panel {
		min-width: 0;
		min-height: 0;
		overflow: hidden;
		background: var(--terminal-bg-panel);
		display: flex;
		flex-direction: column;
	}

	.rr-panel-head {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 12px;
		padding: 8px 10px 6px;
		border-bottom: var(--terminal-border-hairline);
	}

	.rr-hero-chart {
		flex: 1;
		min-height: 0;
		padding: 12px 14px 8px;
	}

	.rr-hero-chart svg {
		width: 100%;
		height: 100%;
	}

	.rr-gridline line {
		stroke: var(--terminal-fg-disabled);
		stroke-dasharray: 3 6;
	}

	.rr-growth,
	.rr-drawdown {
		fill: none;
		stroke-linecap: round;
		stroke-linejoin: round;
	}

	.rr-growth {
		stroke: var(--terminal-accent-cyan);
		stroke-width: 3;
	}

	.rr-drawdown {
		stroke: var(--terminal-status-error);
		stroke-width: 2;
	}

	.rr-hero-footer {
		display: flex;
		justify-content: space-between;
		gap: 16px;
		padding: 0 14px 10px;
	}

	.rr-range {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.rr-range strong,
	.rr-summary-value,
	.rr-month-cell strong {
		color: var(--terminal-fg-primary);
		font-size: var(--terminal-text-16);
		font-weight: 700;
		font-variant-numeric: tabular-nums;
	}

	.rr-summary-grid {
		display: grid;
		grid-template-columns: repeat(2, minmax(0, 1fr));
		gap: 1px;
		background: var(--terminal-fg-disabled);
		border-bottom: var(--terminal-border-hairline);
	}

	.rr-summary-card {
		padding: 10px 12px;
		background: var(--terminal-bg-panel);
	}

	.rr-mini-table {
		display: flex;
		flex-direction: column;
		gap: 1px;
		padding: 10px;
		background: var(--terminal-fg-disabled);
	}

	.rr-table-head,
	.rr-table-row {
		display: grid;
		grid-template-columns: 1.2fr 0.8fr 0.8fr;
		gap: 10px;
		padding: 6px 8px;
		background: var(--terminal-bg-panel);
	}

	.rr-table-row {
		color: var(--terminal-fg-secondary);
		font-size: var(--terminal-text-10);
	}

	.rr-month-grid {
		display: grid;
		grid-template-columns: repeat(4, minmax(0, 1fr));
		gap: 1px;
		padding: 1px;
		background: var(--terminal-fg-disabled);
		overflow: auto;
	}

	.rr-month-cell {
		display: flex;
		flex-direction: column;
		gap: 8px;
		padding: 10px;
		min-height: 74px;
		background: var(--terminal-bg-panel);
	}

	.rr-dist-list {
		display: flex;
		flex-direction: column;
		gap: 8px;
		padding: 12px 14px;
		overflow: auto;
	}

	.rr-dist-row {
		display: grid;
		grid-template-columns: 62px minmax(0, 1fr) 32px;
		gap: 10px;
		align-items: center;
	}

	.rr-dist-track {
		height: 10px;
		background: var(--terminal-bg-panel-raised);
		border: 1px solid var(--terminal-fg-disabled);
	}

	.rr-dist-fill {
		height: 100%;
		background: linear-gradient(90deg, var(--terminal-accent-violet), var(--terminal-accent-cyan));
	}

	.pos,
	.rr-month-cell.pos strong,
	.rr-table-row .pos {
		color: var(--terminal-status-success);
	}

	.neg,
	.rr-month-cell.neg strong,
	.rr-table-row .neg {
		color: var(--terminal-status-error);
	}

	@media (max-width: 1280px) {
		.rr-grid {
			grid-template-columns: 1fr;
			grid-template-rows: minmax(420px, 1.1fr) minmax(280px, 0.8fr) minmax(260px, 0.8fr) minmax(260px, 0.8fr);
		}
	}
</style>
