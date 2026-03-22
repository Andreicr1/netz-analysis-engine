<!--
  Macro Intelligence — Dense read-only dashboard consuming hypertables.
  FRED, Treasury, OFR, BIS, IMF data visualized in CSS Grid panels.
  Design: data-first density, --netz-* tokens only, no competing UI.
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
	} from "$lib/types/macro";
	import { regimeColor, freshnessColor } from "$lib/types/macro";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let { data }: { data: PageData } = $props();

	let scores = $derived(data.scores as MacroScores | null);
	let regime = $derived(data.regime as RegimeHierarchy | null);
	let indicators = $derived(data.indicators as MacroIndicators | null);

	// ── Derived regions ───────────────────────────────────────────────────

	let regions = $derived(
		scores ? Object.entries(scores.regions) as [string, RegionalScore][] : []
	);
	let globalInd = $derived(scores?.global_indicators ?? null);

	// ── Treasury panel state ──────────────────────────────────────────────

	let treasurySeries = $state("YIELD_CURVE");
	let treasuryData = $state<TreasuryPoint[]>([]);
	let treasuryLoading = $state(false);

	const TREASURY_SERIES = ["YIELD_CURVE", "10Y_RATE", "2Y_RATE", "30Y_RATE", "FED_FUNDS"];

	async function fetchTreasury(series: string) {
		treasuryLoading = true;
		try {
			const api = createClientApiClient(getToken);
			const res = await api.get<{ series: string; data: TreasuryPoint[] }>(`/macro/treasury`, { series });
			treasuryData = res.data ?? [];
		} catch {
			treasuryData = [];
		} finally {
			treasuryLoading = false;
		}
	}

	$effect(() => {
		fetchTreasury(treasurySeries);
	});

	// ── OFR panel state ───────────────────────────────────────────────────

	let ofrMetric = $state("HF_LEVERAGE");
	let ofrData = $state<OfrPoint[]>([]);
	let ofrLoading = $state(false);

	const OFR_METRICS = ["HF_AUM", "HF_LEVERAGE", "HF_REPO_STRESS"];

	async function fetchOfr(metric: string) {
		ofrLoading = true;
		try {
			const api = createClientApiClient(getToken);
			const res = await api.get<{ metric: string; data: OfrPoint[] }>(`/macro/ofr`, { metric });
			ofrData = res.data ?? [];
		} catch {
			ofrData = [];
		} finally {
			ofrLoading = false;
		}
	}

	$effect(() => {
		fetchOfr(ofrMetric);
	});

	// ── Helpers ───────────────────────────────────────────────────────────

	function scoreColor(score: number): string {
		if (score >= 70) return "var(--netz-success)";
		if (score >= 40) return "var(--netz-warning)";
		return "var(--netz-danger)";
	}

	function sparkMini(data: { value: number }[], maxCount = 30): { h: number }[] {
		const tail = data.slice(-maxCount);
		if (tail.length === 0) return [];
		const max = Math.max(...tail.map((d) => Math.abs(d.value)), 0.001);
		return tail.map((d) => ({ h: (Math.abs(d.value) / max) * 100 }));
	}
</script>

