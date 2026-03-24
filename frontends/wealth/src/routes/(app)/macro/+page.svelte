<!--
  Macro Intelligence — Dense dashboard with interactive ECharts charting,
  series picker, snapshot regime badge, committee reviews.
  Specs: WM-S1-01 through WM-S1-05
-->
<script lang="ts">
	import { getContext } from "svelte";
	import {
		PageHeader, StatusBadge,
		formatNumber, formatPercent, formatDate,
	} from "@netz/ui";
	import { createClientApiClient } from "$lib/api/client";
	import type { PageData } from "./$types";
	import type {
		MacroScores, RegimeHierarchy, MacroIndicators,
		RegionalScore, GlobalIndicators, TreasuryPoint, OfrPoint,
		BisPoint, ImfPoint, MacroSnapshot, MacroReview,
	} from "$lib/types/macro";
	import { regimeColor } from "$lib/types/macro";
	import MacroChart from "$lib/components/macro/MacroChart.svelte";
	import SeriesPicker, { type IndicatorEntry } from "$lib/components/macro/SeriesPicker.svelte";
	import CommitteeReviews from "$lib/components/macro/CommitteeReviews.svelte";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let { data }: { data: PageData } = $props();

	// Extended fields added in +page.server.ts — cast via any until types regenerated
	let pageData = $derived(data as PageData & Record<string, unknown>);

	let scores = $derived(pageData.scores as MacroScores | null);
	let regime = $derived(pageData.regime as RegimeHierarchy | null);
	let indicators = $derived(pageData.indicators as MacroIndicators | null);
	let snapshot = $derived(pageData.snapshot as MacroSnapshot | null);
	let initialReviews = $derived((pageData.reviews ?? []) as MacroReview[]);
	let actorRole = $derived((pageData.actorRole ?? null) as string | null);

	// ── Derived regions ───────────────────────────────────────────────────

	let regions = $derived(
		scores ? Object.entries(scores.regions) as [string, RegionalScore][] : []
	);
	let globalInd = $derived(scores?.global_indicators ?? null);

	// ── Chart state ──────────────────────────────────────────────────────

	let selectedSeries = $state<Set<string>>(new Set());
	let favorites = $state<Set<string>>(new Set());
	let timeRange = $state<"1M" | "3M" | "6M" | "1Y" | "2Y">("2Y");
	import type { MacroSeries } from "$lib/components/macro/MacroChart.svelte";
	let chartSeries = $state.raw<MacroSeries[]>([]);
	let fetchControllers = $state<Map<string, AbortController>>(new Map());

	let pickerRef: ReturnType<typeof SeriesPicker> | undefined = $state();

	function toggleSeries(id: string) {
		const next = new Set(selectedSeries);
		if (next.has(id)) {
			next.delete(id);
			// Abort pending fetch
			const ctrl = fetchControllers.get(id);
			if (ctrl) { ctrl.abort(); fetchControllers.delete(id); }
			// Remove from chart
			chartSeries = chartSeries.filter((s) => s.id !== id);
		} else {
			if (next.size >= 8) return;
			next.add(id);
			fetchSeriesData(id);
		}
		selectedSeries = next;
	}

	function toggleFavorite(id: string) {
		const next = new Set(favorites);
		if (next.has(id)) next.delete(id);
		else next.add(id);
		favorites = next;
	}

	async function fetchSeriesData(id: string) {
		// Abort previous fetch for same id
		const prev = fetchControllers.get(id);
		if (prev) prev.abort();
		const controller = new AbortController();
		fetchControllers.set(id, controller);

		const entry = pickerRef?.getEntryById(id);
		if (!entry) return;

		try {
			const api = createClientApiClient(getToken);
			let data: [string, number][] = [];
			let frequency = entry.frequency;

			if (entry.source === "treasury") {
				const res = await api.get<{ series: string; data: TreasuryPoint[] }>("/macro/treasury", entry.params);
				if (controller.signal.aborted) return;
				data = (res.data ?? []).map((p) => [p.obs_date, p.value]);
			} else if (entry.source === "ofr") {
				const res = await api.get<{ metric: string; data: OfrPoint[] }>("/macro/ofr", entry.params);
				if (controller.signal.aborted) return;
				data = (res.data ?? []).map((p) => [p.obs_date, p.value]);
			} else if (entry.source === "bis") {
				const res = await api.get<{ country: string; indicator: string; data: BisPoint[] }>("/macro/bis", entry.params);
				if (controller.signal.aborted) return;
				data = (res.data ?? []).map((p) => [p.period, p.value]);
			} else if (entry.source === "imf") {
				const res = await api.get<{ country: string; indicator: string; data: ImfPoint[] }>("/macro/imf", entry.params);
				if (controller.signal.aborted) return;
				// IMF: split into actual + forecast
				const currentYear = new Date().getFullYear();
				const actual = (res.data ?? []).filter((p) => p.year <= currentYear);
				const forecast = (res.data ?? []).filter((p) => p.year >= currentYear);

				const actualSeries: MacroSeries = {
					id: entry.id,
					name: entry.name,
					data: actual.map((p) => [`${p.year}-01-01`, p.value]),
					frequency: "A",
					yAxisIndex: 1,
				};

				if (forecast.length > 0) {
					const forecastSeries: MacroSeries = {
						id: `${entry.id}:forecast`,
						name: `${entry.name} (proj.)`,
						data: forecast.map((p) => [`${p.year}-01-01`, p.value]),
						frequency: "A",
						yAxisIndex: 1,
						lineStyle: "dashed",
					};
					chartSeries = [
						...chartSeries.filter((s) => s.id !== entry.id && s.id !== `${entry.id}:forecast`),
						actualSeries,
						forecastSeries,
					];
				} else {
					chartSeries = [
						...chartSeries.filter((s) => s.id !== entry.id && s.id !== `${entry.id}:forecast`),
						actualSeries,
					];
				}
				fetchControllers.delete(id);
				return;
			}

			if (controller.signal.aborted) return;

			// Determine yAxisIndex based on unit
			const yAxisIndex = entry.unit === "%" || entry.unit === "bps" || entry.unit === "pp" || entry.unit === "%GDP" ? 0 : 1;

			const newSeries: MacroSeries = {
				id: entry.id,
				name: entry.name,
				data,
				frequency,
				yAxisIndex,
			};

			chartSeries = [
				...chartSeries.filter((s) => s.id !== entry.id),
				newSeries,
			];
		} catch (e) {
			if (e instanceof DOMException && e.name === "AbortError") return;
			// Remove failed series silently
			chartSeries = chartSeries.filter((s) => s.id !== id);
		} finally {
			fetchControllers.delete(id);
		}
	}

	// ── Helpers ───────────────────────────────────────────────────────────

	function scoreColor(score: number): string {
		if (score >= 70) return "var(--netz-success)";
		if (score >= 40) return "var(--netz-warning)";
		return "var(--netz-danger)";
	}

	// ── Snapshot regime badge ────────────────────────────────────────────

	function snapshotRegimeLabel(r: RegimeHierarchy): string {
		const regime = r.global_regime;
		if (!regime) return "";
		return regime.replace(/_/g, " ").toUpperCase();
	}

	function snapshotRegimeBadgeColor(r: RegimeHierarchy | null): string {
		if (!r) return "var(--netz-text-muted)";
		return regimeColor(r.global_regime);
	}

	function formatLabel(key: string): string {
		return key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
	}
