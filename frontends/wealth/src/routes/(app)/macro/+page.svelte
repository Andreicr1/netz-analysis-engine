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

	// ── Expandable region state ─────────────────────────────────────────

	let expandedRegion = $state<string | null>(null);

	// Expand first region once data loads
	$effect(() => {
		if (regions.length > 0 && expandedRegion === null) {
			expandedRegion = regions[0]?.[0] ?? null;
		}
	});

	function toggleRegion(regionName: string) {
		expandedRegion = expandedRegion === regionName ? null : regionName;
	}

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

	const REGION_DISPLAY: Record<string, string> = {
		US: "United States",
		EUROPE: "Europe",
		ASIA: "Asia",
		EM: "Emerging Markets",
	};

	function regionDisplayName(key: string): string {
		return REGION_DISPLAY[key] ?? key;
	}

	function scoreColor(score: number): string {
		if (score >= 70) return "#22c55e";
		if (score >= 40) return "#fe9a00";
		return "#ff2056";
	}

	function stressBarColor(value: number): string {
		if (value > 80) return "#ff2056";
		if (value >= 40) return "#fe9a00";
		return "#155dfc";
	}

	// ── Snapshot regime badge ────────────────────────────────────────────

	function snapshotRegimeLabel(r: RegimeHierarchy): string {
		const regime = r.global_regime;
		if (!regime) return "";
		return regime.replace(/_/g, " ").toUpperCase();
	}

	function formatLabel(key: string): string {
		return key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
	}
</script>