<PageHeader title="Macro Intelligence">
	{#snippet actions()}
		{#if regime}
			<span class="macro-regime-badge" style:color={regimeColor(regime.global_regime)}>
				{regime.global_regime.toUpperCase()}
			</span>
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
						{regime.regional_regimes[regionName]}
					</span>
				{/if}
			</div>

			<div class="region-score-hero" style:color={scoreColor(regionData.composite_score)}>
				{regionData.composite_score.toFixed(0)}
			</div>

			<div class="region-coverage">
				Coverage: {(regionData.coverage * 100).toFixed(0)}%
			</div>

			<!-- Dimension scores -->
			{#if Object.keys(regionData.dimensions).length > 0}
				<div class="region-dims">
					{#each Object.entries(regionData.dimensions) as [dimName, dim] (dimName)}
						<div class="region-dim">
							<span class="dim-name">{dimName}</span>
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
	<!-- ROW 4: Treasury time-series                                        -->
	<!-- ═══════════════════════════════════════════════════════════════════ -->
	<section class="macro-panel macro-panel--wide">
		<div class="ts-header">
			<h3 class="macro-panel-title">US Treasury</h3>
			<select class="ts-select" bind:value={treasurySeries}>
				{#each TREASURY_SERIES as s (s)}
					<option value={s}>{s.replace(/_/g, " ")}</option>
				{/each}
			</select>
		</div>
		{#if treasuryLoading}
			<div class="ts-loading">Loading…</div>
		{:else if treasuryData.length > 0}
			<div class="ts-spark">
				{#each sparkMini(treasuryData, 60) as bar, i (i)}
					<div class="ts-bar" style:height="{bar.h}%"></div>
				{/each}
			</div>
			<div class="ts-range">
				<span>{treasuryData[0]?.obs_date}</span>
				<span>{treasuryData[treasuryData.length - 1]?.obs_date}</span>
			</div>
		{:else}
			<div class="ts-empty">No data for {treasurySeries}</div>
		{/if}
	</section>

	<!-- ═══════════════════════════════════════════════════════════════════ -->
	<!-- ROW 5: OFR Hedge Fund Monitor                                      -->
	<!-- ═══════════════════════════════════════════════════════════════════ -->
	<section class="macro-panel macro-panel--wide">
		<div class="ts-header">
			<h3 class="macro-panel-title">OFR Hedge Fund</h3>
			<select class="ts-select" bind:value={ofrMetric}>
				{#each OFR_METRICS as m (m)}
					<option value={m}>{m.replace(/^HF_/, "").replace(/_/g, " ")}</option>
				{/each}
			</select>
		</div>
		{#if ofrLoading}
			<div class="ts-loading">Loading…</div>
		{:else if ofrData.length > 0}
			<div class="ts-spark">
				{#each sparkMini(ofrData, 60) as bar, i (i)}
					<div class="ts-bar ts-bar--ofr" style:height="{bar.h}%"></div>
				{/each}
			</div>
			<div class="ts-range">
				<span>{ofrData[0]?.obs_date}</span>
				<span>{ofrData[ofrData.length - 1]?.obs_date}</span>
			</div>
		{:else}
			<div class="ts-empty">No data for {ofrMetric}</div>
		{/if}
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

	.macro-panel--wide {
		grid-column: span 2;
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

	/* ── Time-series panels (Treasury, OFR) ──────────────────────────────── */
	.ts-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: var(--netz-space-stack-xs, 8px) var(--netz-space-inline-md, 16px);
		border-bottom: 1px solid var(--netz-border-subtle);
		background: var(--netz-surface-alt);
	}

	.ts-header .macro-panel-title {
		border-bottom: none;
		padding: 0;
		background: transparent;
	}

	.ts-select {
		height: var(--netz-space-control-height-sm, 28px);
		padding: 0 var(--netz-space-inline-xs, 8px);
		border: 1px solid var(--netz-border);
		border-radius: var(--netz-radius-sm, 6px);
		background: var(--netz-surface-elevated);
		color: var(--netz-text-primary);
		font-size: var(--netz-text-label, 0.75rem);
		font-family: var(--netz-font-sans);
	}

	.ts-spark {
		display: flex;
		align-items: flex-end;
		gap: 1px;
		height: 64px;
		padding: var(--netz-space-stack-xs, 8px) var(--netz-space-inline-md, 16px);
	}

	.ts-bar {
		flex: 1;
		min-width: 2px;
		background: var(--netz-brand-primary);
		border-radius: 1px 1px 0 0;
		opacity: 0.5;
		transition: height 200ms ease;
	}

	.ts-bar:last-child {
		opacity: 1;
	}

	.ts-bar--ofr {
		background: var(--netz-brand-highlight);
	}

	.ts-range {
		display: flex;
		justify-content: space-between;
		padding: 0 var(--netz-space-inline-md, 16px) var(--netz-space-stack-xs, 8px);
		font-size: 10px;
		color: var(--netz-text-muted);
	}

	.ts-loading,
	.ts-empty {
		padding: var(--netz-space-stack-lg, 32px);
		text-align: center;
		color: var(--netz-text-muted);
		font-size: var(--netz-text-small, 0.8125rem);
	}

	/* ── Responsive ──────────────────────────────────────────────────────── */
	@media (max-width: 1024px) {
		.macro-grid {
			grid-template-columns: repeat(2, 1fr);
		}

		.macro-panel--wide {
			grid-column: span 2;
		}
	}

	@media (max-width: 600px) {
		.macro-grid {
			grid-template-columns: 1fr;
		}

		.macro-panel--indicators,
		.macro-panel--wide {
			grid-column: 1;
		}

		.ind-grid {
			grid-template-columns: repeat(2, 1fr);
		}
	}
</style>
