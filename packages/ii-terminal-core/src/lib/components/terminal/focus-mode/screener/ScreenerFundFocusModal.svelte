<!--
  ScreenerFundFocusModal -- constrained fund focus for the screener page.

  1040px x 88vh quick-view modal with SVG performance and composite radar.
-->
<script lang="ts">
	import { getContext, onMount } from "svelte";
	import { formatCurrency, formatNumber, formatPercent } from "@investintell/ui";
	import { createClientApiClient } from "../../../../api/client";

	interface Props {
		fundId: string;
		fundLabel: string;
		ticker: string | null;
		instrumentId: string | null;
		onClose: () => void;
	}

	let { fundId, fundLabel, ticker, instrumentId, onClose }: Props = $props();

	const getToken = getContext<() => Promise<string>>("netz:getToken");
	const api = createClientApiClient(getToken);

	interface FundCatalogItem {
		name: string;
		manager_name: string | null;
		aum: number | null;
		strategy_label: string | null;
		fund_type: string | null;
		expense_ratio_pct: number | null;
		avg_annual_return_1y: number | null;
		avg_annual_return_10y: number | null;
		manager_score: number | null;
		blended_momentum_score: number | null;
		max_drawdown: number | null;
		sharpe_ratio: number | null;
		volatility: number | null;
	}

	interface NavBar {
		date: string;
		value: number;
	}

	let detail = $state<FundCatalogItem | null>(null);
	let navBars = $state<NavBar[]>([]);
	let loadingDetail = $state(true);
	let loadingNav = $state(false);

	$effect(() => {
		const id = fundId;
		let cancelled = false;
		loadingDetail = true;
		api
			.get<FundCatalogItem>(`/screener/catalog/detail/${encodeURIComponent(id)}`)
			.then((res) => {
				if (cancelled) return;
				detail = res ?? null;
				loadingDetail = false;
			})
			.catch(() => {
				if (cancelled) return;
				detail = null;
				loadingDetail = false;
			});
		return () => {
			cancelled = true;
		};
	});

	$effect(() => {
		const symbol = ticker;
		void instrumentId;
		if (!symbol) {
			navBars = [];
			return;
		}
		let cancelled = false;
		loadingNav = true;
		const start = new Date(Date.now() - 365 * 5 * 86_400_000)
			.toISOString()
			.slice(0, 10);
		api
			.get<{ bars: Array<{ timestamp: string; close: number | null }> }>(
				`/market-data/historical/${encodeURIComponent(symbol)}`,
				{ start_date: start },
			)
			.then((res) => {
				if (cancelled) return;
				navBars = (res.bars ?? [])
					.filter((bar) => bar.close != null)
					.map((bar) => ({
						date: bar.timestamp.slice(0, 10),
						value: Number(bar.close),
					}));
				loadingNav = false;
			})
			.catch(() => {
				if (cancelled) return;
				navBars = [];
				loadingNav = false;
			});
		return () => {
			cancelled = true;
		};
	});

	const PERIODS: Array<{ label: string; days: number }> = [
		{ label: "1M", days: 30 },
		{ label: "3M", days: 91 },
		{ label: "6M", days: 182 },
		{ label: "1Y", days: 365 },
		{ label: "3Y", days: 365 * 3 },
		{ label: "5Y", days: 365 * 5 },
	];

	const periodStats = $derived.by(() => {
		if (navBars.length < 2) {
			return PERIODS.map((period) => ({ label: period.label, returnPct: null as number | null }));
		}
		const last = navBars[navBars.length - 1];
		return PERIODS.map((period) => {
			const cutoff = new Date(Date.now() - period.days * 86_400_000)
				.toISOString()
				.slice(0, 10);
			const ref = navBars.find((bar) => bar.date >= cutoff);
			if (!last || !ref || ref.value === 0) {
				return { label: period.label, returnPct: null };
			}
			return {
				label: period.label,
				returnPct: (last.value - ref.value) / ref.value,
			};
		});
	});

	const CHART_W = 320;
	const CHART_H = 120;

	const perfChart = $derived.by(() => {
		if (navBars.length < 2) return { area: "", line: "", isUp: true };
		const values = navBars.map((bar) => bar.value);
		const minValue = Math.min(...values);
		const maxValue = Math.max(...values);
		const range = maxValue - minValue || 1;
		const points = values.map((value, index) => {
			const x = (index / (values.length - 1)) * CHART_W;
			const y = CHART_H - ((value - minValue) / range) * CHART_H;
			return `${x.toFixed(1)},${y.toFixed(1)}`;
		});
		const line = "M " + points.join(" L ");
		return {
			area: `${line} L ${CHART_W},${CHART_H} L 0,${CHART_H} Z`,
			line,
			isUp: values[values.length - 1]! >= values[0]!,
		};
	});

	const AXES = ["RETURN", "MOMENTUM", "RISK ADJ", "DD CTL", "COST EFF", "CONSISTENCY"] as const;
	const RADAR_W = 200;
	const RADAR_H = 160;
	const CX = RADAR_W / 2;
	const CY = RADAR_H / 2;
	const R = 65;
	const N = AXES.length;

	function radarPt(index: number, radius: number) {
		const angle = (index / N) * 2 * Math.PI - Math.PI / 2;
		return {
			x: CX + radius * Math.cos(angle),
			y: CY + radius * Math.sin(angle),
		};
	}

	function clampScore(value: number): number {
		return Math.min(100, Math.max(0, value));
	}

	function asDecimalPercent(value: number | null | undefined): number | null {
		if (value == null) return null;
		return Math.abs(value) > 1 ? value / 100 : value;
	}

	function peerSubjectLeft(
		value: number | null,
		p25: number | null,
		p75: number | null,
		fallbackP25: number,
		fallbackP75: number,
	): string {
		if (value == null) return "0%";
		const low = p25 ?? fallbackP25;
		const high = p75 ?? fallbackP75;
		const range = high - low || Math.abs(fallbackP75 - fallbackP25) || 1;
		const pct = Math.max(0, Math.min(100, ((value - low) / range) * 100));
		return `${pct}%`;
	}

	const axisScores = $derived.by((): number[] => {
		if (!detail) return Array(N).fill(50);
		const returnDecimal = asDecimalPercent(detail.avg_annual_return_1y);
		const drawdownDecimal = asDecimalPercent(detail.max_drawdown);
		const expensePct = detail.expense_ratio_pct ?? null;
		return [
			returnDecimal != null ? clampScore((returnDecimal + 0.1) * 500) : 50,
			detail.blended_momentum_score ?? 50,
			detail.sharpe_ratio != null ? clampScore((detail.sharpe_ratio + 0.5) * 50) : 50,
			drawdownDecimal != null ? clampScore((1 + drawdownDecimal / 0.5) * 100) : 50,
			expensePct != null ? clampScore(100 - expensePct * 50) : 50,
			detail.manager_score ?? 50,
		];
	});

	const radarPath = $derived.by(() => {
		const points = axisScores.map((score, index) => {
			const p = radarPt(index, (score / 100) * R);
			return `${p.x.toFixed(1)},${p.y.toFixed(1)}`;
		});
		return "M " + points.join(" L ") + " Z";
	});

	const w52 = $derived.by(() => {
		const cutoff = new Date(Date.now() - 365 * 86_400_000).toISOString().slice(0, 10);
		const values = navBars.filter((bar) => bar.date >= cutoff).map((bar) => bar.value);
		if (values.length === 0) return null;
		return { high: Math.max(...values), low: Math.min(...values) };
	});

	interface PeerMetricsResponse {
		strategy_label: string | null;
		peer_count: number;
		subject_sharpe: number | null;
		subject_drawdown: number | null;
		peer_sharpe_p25: number | null;
		peer_sharpe_p50: number | null;
		peer_sharpe_p75: number | null;
		peer_drawdown_p25: number | null;
		peer_drawdown_p50: number | null;
		peer_drawdown_p75: number | null;
		top_peers: Array<{
			ticker: string;
			name: string;
			sharpe_ratio: number | null;
			max_drawdown: number | null;
		}>;
	}

	interface DDReportSummary {
		id: string;
		version: number;
		status: string;
		confidence_score: number | null;
		decision_anchor: string | null;
		is_current: boolean;
		created_at: string;
	}

	let peerMetrics = $state<PeerMetricsResponse | null>(null);
	let loadingPeer = $state(false);
	let ddReports = $state<DDReportSummary[]>([]);
	let loadingDD = $state(false);
	let rightTab = $state<"profile" | "analysis">("profile");

	$effect(() => {
		const id = fundId;
		if (!id) return;
		let cancelled = false;
		loadingPeer = true;
		api
			.get<PeerMetricsResponse>(`/screener/peer-metrics/${encodeURIComponent(id)}`)
			.then((res) => {
				if (cancelled) return;
				peerMetrics = res;
				loadingPeer = false;
			})
			.catch(() => {
				if (cancelled) return;
				peerMetrics = null;
				loadingPeer = false;
			});
		return () => {
			cancelled = true;
		};
	});

	$effect(() => {
		const iid = instrumentId;
		if (!iid) {
			ddReports = [];
			return;
		}
		let cancelled = false;
		loadingDD = true;
		api
			.get<DDReportSummary[]>(`/dd-reports/funds/${encodeURIComponent(iid)}`)
			.then((res) => {
				if (cancelled) return;
				ddReports = res ?? [];
				loadingDD = false;
			})
			.catch(() => {
				if (cancelled) return;
				ddReports = [];
				loadingDD = false;
			});
		return () => {
			cancelled = true;
		};
	});

	function percentText(value: number | null | undefined, decimals = 2): string {
		const decimal = asDecimalPercent(value);
		return decimal == null ? "\u2014" : formatPercent(decimal, decimals);
	}

	function closeOnEscape(event: KeyboardEvent) {
		if (event.key === "Escape") onClose();
	}

	onMount(() => {
		document.addEventListener("keydown", closeOnEscape);
		return () => document.removeEventListener("keydown", closeOnEscape);
	});
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<!-- svelte-ignore a11y_click_events_have_key_events -->
<div class="sfm-overlay" onclick={onClose} role="dialog" aria-modal="true" aria-label={fundLabel} tabindex="-1">
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<!-- svelte-ignore a11y_click_events_have_key_events -->
	<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
	<div class="sfm-modal" onclick={(event) => event.stopPropagation()} role="document">
		<div class="sfm-hero">
			<div>
				<h1 class="sfm-name">{detail?.name ?? fundLabel}</h1>
				<div class="sfm-meta">
					{#if loadingDetail}<span>Loading...</span>{/if}
					{#if detail?.manager_name}<span>{detail.manager_name}</span>{/if}
					{#if detail?.strategy_label}<span class="sfm-accent">{detail.strategy_label}</span>{/if}
					{#if detail?.fund_type}<span>{detail.fund_type.replace("_", " ").toUpperCase()}</span>{/if}
					{#if ticker}<span class="sfm-accent">{ticker}</span>{/if}
				</div>
			</div>
			{#if detail?.aum != null}
				<div class="sfm-aum">
					<span class="sfm-aum-val">{formatNumber(detail.aum / 1_000_000, 0)}M</span>
					<span class="sfm-aum-label">AUM</span>
				</div>
			{/if}
		</div>

		<div class="sfm-kpi-grid">
			{#each [
				{ label: "1Y RETURN", value: percentText(detail?.avg_annual_return_1y, 2), tone: (detail?.avg_annual_return_1y ?? 0) >= 0 ? "up" : "down" },
				{ label: "10Y RETURN", value: percentText(detail?.avg_annual_return_10y, 2), tone: (detail?.avg_annual_return_10y ?? 0) >= 0 ? "up" : "down" },
				{ label: "SHARPE", value: detail?.sharpe_ratio != null ? formatNumber(detail.sharpe_ratio, 2) : "\u2014", tone: "" },
				{ label: "MAX DD", value: percentText(detail?.max_drawdown, 1), tone: "down" },
				{ label: "EXPENSE", value: detail?.expense_ratio_pct != null ? formatPercent(detail.expense_ratio_pct / 100, 2) : "\u2014", tone: "" },
				{ label: "SCORE", value: detail?.manager_score != null ? formatNumber(detail.manager_score, 0) : "\u2014", tone: "" },
			] as kpi (kpi.label)}
				<div class="sfm-kpi">
					<span class="sfm-kpi-label">{kpi.label}</span>
					<span class="sfm-kpi-value {kpi.tone}">{kpi.value}</span>
				</div>
			{/each}
		</div>

		<div class="sfm-body">
			<div class="sfm-section">
				<h3 class="sfm-sh">PERFORMANCE</h3>
				<div class="sfm-perf-chart">
					{#if loadingNav}
						<div class="sfm-chart-empty">Loading...</div>
					{:else if perfChart.line}
						<svg viewBox="0 0 {CHART_W} {CHART_H}" preserveAspectRatio="none" width="100%" height="100%">
							<defs>
								<linearGradient id="sfm-g-{fundId}" x1="0" y1="0" x2="0" y2="1">
									<stop offset="0%" stop-color={perfChart.isUp ? "var(--ii-success,#3DD39A)" : "var(--ii-danger,#FF5C7A)"} stop-opacity="0.35" />
									<stop offset="100%" stop-color={perfChart.isUp ? "var(--ii-success,#3DD39A)" : "var(--ii-danger,#FF5C7A)"} stop-opacity="0" />
								</linearGradient>
							</defs>
							<path d={perfChart.area} fill="url(#sfm-g-{fundId})" />
							<path d={perfChart.line} fill="none" stroke={perfChart.isUp ? "var(--ii-success,#3DD39A)" : "var(--ii-danger,#FF5C7A)"} stroke-width="1.5" />
						</svg>
					{:else}
						<div class="sfm-chart-empty">No NAV data</div>
					{/if}
				</div>

				<div class="sfm-period-grid">
					{#each periodStats as stat (stat.label)}
						<div class="sfm-period-row">
							<span class="sfm-period-lbl">{stat.label}</span>
							<span
								class="sfm-period-val"
								class:up={(stat.returnPct ?? 0) >= 0}
								class:down={(stat.returnPct ?? 0) < 0}
							>
								{stat.returnPct != null ? formatPercent(stat.returnPct, 2, "en-US", true) : "\u2014"}
							</span>
						</div>
					{/each}
				</div>

				{#if w52}
					<div class="sfm-52w">
						<span class="sfm-52w-lbl">52W</span>
						<span class="sfm-52w-val down">{formatCurrency(w52.low)}</span>
						<span class="sfm-52w-sep">-</span>
						<span class="sfm-52w-val up">{formatCurrency(w52.high)}</span>
					</div>
				{/if}
			</div>

			<div class="sfm-section sfm-section--right">
				<div class="sfm-rtabs" role="tablist" aria-label="Fund detail panel">
					<button
						type="button"
						class="sfm-rtab"
						class:sfm-rtab--active={rightTab === "profile"}
						role="tab"
						aria-selected={rightTab === "profile"}
						onclick={() => (rightTab = "profile")}
					>
						COMPOSITE PROFILE
					</button>
					<button
						type="button"
						class="sfm-rtab"
						class:sfm-rtab--active={rightTab === "analysis"}
						role="tab"
						aria-selected={rightTab === "analysis"}
						onclick={() => (rightTab = "analysis")}
					>
						DD ANALYSIS
					</button>
				</div>

				{#if rightTab === "profile"}
					<div class="sfm-radar-wrap">
						<svg viewBox="0 0 {RADAR_W} {RADAR_H}" width={RADAR_W} height={RADAR_H}>
							{#each [0.25, 0.5, 0.75, 1.0] as pct}
								{@const pts = Array.from({ length: N }, (_, index) => {
									const p = radarPt(index, pct * R);
									return `${p.x.toFixed(1)},${p.y.toFixed(1)}`;
								})}
								<polygon points={pts.join(" ")} fill="none" stroke="var(--ii-border-subtle,#1A2458)" stroke-width="1" />
							{/each}
							{#each Array.from({ length: N }, (_, index) => index) as index (index)}
								{@const endpoint = radarPt(index, R)}
								<line x1={CX} y1={CY} x2={endpoint.x} y2={endpoint.y} stroke="var(--ii-border,#1A2458)" stroke-width="1" />
							{/each}
							<path d={radarPath} fill="var(--ii-brand-primary,#FF965A)" fill-opacity="0.18" stroke="var(--ii-brand-primary,#FF965A)" stroke-width="1.5" />
							{#each AXES as label, index (label)}
								{@const labelPoint = radarPt(index, R + 14)}
								<text x={labelPoint.x} y={labelPoint.y} text-anchor="middle" dominant-baseline="middle" font-family="var(--ii-font-mono)" font-size="7" fill="var(--ii-text-muted,#6D7DA6)">
									{label}
								</text>
							{/each}
						</svg>
					</div>

					<div class="sfm-axis-bars">
						{#each AXES as label, index (label)}
							{@const score = axisScores[index] ?? 0}
							<div class="sfm-axis-row">
								<span class="sfm-axis-lbl">{label}</span>
								<span class="sfm-axis-bar-wrap">
									<span class="sfm-axis-bar" style:width="{score}%"></span>
								</span>
								<span class="sfm-axis-val">{formatNumber(score, 0)}</span>
							</div>
						{/each}
					</div>
				{:else}
					{#if peerMetrics && peerMetrics.peer_count > 0}
						<div class="sfm-peer-section">
							<h4 class="sfm-peer-hd">
								PEER GROUP
								{#if peerMetrics.strategy_label}
									<span class="sfm-peer-label">{peerMetrics.strategy_label}</span>
								{/if}
								<span class="sfm-peer-count">n={peerMetrics.peer_count}</span>
							</h4>

							<div class="sfm-peer-metric">
								<span class="sfm-peer-metric-name">SHARPE</span>
								<div class="sfm-peer-bar-wrap">
									<div class="sfm-peer-range" style:left="0%" style:width="100%"></div>
									{#if peerMetrics.subject_sharpe !== null}
										<div
											class="sfm-peer-subject"
											style:left={peerSubjectLeft(peerMetrics.subject_sharpe, peerMetrics.peer_sharpe_p25, peerMetrics.peer_sharpe_p75, 0, 1)}
										></div>
									{/if}
								</div>
								<div class="sfm-peer-vals">
									<span>p25: {peerMetrics.peer_sharpe_p25 != null ? formatNumber(peerMetrics.peer_sharpe_p25, 2) : "\u2014"}</span>
									<span>med: {peerMetrics.peer_sharpe_p50 != null ? formatNumber(peerMetrics.peer_sharpe_p50, 2) : "\u2014"}</span>
									<span class:sfm-peer-val-up={(peerMetrics.subject_sharpe ?? 0) >= (peerMetrics.peer_sharpe_p50 ?? 0)}>
										you: {peerMetrics.subject_sharpe != null ? formatNumber(peerMetrics.subject_sharpe, 2) : "\u2014"}
									</span>
								</div>
							</div>

							<div class="sfm-peer-metric">
								<span class="sfm-peer-metric-name">MAX DD</span>
								<div class="sfm-peer-bar-wrap">
									<div class="sfm-peer-range" style:left="0%" style:width="100%"></div>
									{#if peerMetrics.subject_drawdown !== null}
										<div
											class="sfm-peer-subject sfm-peer-subject--down"
											style:left={peerSubjectLeft(peerMetrics.subject_drawdown, peerMetrics.peer_drawdown_p25, peerMetrics.peer_drawdown_p75, -0.3, 0)}
										></div>
									{/if}
								</div>
								<div class="sfm-peer-vals">
									<span>p25: {percentText(peerMetrics.peer_drawdown_p25, 1)}</span>
									<span>med: {percentText(peerMetrics.peer_drawdown_p50, 1)}</span>
									<span class:sfm-peer-val-up={(peerMetrics.subject_drawdown ?? -1) >= (peerMetrics.peer_drawdown_p50 ?? -1)}>
										you: {percentText(peerMetrics.subject_drawdown, 1)}
									</span>
								</div>
							</div>
						</div>
					{:else if loadingPeer}
						<div class="sfm-analysis-empty">Loading peer data...</div>
					{:else}
						<div class="sfm-analysis-empty">No peer group data available.</div>
					{/if}

					<div class="sfm-dd-section">
						<h4 class="sfm-peer-hd">DD REPORTS</h4>
						{#if loadingDD}
							<div class="sfm-analysis-empty">Loading...</div>
						{:else if ddReports.length === 0}
							<div class="sfm-analysis-empty">No DD reports generated yet.</div>
						{:else}
							{#each ddReports as report (report.id)}
								<div class="sfm-dd-row">
									<span class="sfm-dd-status sfm-dd-status--{report.status.toLowerCase()}">{report.status}</span>
									<span class="sfm-dd-ver">v{report.version}</span>
									<span class="sfm-dd-score">{report.confidence_score != null ? formatNumber(Number(report.confidence_score), 0) : "\u2014"}</span>
									<span class="sfm-dd-anchor">{report.decision_anchor ?? ""}</span>
								</div>
							{/each}
						{/if}
					</div>
				{/if}
			</div>
		</div>

		<button type="button" class="sfm-close" onclick={onClose} aria-label="Close">
			[ ESC - CLOSE ]
		</button>
	</div>
</div>

<style>
	.sfm-overlay {
		position: fixed;
		inset: 0;
		z-index: 9999;
		display: flex;
		align-items: center;
		justify-content: center;
		background: rgba(5, 8, 26, 0.72);
	}

	.sfm-modal {
		position: relative;
		display: flex;
		flex-direction: column;
		width: 1040px;
		max-width: 98vw;
		height: 88vh;
		max-height: 88vh;
		overflow: hidden;
		border: 1px solid var(--ii-border, #1A2458);
		background: var(--ii-surface, #0B1230);
		font-family: var(--ii-font-mono, var(--terminal-font-mono));
	}

	.sfm-hero {
		display: grid;
		grid-template-columns: 1fr auto;
		flex-shrink: 0;
		gap: 24px;
		padding: 18px 20px;
		border-bottom: 1px solid var(--ii-border-subtle, var(--terminal-fg-muted));
		background: var(--ii-surface-alt, var(--terminal-bg-panel-sunken));
	}

	.sfm-name {
		margin: 0 0 4px;
		color: var(--ii-text-primary, var(--terminal-fg-primary));
		font-family: var(--ii-font-sans, var(--terminal-font-sans, var(--terminal-font-mono)));
		font-size: 22px;
		font-weight: 300;
	}

	.sfm-meta {
		display: flex;
		flex-wrap: wrap;
		gap: 14px;
		margin-top: 6px;
		color: var(--ii-text-muted, var(--terminal-fg-muted));
		font-size: 10px;
		letter-spacing: 0.08em;
		text-transform: uppercase;
	}

	.sfm-accent {
		color: var(--ii-brand-primary, var(--terminal-accent-amber));
		font-weight: 600;
	}

	.sfm-aum {
		text-align: right;
	}

	.sfm-aum-val {
		display: block;
		color: var(--ii-text-primary, var(--terminal-fg-primary));
		font-size: 20px;
		font-weight: 600;
		font-variant-numeric: tabular-nums;
	}

	.sfm-aum-label,
	.sfm-kpi-label,
	.sfm-sh,
	.sfm-period-lbl,
	.sfm-52w-lbl,
	.sfm-axis-lbl {
		color: var(--ii-text-muted, var(--terminal-fg-muted));
		font-size: 9px;
		letter-spacing: 0.08em;
		text-transform: uppercase;
	}

	.sfm-kpi-grid {
		display: grid;
		grid-template-columns: repeat(6, minmax(0, 1fr));
		flex-shrink: 0;
		gap: 1px;
		padding: 1px;
		background: var(--ii-border-subtle, var(--terminal-fg-muted));
	}

	.sfm-kpi {
		padding: 10px 12px;
		background: var(--ii-surface, var(--terminal-bg-panel));
	}

	.sfm-kpi-label {
		display: block;
	}

	.sfm-kpi-value {
		display: block;
		margin-top: 4px;
		color: var(--ii-text-primary, var(--terminal-fg-primary));
		font-size: 18px;
		font-weight: 600;
		font-variant-numeric: tabular-nums;
	}

	.sfm-kpi-value.up,
	.sfm-period-val.up,
	.sfm-52w-val.up {
		color: var(--ii-success, var(--terminal-status-success));
	}

	.sfm-kpi-value.down,
	.sfm-period-val.down,
	.sfm-52w-val.down {
		color: var(--ii-danger, var(--terminal-status-error));
	}

	.sfm-body {
		display: grid;
		grid-template-columns: 1.4fr 1fr;
		flex: 1;
		min-height: 0;
		overflow: hidden;
		gap: 1px;
		background: var(--ii-border-subtle, var(--terminal-fg-muted));
	}

	.sfm-section {
		min-height: 0;
		overflow-y: auto;
		padding: 14px 18px;
		background: var(--ii-surface, var(--terminal-bg-panel));
	}

	.sfm-sh {
		margin: 0 0 10px;
		font-size: 10px;
		font-weight: 700;
	}

	.sfm-perf-chart {
		height: 120px;
		margin-bottom: 14px;
		border: 1px solid var(--ii-border-subtle, var(--terminal-fg-muted));
	}

	.sfm-chart-empty {
		display: flex;
		align-items: center;
		justify-content: center;
		height: 100%;
		color: var(--ii-text-muted, var(--terminal-fg-muted));
		font-size: 10px;
	}

	.sfm-period-grid {
		display: grid;
		grid-template-columns: repeat(3, minmax(0, 1fr));
		gap: 4px 8px;
		margin-bottom: 12px;
	}

	.sfm-period-row {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 3px 0;
		border-bottom: 1px solid var(--ii-terminal-hair, rgba(102, 137, 188, 0.14));
	}

	.sfm-period-val {
		font-size: 11px;
		font-weight: 600;
		font-variant-numeric: tabular-nums;
	}

	.sfm-52w {
		display: flex;
		align-items: center;
		gap: 8px;
		margin-top: 8px;
		font-size: 10px;
	}

	.sfm-52w-val {
		font-weight: 600;
		font-variant-numeric: tabular-nums;
	}

	.sfm-52w-sep {
		color: var(--ii-text-muted, var(--terminal-fg-muted));
	}

	.sfm-radar-wrap {
		display: flex;
		justify-content: center;
		padding: 8px 0 14px;
	}

	.sfm-axis-bars {
		display: flex;
		flex-direction: column;
		gap: 6px;
		padding-top: 12px;
		border-top: 1px solid var(--ii-border-subtle, var(--terminal-fg-muted));
	}

	.sfm-axis-row {
		display: grid;
		grid-template-columns: 90px 1fr 32px;
		align-items: center;
		gap: 10px;
	}

	.sfm-axis-lbl {
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.sfm-axis-bar-wrap {
		position: relative;
		display: block;
		height: 8px;
		overflow: hidden;
		border: 1px solid var(--ii-border-subtle, var(--terminal-fg-muted));
		border-radius: 1px;
		background: var(--ii-surface-alt, var(--terminal-bg-panel-sunken));
	}

	.sfm-axis-bar {
		position: absolute;
		inset: 0 auto 0 0;
		background: var(--ii-brand-primary, var(--terminal-accent-amber));
		transition: width 200ms ease;
	}

	.sfm-axis-val {
		color: var(--ii-text-primary, var(--terminal-fg-primary));
		font-size: 12px;
		font-weight: 600;
		font-variant-numeric: tabular-nums;
		text-align: right;
	}

	.sfm-close {
		position: absolute;
		top: 12px;
		right: 12px;
		padding: 4px 10px;
		border: 1px solid var(--ii-border-subtle, var(--terminal-fg-muted));
		background: transparent;
		color: var(--ii-text-muted, var(--terminal-fg-muted));
		font-family: var(--ii-font-mono, var(--terminal-font-mono));
		font-size: 10px;
		letter-spacing: 0.08em;
		cursor: pointer;
	}

	.sfm-close:hover {
		border-color: var(--ii-brand-primary, var(--terminal-accent-amber));
		color: var(--ii-brand-primary, var(--terminal-accent-amber));
	}

	.sfm-section--right {
		display: flex;
		flex-direction: column;
		min-height: 0;
	}

	.sfm-rtabs {
		display: flex;
		flex-shrink: 0;
		gap: 1px;
		margin-bottom: 12px;
		background: var(--ii-border-subtle, var(--terminal-fg-muted));
	}

	.sfm-rtab {
		flex: 1;
		padding: 6px 0;
		border: none;
		background: var(--ii-surface-alt, var(--terminal-bg-panel-sunken));
		color: var(--ii-text-muted, var(--terminal-fg-muted));
		font-family: var(--ii-font-mono, var(--terminal-font-mono));
		font-size: 9px;
		font-weight: 700;
		letter-spacing: 0.08em;
		text-transform: uppercase;
		cursor: pointer;
	}

	.sfm-rtab--active {
		background: var(--ii-surface, var(--terminal-bg-panel));
		color: var(--ii-brand-primary, var(--terminal-accent-amber));
	}

	.sfm-peer-section {
		margin-bottom: 14px;
	}

	.sfm-peer-hd {
		display: flex;
		align-items: center;
		gap: 8px;
		margin: 0 0 8px;
		color: var(--ii-text-muted, var(--terminal-fg-muted));
		font-size: 9px;
		font-weight: 700;
		letter-spacing: 0.08em;
		text-transform: uppercase;
	}

	.sfm-peer-label {
		overflow: hidden;
		color: var(--ii-brand-primary, var(--terminal-accent-amber));
		font-weight: 600;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.sfm-peer-count {
		margin-left: auto;
		color: var(--ii-text-muted, var(--terminal-fg-muted));
	}

	.sfm-peer-metric {
		margin-bottom: 10px;
	}

	.sfm-peer-metric-name {
		display: block;
		margin-bottom: 4px;
		color: var(--ii-text-muted, var(--terminal-fg-muted));
		font-size: 9px;
		letter-spacing: 0.06em;
		text-transform: uppercase;
	}

	.sfm-peer-bar-wrap {
		position: relative;
		height: 10px;
		margin-bottom: 4px;
		overflow: hidden;
		border: 1px solid var(--ii-border-subtle, var(--terminal-fg-muted));
		background: var(--ii-surface-alt, var(--terminal-bg-panel-sunken));
	}

	.sfm-peer-range {
		position: absolute;
		top: 0;
		bottom: 0;
		background: var(--ii-border-subtle, rgba(102, 137, 188, 0.26));
	}

	.sfm-peer-subject {
		position: absolute;
		top: 0;
		bottom: 0;
		width: 2px;
		background: var(--ii-brand-primary, var(--terminal-accent-amber));
	}

	.sfm-peer-subject--down {
		background: var(--ii-danger, var(--terminal-status-error));
	}

	.sfm-peer-vals {
		display: flex;
		gap: 10px;
		color: var(--ii-text-muted, var(--terminal-fg-muted));
		font-size: 9px;
		font-variant-numeric: tabular-nums;
	}

	.sfm-peer-val-up {
		color: var(--ii-success, var(--terminal-status-success));
		font-weight: 700;
	}

	.sfm-dd-section {
		padding-top: 10px;
		border-top: 1px solid var(--ii-border-subtle, var(--terminal-fg-muted));
	}

	.sfm-dd-row {
		display: grid;
		grid-template-columns: 88px 28px 36px minmax(0, 1fr);
		gap: 8px;
		align-items: center;
		padding: 3px 0;
		border-bottom: 1px solid var(--ii-terminal-hair, rgba(102, 137, 188, 0.14));
		font-family: var(--ii-font-mono, var(--terminal-font-mono));
		font-size: 10px;
	}

	.sfm-dd-status {
		overflow: hidden;
		font-size: 9px;
		font-weight: 700;
		letter-spacing: 0.06em;
		text-overflow: ellipsis;
		text-transform: uppercase;
		white-space: nowrap;
	}

	.sfm-dd-status--approved {
		color: var(--ii-success, var(--terminal-status-success));
	}

	.sfm-dd-status--pending,
	.sfm-dd-status--pending_approval {
		color: var(--ii-warning, var(--terminal-status-warn));
	}

	.sfm-dd-status--rejected,
	.sfm-dd-status--failed {
		color: var(--ii-danger, var(--terminal-status-error));
	}

	.sfm-dd-status--generating {
		color: var(--ii-text-muted, var(--terminal-fg-muted));
	}

	.sfm-dd-ver {
		color: var(--ii-text-muted, var(--terminal-fg-muted));
		font-size: 9px;
	}

	.sfm-dd-score {
		color: var(--ii-text-primary, var(--terminal-fg-primary));
		font-weight: 600;
		font-variant-numeric: tabular-nums;
	}

	.sfm-dd-anchor {
		overflow: hidden;
		color: var(--ii-text-muted, var(--terminal-fg-muted));
		font-size: 9px;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.sfm-analysis-empty {
		padding: 12px 0;
		color: var(--ii-text-muted, var(--terminal-fg-muted));
		font-family: var(--ii-font-mono, var(--terminal-font-mono));
		font-size: 10px;
	}
</style>