<!-- ── Header ────────────────────────────────────────────────────────── -->
<div class="macro-page">
	<header class="macro-header">
		<h1 class="macro-title">Macro Intelligence</h1>
		<div class="macro-header-right">
			{#if regime}
				<span class="macro-regime-line">
					REGIME: <strong class="regime-value">{snapshotRegimeLabel(regime)}</strong>
				</span>
				<span class="macro-regime-separator">&#x2022;</span>
			{/if}
			{#if regime?.regional_regimes}
				{#each Object.keys(regime.regional_regimes) as region (region)}
					<span class="macro-region-tag">{region}</span>
				{/each}
			{/if}
			{#if scores}
				<span class="macro-asof">AS OF {scores.as_of_date}</span>
			{/if}
		</div>
	</header>

	<!-- ── Card 1: Market Indicators ─────────────────────────────────── -->
	{#if indicators}
		<section class="fi-card">
			<div class="fi-card-header">
				<span class="fi-card-title">MARKET INDICATORS</span>
			</div>
			<div class="ind-row">
				<div class="ind-col">
					<span class="ind-label">VIX</span>
					<span class="ind-value">{indicators.vix !== null ? formatNumber(indicators.vix) : "—"}</span>
					{#if indicators.vix_date}
						<span class="ind-date">{indicators.vix_date}</span>
					{/if}
				</div>
				<div class="ind-col">
					<span class="ind-label">10Y-2Y SPREAD</span>
					<span class="ind-value">{indicators.yield_curve_10y2y !== null ? formatNumber(indicators.yield_curve_10y2y * 100, 0) + " bps" : "—"}</span>
					{#if indicators.yield_curve_date}
						<span class="ind-date">{indicators.yield_curve_date}</span>
					{/if}
				</div>
				<div class="ind-col">
					<span class="ind-label">CPI YOY</span>
					<span class="ind-value">{indicators.cpi_yoy !== null ? formatPercent(indicators.cpi_yoy) : "—"}</span>
					{#if indicators.cpi_date}
						<span class="ind-date">{indicators.cpi_date}</span>
					{/if}
				</div>
				<div class="ind-col ind-col--last">
					<span class="ind-label">FED FUNDS</span>
					<span class="ind-value">{indicators.fed_funds_rate !== null ? formatPercent(indicators.fed_funds_rate) : "—"}</span>
					{#if indicators.fed_funds_date}
						<span class="ind-date">{indicators.fed_funds_date}</span>
					{/if}
				</div>
			</div>
		</section>
	{/if}

	<!-- ── Card 2: Global Stress Index ───────────────────────────────── -->
	{#if globalInd}
		<section class="fi-card">
			<div class="fi-card-header">
				<svg class="fi-icon" viewBox="0 0 16 16" fill="none"><circle cx="8" cy="8" r="7" stroke="#62748e" stroke-width="1.5"/><path d="M8 4v5M8 11v1" stroke="#62748e" stroke-width="1.5" stroke-linecap="round"/></svg>
				<span class="fi-card-title">GLOBAL STRESS INDEX</span>
			</div>
			<div class="ind-row">
				{#each [
					{ label: "Geopolitical Risk", value: globalInd.geopolitical_risk_score },
					{ label: "Energy Stress", value: globalInd.energy_stress },
					{ label: "Commodity Stress", value: globalInd.commodity_stress },
					{ label: "USD Strength", value: globalInd.usd_strength },
				] as item, i (item.label)}
					<div class="ind-col stress-col" class:ind-col--last={i === 3}>
						<span class="stress-label">{item.label}</span>
						<div class="stress-value-row">
							<span class="stress-value">{item.value.toFixed(0)}</span>
							<span class="stress-max">/ 100</span>
						</div>
						<div class="stress-bar-track">
							<div class="stress-bar-fill" style:width="{item.value}%" style:background={stressBarColor(item.value)}></div>
						</div>
					</div>
				{/each}
			</div>
		</section>
	{/if}

	<!-- ── Section 3: Regional Analysis ──────────────────────────────── -->
	{#if regions.length > 0}
		<div class="section-label">REGIONAL ANALYSIS</div>

		{#each regions as [regionName, regionData] (regionName)}
			{@const isExpanded = expandedRegion === regionName}
			{@const dimEntries = Object.entries(regionData.dimensions)}
			<section
				class="region-card"
				class:region-card--expanded={isExpanded}
			>
				<!-- Region header row -->
				<button class="region-header" onclick={() => toggleRegion(regionName)}>
					<div class="region-header-left">
						<span class="region-name">{regionDisplayName(regionName)}</span>
						{#if regime?.regional_regimes[regionName]}
							<span class="region-regime-badge">{regime.regional_regimes[regionName].replace(/_/g, " ").toUpperCase()}</span>
						{/if}
						<span class="region-coverage">COVERAGE {(regionData.coverage * 100).toFixed(0)}%</span>
					</div>
					<div class="region-header-right">
						<div class="region-score-group">
							<span class="region-score-label">MACRO SCORE</span>
							<span class="region-score-value" style:color={scoreColor(regionData.composite_score)}>
								{regionData.composite_score.toFixed(0)}
							</span>
						</div>
						<div class="region-chevron" class:region-chevron--open={isExpanded}>
							<svg viewBox="0 0 20 20" fill="none" width="20" height="20"><path d="M6 8l4 4 4-4" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>
						</div>
					</div>
				</button>

				<!-- Collapsed mini bars -->
				{#if !isExpanded && dimEntries.length > 0}
					<div class="region-mini-bars">
						{#each dimEntries.slice(0, 3) as [, dim]}
							<div class="mini-bar-track">
								<div class="mini-bar-fill" style:width="{dim.score}%"></div>
							</div>
						{/each}
					</div>
				{/if}

				<!-- Expanded body -->
				{#if isExpanded}
					<div class="region-body">
						<div class="region-body-inner">
							<!-- Left: Score Breakdown -->
							<div class="breakdown-section">
								<span class="breakdown-title">MACRO SCORE BREAKDOWN</span>
								<div class="breakdown-grid">
									{#each dimEntries as [dimName, dim] (dimName)}
										<div class="breakdown-item">
											<div class="breakdown-item-header">
												<span class="breakdown-dim-name">{formatLabel(dimName)}</span>
												<span class="breakdown-dim-score" style:color={scoreColor(dim.score)}>{dim.score.toFixed(0)}</span>
											</div>
											<div class="breakdown-bar-track">
												<div class="breakdown-bar-fill" style:width="{dim.score}%"></div>
											</div>
										</div>
									{/each}
								</div>
							</div>

							<!-- Right: Context & Analysis -->
							<div class="analysis-card">
								<div class="analysis-card-header">
									<svg class="fi-icon" viewBox="0 0 16 16" fill="none"><rect x="2" y="2" width="12" height="12" rx="2" stroke="#62748e" stroke-width="1.2"/><path d="M5 6h6M5 8.5h4" stroke="#62748e" stroke-width="1.2" stroke-linecap="round"/></svg>
									<span class="analysis-card-title">CONTEXT & ANALYSIS</span>
								</div>
								<div class="analysis-card-body">
									{#if regionData.analysis_text}
										<p class="analysis-text">{regionData.analysis_text}</p>
									{:else}
										<p class="analysis-text analysis-text--empty">Analysis not available for this region.</p>
									{/if}
								</div>
								<div class="analysis-card-footer">
									<a href="/macro/reports/{regionName.toLowerCase()}" class="analysis-link">VIEW FULL DETAILED REPORT</a>
								</div>
							</div>
						</div>
					</div>
				{/if}
			</section>
		{/each}
	{/if}

	<!-- ── Interactive Chart + Series Picker ──────────────────────────── -->
	<section class="fi-card fi-card--full">
		<div class="fi-card-header">
			<span class="fi-card-title">MACRO CHARTING</span>
		</div>
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

	<!-- ── Committee Reviews ──────────────────────────────────────────── -->
	<section class="fi-card fi-card--full">
		<CommitteeReviews {initialReviews} {actorRole} />
	</section>
</div>

<style>
	/* ── Page layout ──────────────────────────────────────────────────── */
	.macro-page {
		display: flex;
		flex-direction: column;
		gap: 16px;
		padding: 24px;
	}

	/* ── Header ──────────────────────────────────────────────────────── */
	.macro-header {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
		flex-wrap: wrap;
		gap: 12px;
	}

	.macro-title {
		font-size: 28px;
		font-weight: 800;
		color: #1d293d;
		margin: 0;
		line-height: 1.2;
	}

	.macro-header-right {
		display: flex;
		align-items: center;
		gap: 8px;
		flex-wrap: wrap;
	}

	.macro-regime-line {
		font-size: 11px;
		font-weight: 700;
		text-transform: uppercase;
		color: #62748e;
		letter-spacing: 0.03em;
	}

	.regime-value {
		color: #1d293d;
		font-weight: 900;
	}

	.macro-regime-separator {
		color: #62748e;
		font-size: 11px;
	}

	.macro-region-tag {
		font-size: 11px;
		font-weight: 700;
		color: #62748e;
		text-transform: uppercase;
		letter-spacing: 0.03em;
	}

	.macro-asof {
		font-size: 11px;
		font-weight: 600;
		color: #62748e;
		text-transform: uppercase;
	}

	/* ── Card base ───────────────────────────────────────────────────── */
	.fi-card {
		background: #fff;
		border-radius: 16px;
		box-shadow: 0 2px 8px rgba(0,0,0,0.02);
		overflow: hidden;
	}

	.fi-card--full {
		width: 100%;
	}

	.fi-card-header {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 10px 20px;
		background: rgba(248,250,252,0.5);
		border-bottom: 1px solid #f1f5f9;
	}

	.fi-card-title {
		font-size: 11px;
		font-weight: 700;
		text-transform: uppercase;
		color: #62748e;
		letter-spacing: 1.1px;
	}

	.fi-icon {
		width: 14px;
		height: 14px;
		flex-shrink: 0;
	}

	/* ── Indicator row (shared by Market Indicators & Stress) ────────── */
	.ind-row {
		display: grid;
		grid-template-columns: repeat(4, 1fr);
	}

	.ind-col {
		display: flex;
		flex-direction: column;
		gap: 2px;
		padding: 14px 20px;
		border-right: 1px solid #f1f5f9;
	}

	.ind-col--last {
		border-right: none;
	}

	.ind-label {
		font-size: 10px;
		font-weight: 700;
		text-transform: uppercase;
		color: #90a1b9;
		letter-spacing: 0.5px;
	}

	.ind-value {
		font-size: 24px;
		font-weight: 900;
		color: #1d293d;
		font-variant-numeric: tabular-nums;
		line-height: 1.2;
	}

	.ind-date {
		font-size: 10px;
		font-weight: 500;
		color: #90a1b9;
	}

	/* ── Stress Index specifics ──────────────────────────────────────── */
	.stress-col {
		gap: 4px;
	}

	.stress-label {
		font-size: 11px;
		font-weight: 700;
		text-transform: uppercase;
		color: #90a1b9;
		letter-spacing: 0.55px;
	}

	.stress-value-row {
		display: flex;
		align-items: baseline;
		gap: 4px;
	}

	.stress-value {
		font-size: 30px;
		font-weight: 900;
		color: #1d293d;
		font-variant-numeric: tabular-nums;
		line-height: 1.1;
	}

	.stress-max {
		font-size: 10px;
		font-weight: 700;
		color: #90a1b9;
	}

	.stress-bar-track {
		height: 6px;
		background: #f1f5f9;
		border-radius: 9999px;
		overflow: hidden;
		margin-top: 2px;
	}

	.stress-bar-fill {
		height: 100%;
		border-radius: 9999px;
		transition: width 300ms ease;
	}

	/* ── Section label ───────────────────────────────────────────────── */
	.section-label {
		font-size: 11px;
		font-weight: 700;
		text-transform: uppercase;
		color: #62748e;
		letter-spacing: 1.1px;
		padding-top: 8px;
	}

	/* ── Region cards ────────────────────────────────────────────────── */
	.region-card {
		background: #fff;
		border-radius: 16px;
		box-shadow: 0 2px 8px rgba(0,0,0,0.02);
		overflow: hidden;
		border: 1px solid transparent;
		transition: border-color 0.15s, box-shadow 0.15s;
	}

	.region-card--expanded {
		border-color: #bedbff;
		box-shadow: 0 0 0 1px #eff6ff, 0 4px 6px -1px rgba(0,0,0,0.1);
	}

	.region-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		width: 100%;
		padding: 16px 20px;
		background: transparent;
		border: none;
		cursor: pointer;
		text-align: left;
		font-family: inherit;
	}

	.region-header:hover {
		background: rgba(248,250,252,0.5);
	}

	.region-header-left {
		display: flex;
		align-items: center;
		gap: 12px;
	}

	.region-name {
		font-size: 20px;
		font-weight: 700;
		color: #1d293d;
	}

	.region-regime-badge {
		font-size: 10px;
		font-weight: 700;
		color: #90a1b9;
		background: #f1f5f9;
		padding: 2px 8px;
		border-radius: 4px;
		letter-spacing: 0.03em;
	}

	.region-coverage {
		font-size: 10px;
		font-weight: 600;
		color: #90a1b9;
		letter-spacing: 0.03em;
	}

	.region-header-right {
		display: flex;
		align-items: center;
		gap: 16px;
	}

	.region-score-group {
		display: flex;
		flex-direction: column;
		align-items: flex-end;
		gap: 0;
	}

	.region-score-label {
		font-size: 10px;
		font-weight: 700;
		text-transform: uppercase;
		color: #90a1b9;
		letter-spacing: 0.5px;
	}

	.region-score-value {
		font-size: 36px;
		font-weight: 900;
		font-variant-numeric: tabular-nums;
		line-height: 1;
	}

	.region-chevron {
		width: 32px;
		height: 32px;
		display: flex;
		align-items: center;
		justify-content: center;
		background: #eff6ff;
		border-radius: 9999px;
		color: #155dfc;
		transition: transform 0.2s;
	}

	.region-chevron--open {
		transform: rotate(180deg);
	}

	/* ── Collapsed mini bars ─────────────────────────────────────────── */
	.region-mini-bars {
		display: flex;
		gap: 8px;
		padding: 0 20px 14px;
	}

	.mini-bar-track {
		flex: 1;
		height: 4px;
		background: #f1f5f9;
		border-radius: 9999px;
		overflow: hidden;
	}

	.mini-bar-fill {
		height: 100%;
		background: #cad5e2;
		border-radius: 9999px;
		opacity: 0.5;
	}

	/* ── Expanded body ───────────────────────────────────────────────── */
	.region-body {
		background: rgba(248,250,252,0.5);
		border-top: 1px solid #f1f5f9;
		padding: 20px;
	}

	.region-body-inner {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 20px;
	}

	/* ── Score Breakdown ─────────────────────────────────────────────── */
	.breakdown-section {
		display: flex;
		flex-direction: column;
		gap: 12px;
	}

	.breakdown-title {
		font-size: 11px;
		font-weight: 700;
		text-transform: uppercase;
		color: #62748e;
		letter-spacing: 1.1px;
	}

	.breakdown-grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 12px;
	}

	.breakdown-item {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}

	.breakdown-item-header {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
	}

	.breakdown-dim-name {
		font-size: 11px;
		font-weight: 700;
		color: #45556c;
		text-transform: capitalize;
	}

	.breakdown-dim-score {
		font-size: 14px;
		font-weight: 900;
		font-variant-numeric: tabular-nums;
	}

	.breakdown-bar-track {
		height: 8px;
		background: rgba(226,232,240,0.6);
		border-radius: 9999px;
		overflow: hidden;
	}

	.breakdown-bar-fill {
		height: 100%;
		background: #155dfc;
		border-radius: 9999px;
		transition: width 300ms ease;
	}

	/* ── Analysis card ───────────────────────────────────────────────── */
	.analysis-card {
		background: #fff;
		border: 1px solid #e2e8f0;
		border-radius: 14px;
		box-shadow: 0 1px 3px rgba(0,0,0,0.04);
		display: flex;
		flex-direction: column;
	}

	.analysis-card-header {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 12px 16px;
		border-bottom: 1px solid #f1f5f9;
	}

	.analysis-card-title {
		font-size: 11px;
		font-weight: 700;
		text-transform: uppercase;
		color: #62748e;
		letter-spacing: 1.1px;
	}

	.analysis-card-body {
		padding: 16px;
		flex: 1;
	}

	.analysis-text {
		font-size: 14px;
		font-weight: 500;
		color: #45556c;
		line-height: 22.75px;
		margin: 0;
	}

	.analysis-text--empty {
		color: #90a1b9;
		font-style: italic;
	}

	.analysis-card-footer {
		padding: 12px 16px;
		border-top: 1px solid #f1f5f9;
	}

	.analysis-link {
		font-size: 12px;
		font-weight: 700;
		text-transform: uppercase;
		color: #155dfc;
		text-decoration: none;
		letter-spacing: 0.03em;
	}

	.analysis-link:hover {
		text-decoration: underline;
	}

	/* ── Chart layout ────────────────────────────────────────────────── */
	.chart-layout {
		display: flex;
		gap: 0;
	}

	.chart-main {
		flex: 1;
		min-width: 0;
	}

	/* ── Responsive ──────────────────────────────────────────────────── */
	@media (max-width: 1024px) {
		.ind-row {
			grid-template-columns: repeat(2, 1fr);
		}

		.region-body-inner {
			grid-template-columns: 1fr;
		}

		.chart-layout {
			flex-direction: column;
		}
	}

	@media (max-width: 600px) {
		.macro-page {
			padding: 16px;
		}

		.macro-header {
			flex-direction: column;
			gap: 8px;
		}

		.ind-row {
			grid-template-columns: 1fr;
		}

		.ind-col {
			border-right: none;
			border-bottom: 1px solid #f1f5f9;
		}

		.ind-col--last {
			border-bottom: none;
		}

		.breakdown-grid {
			grid-template-columns: 1fr;
		}

		.region-header-left {
			flex-wrap: wrap;
		}

		.region-name {
			font-size: 16px;
		}
	}
</style>