</script>

<PageHeader title="Macro Intelligence">
	{#snippet actions()}
		{#if regime}
			<span class="macro-regime-badge" style:color={snapshotRegimeBadgeColor(regime)}>
				Regime: {snapshotRegimeLabel(regime)} ●
			</span>
		{/if}
		{#if regime?.regional_regimes}
			{#each Object.entries(regime.regional_regimes) as [region, reg] (region)}
				<span class="macro-region-badge" style:color={regimeColor(reg)}>
					{region}
				</span>
			{/each}
		{/if}
		{#if scores}
			<span class="macro-asof">as of {scores.as_of_date}</span>
		{/if}
	{/snippet}
</PageHeader>

<div class="macro-grid">
	<!-- ═══════════════════════════════════════════════════════════════════ -->
	<!-- ROW 1: Core indicators (VIX, Yield Curve, CPI, Fed Funds)          -->
	<!-- ═══════════════════════════════════════════════════════════════════ -->
	{#if indicators}
		<section class="macro-panel macro-panel--indicators">
			<h3 class="macro-panel-title">Market Indicators</h3>
			<div class="ind-grid">
				<div class="ind-card">
					<span class="ind-label">VIX</span>
					<span class="ind-value">{indicators.vix !== null ? formatNumber(indicators.vix) : "—"}</span>
					{#if indicators.vix_date}
						<span class="ind-date">{indicators.vix_date}</span>
					{/if}
				</div>
				<div class="ind-card">
					<span class="ind-label">10Y-2Y Spread</span>
					<span class="ind-value" style:color={indicators.yield_curve_10y2y !== null && indicators.yield_curve_10y2y < 0 ? "var(--netz-danger)" : "var(--netz-text-primary)"}>
						{indicators.yield_curve_10y2y !== null ? `${(indicators.yield_curve_10y2y * 100).toFixed(0)} bps` : "—"}
					</span>
					{#if indicators.yield_curve_date}
						<span class="ind-date">{indicators.yield_curve_date}</span>
					{/if}
				</div>
				<div class="ind-card">
					<span class="ind-label">CPI YoY</span>
					<span class="ind-value">{indicators.cpi_yoy !== null ? formatPercent(indicators.cpi_yoy) : "—"}</span>
					{#if indicators.cpi_date}
						<span class="ind-date">{indicators.cpi_date}</span>
					{/if}
				</div>
				<div class="ind-card">
					<span class="ind-label">Fed Funds</span>
					<span class="ind-value">{indicators.fed_funds_rate !== null ? formatPercent(indicators.fed_funds_rate) : "—"}</span>
					{#if indicators.fed_funds_date}
						<span class="ind-date">{indicators.fed_funds_date}</span>
					{/if}
				</div>
			</div>
		</section>
	{/if}

	<!-- ═══════════════════════════════════════════════════════════════════ -->
	<!-- ROW 2: Global stress indicators                                    -->
	<!-- ═══════════════════════════════════════════════════════════════════ -->
	{#if globalInd}
		<section class="macro-panel">
			<h3 class="macro-panel-title">Global Stress</h3>
			<div class="ind-grid">
				<div class="ind-card">
					<span class="ind-label">Geopolitical Risk</span>
					<span class="ind-value">{globalInd.geopolitical_risk_score.toFixed(1)}</span>
					<div class="ind-bar-track">
						<div class="ind-bar-fill" style:width="{globalInd.geopolitical_risk_score}%"></div>
					</div>
				</div>
				<div class="ind-card">
					<span class="ind-label">Energy Stress</span>
					<span class="ind-value">{globalInd.energy_stress.toFixed(1)}</span>
					<div class="ind-bar-track">
						<div class="ind-bar-fill" style:width="{globalInd.energy_stress}%"></div>
					</div>
				</div>
				<div class="ind-card">
					<span class="ind-label">Commodity Stress</span>
					<span class="ind-value">{globalInd.commodity_stress.toFixed(1)}</span>
					<div class="ind-bar-track">
						<div class="ind-bar-fill" style:width="{globalInd.commodity_stress}%"></div>
					</div>
				</div>
				<div class="ind-card">
					<span class="ind-label">USD Strength</span>
					<span class="ind-value">{globalInd.usd_strength.toFixed(1)}</span>
					<div class="ind-bar-track">
						<div class="ind-bar-fill" style:width="{globalInd.usd_strength}%"></div>
					</div>
				</div>
			</div>
		</section>
	{/if}

	<!-- ═══════════════════════════════════════════════════════════════════ -->
	<!-- ROW 3: Regional scores + regime                                    -->
	<!-- ═══════════════════════════════════════════════════════════════════ -->
	{#each regions as [regionName, regionData] (regionName)}
		<section class="macro-panel macro-panel--region">
			<div class="region-header">
				<h3 class="region-name">{regionName}</h3>
				{#if regime?.regional_regimes[regionName]}
					<span class="region-regime" style:color={regimeColor(regime.regional_regimes[regionName])}>
						{formatLabel(regime.regional_regimes[regionName])}
					</span>
				{/if}
			</div>

			<div
				class="region-score-hero"
				style:color={scoreColor(regionData.composite_score)}
				title="Composite score 0–100 based on multiple economic indicators. Higher = stronger economic conditions."
			>
				{regionData.composite_score.toFixed(0)}
			</div>

			<div class="region-coverage">
				Coverage: {(regionData.coverage * 100).toFixed(0)}%
			</div>

			{#if Object.keys(regionData.dimensions).length > 0}
				<div class="region-dims">
					{#each Object.entries(regionData.dimensions) as [dimName, dim] (dimName)}
						<div class="region-dim">
							<span class="dim-name">{formatLabel(dimName)}</span>
							<span class="dim-score" style:color={scoreColor(dim.score)}>{dim.score.toFixed(0)}</span>
							<div class="dim-bar-track">
								<div class="dim-bar-fill" style:width="{dim.score}%"></div>
							</div>
						</div>
					{/each}
				</div>
			{/if}
		</section>
	{/each}

	<!-- ═══════════════════════════════════════════════════════════════════ -->
	<!-- ROW 4: Interactive Chart + Series Picker (full width)              -->
	<!-- ═══════════════════════════════════════════════════════════════════ -->
	<section class="macro-panel macro-panel--chart">
		<h3 class="macro-panel-title">Macro Charting</h3>
		<div class="chart-layout">
			<div class="chart-main">
				<MacroChart
					series={chartSeries}
					{timeRange}
					onTimeRangeChange={(r) => (timeRange = r)}
					height={440}
				/>
			</div>
			<SeriesPicker
				bind:this={pickerRef}
				selected={selectedSeries}
				{favorites}
				onToggle={toggleSeries}
				onToggleFavorite={toggleFavorite}
			/>
		</div>
	</section>

	<!-- ═══════════════════════════════════════════════════════════════════ -->
	<!-- ROW 5: Committee Reviews (full width)                              -->
	<!-- ═══════════════════════════════════════════════════════════════════ -->
	<section class="macro-panel macro-panel--full">
		<CommitteeReviews {initialReviews} {actorRole} />
	</section>
</div>

<style>
	/* ── Page grid ────────────────────────────────────────────────────────── */
	.macro-grid {
		display: grid;
		grid-template-columns: repeat(4, 1fr);
		gap: var(--netz-space-stack-sm, 12px);
		padding: var(--netz-space-stack-md, 16px) var(--netz-space-inline-lg, 24px);
		align-content: start;
	}

	.macro-regime-badge {
		font-size: var(--netz-text-small, 0.8125rem);
		font-weight: 700;
		letter-spacing: 0.04em;
	}

	.macro-region-badge {
		font-size: var(--netz-text-label, 0.75rem);
		font-weight: 600;
		letter-spacing: 0.02em;
	}

	.macro-asof {
		font-size: var(--netz-text-label, 0.75rem);
		color: var(--netz-text-muted);
	}

	/* ── Panel base ──────────────────────────────────────────────────────── */
	.macro-panel {
		border: 1px solid var(--netz-border-subtle);
		border-radius: var(--netz-radius-md, 12px);
		background: var(--netz-surface-elevated);
		overflow: hidden;
	}

	.macro-panel--indicators {
		grid-column: 1 / -1;
	}

	.macro-panel--chart {
		grid-column: 1 / -1;
	}

	.macro-panel--full {
		grid-column: 1 / -1;
	}

	.macro-panel--region {
		grid-column: span 1;
	}

	.macro-panel-title {
		padding: var(--netz-space-stack-xs, 8px) var(--netz-space-inline-md, 16px);
		font-size: var(--netz-text-label, 0.75rem);
		font-weight: 600;
		letter-spacing: 0.04em;
		text-transform: uppercase;
		color: var(--netz-text-muted);
		border-bottom: 1px solid var(--netz-border-subtle);
		background: var(--netz-surface-alt);
		margin: 0;
	}

	/* ── Indicator grid ──────────────────────────────────────────────────── */
	.ind-grid {
		display: grid;
		grid-template-columns: repeat(4, 1fr);
		gap: 1px;
		background: var(--netz-border-subtle);
	}

	.ind-card {
		display: flex;
		flex-direction: column;
		gap: 2px;
		padding: var(--netz-space-stack-xs, 10px) var(--netz-space-inline-sm, 12px);
		background: var(--netz-surface-elevated);
	}

	.ind-label {
		font-size: var(--netz-text-label, 0.75rem);
		color: var(--netz-text-muted);
	}

	.ind-value {
		font-size: var(--netz-text-h4, 1.125rem);
		font-weight: 700;
		color: var(--netz-text-primary);
		font-variant-numeric: tabular-nums;
	}

	.ind-date {
		font-size: 10px;
		color: var(--netz-text-muted);
	}

	.ind-bar-track {
		height: 4px;
		background: var(--netz-surface-alt);
		border-radius: 2px;
		overflow: hidden;
		margin-top: 2px;
	}

	.ind-bar-fill {
		height: 100%;
		background: var(--netz-brand-primary);
		border-radius: 2px;
		transition: width 300ms ease;
	}

	/* ── Region cards ────────────────────────────────────────────────────── */
	.region-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: var(--netz-space-stack-xs, 8px) var(--netz-space-inline-md, 16px);
		border-bottom: 1px solid var(--netz-border-subtle);
		background: var(--netz-surface-alt);
	}

	.region-name {
		font-size: var(--netz-text-body, 0.9375rem);
		font-weight: 600;
		color: var(--netz-text-primary);
		margin: 0;
	}

	.region-regime {
		font-size: var(--netz-text-label, 0.75rem);
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.region-score-hero {
		padding: var(--netz-space-stack-xs, 8px) var(--netz-space-inline-md, 16px) 0;
		font-size: var(--netz-text-h2, 1.75rem);
		font-weight: 800;
		font-variant-numeric: tabular-nums;
	}

	.region-coverage {
		padding: 0 var(--netz-space-inline-md, 16px) var(--netz-space-stack-2xs, 4px);
		font-size: var(--netz-text-label, 0.75rem);
		color: var(--netz-text-muted);
	}

	.region-dims {
		border-top: 1px solid var(--netz-border-subtle);
		padding: var(--netz-space-stack-xs, 8px) var(--netz-space-inline-md, 16px);
		display: flex;
		flex-direction: column;
		gap: var(--netz-space-stack-2xs, 4px);
	}

	.region-dim {
		display: grid;
		grid-template-columns: 1fr 30px 60px;
		align-items: center;
		gap: var(--netz-space-inline-xs, 6px);
		font-size: var(--netz-text-label, 0.75rem);
	}

	.dim-name {
		color: var(--netz-text-secondary);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.dim-score {
		font-weight: 600;
		font-variant-numeric: tabular-nums;
		text-align: right;
	}

	.dim-bar-track {
		height: 4px;
		background: var(--netz-surface-alt);
		border-radius: 2px;
		overflow: hidden;
	}

	.dim-bar-fill {
		height: 100%;
		background: var(--netz-brand-primary);
		border-radius: 2px;
	}

	/* ── Chart layout ───────────────────────────────────────────────────── */
	.chart-layout {
		display: flex;
		gap: 0;
	}

	.chart-main {
		flex: 1;
		min-width: 0;
	}

	/* ── Responsive ──────────────────────────────────────────────────────── */
	@media (max-width: 1024px) {
		.macro-grid {
			grid-template-columns: repeat(2, 1fr);
		}

		.chart-layout {
			flex-direction: column;
		}
	}

	@media (max-width: 600px) {
		.macro-grid {
			grid-template-columns: 1fr;
		}

		.macro-panel--indicators {
			grid-column: 1;
		}

		.ind-grid {
			grid-template-columns: repeat(2, 1fr);
		}
	}
</style>
