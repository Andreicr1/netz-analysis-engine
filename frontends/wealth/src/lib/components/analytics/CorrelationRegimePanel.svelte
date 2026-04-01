<!--
  Correlation Regime Panel — regime-aware heatmap with Marchenko-Pastur denoising,
  contagion detection, concentration metrics, and pair drill-down.
-->
<script lang="ts">
	import { getContext } from "svelte";
	import { MetricCard, StatusBadge, formatPercent, formatNumber } from "@investintell/ui";
	import { RegimeChart } from "@investintell/ui/charts";
	import { createClientApiClient } from "$lib/api/client";
	import type {
		CorrelationRegimeResult,
		PairCorrelationResult,
		InstrumentCorrelation,
	} from "$lib/types/analytics";
	import type { UniverseAsset } from "$lib/types/universe";
	import CorrelationHeatmap from "$lib/components/charts/CorrelationHeatmap.svelte";
	import EigenvalueChart from "$lib/components/charts/EigenvalueChart.svelte";

	interface Props {
		data: CorrelationRegimeResult;
		profile: string;
		instruments: UniverseAsset[];
	}

	let { data, profile, instruments }: Props = $props();

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	// ── Derived ─────────────────────────────────────────────────────────

	let concentration = $derived(data.concentration);
	let contagionPairs = $derived(data.contagion_pairs);

	function absorptionStatusLabel(s: string): "ok" | "warn" | "breach" {
		if (s === "critical") return "breach";
		if (s === "warning") return "warn";
		return "ok";
	}

	function concentrationStatusLabel(s: string): "ok" | "warn" | "breach" {
		if (s === "critical" || s === "high") return "breach";
		if (s === "moderate") return "warn";
		return "ok";
	}

	// ── Pair drill-down ─────────────────────────────────────────────────

	let pairSelection = $state<{ a: string; b: string } | null>(null);
	let pairData = $state<PairCorrelationResult | null>(null);
	let pairLoading = $state(false);
	let pairError = $state<string | null>(null);
	let pairAbort: (() => void) | null = $state(null);

	function handlePairSelect(nameA: string, nameB: string) {
		pairSelection = { a: nameA, b: nameB };
		pairData = null;
		pairLoading = true;
		pairError = null;

		// Resolve name → instrument_id using contagion_pairs then instruments
		let idA: string | null = null;
		let idB: string | null = null;

		for (const p of contagionPairs) {
			if (p.instrument_a_name === nameA && !idA) idA = p.instrument_a_id;
			if (p.instrument_b_name === nameA && !idA) idA = p.instrument_b_id;
			if (p.instrument_a_name === nameB && !idB) idB = p.instrument_a_id;
			if (p.instrument_b_name === nameB && !idB) idB = p.instrument_b_id;
		}

		// Fallback: instruments list
		if (!idA || !idB) {
			for (const inst of instruments) {
				if (inst.fund_name === nameA && !idA) idA = inst.instrument_id;
				if (inst.fund_name === nameB && !idB) idB = inst.instrument_id;
			}
		}

		if (!idA || !idB) {
			pairError = "Could not resolve instrument IDs for this pair";
			pairLoading = false;
			return;
		}

		const controller = new AbortController();

		(async () => {
			try {
				const api = createClientApiClient(getToken);
				const result = await api.get<PairCorrelationResult>(
					`/analytics/correlation-regime/${profile}/pair/${idA}/${idB}`,
				);
				if (!controller.signal.aborted) pairData = result;
			} catch (e) {
				if (!controller.signal.aborted) {
					pairError = e instanceof Error ? e.message : "Failed to load pair correlation";
				}
			} finally {
				if (!controller.signal.aborted) pairLoading = false;
			}
		})();

		pairAbort?.();
		pairAbort = () => controller.abort();
	}

	let pairChartSeries = $derived.by(() => {
		if (!pairData) return [];
		return [{
			name: `${pairData.instrument_a_name} vs ${pairData.instrument_b_name}`,
			data: pairData.dates.map((d, i) => [d, pairData!.correlations[i]] as [string, number]),
		}];
	});
</script>

<div class="crp-section">
	<!-- ── Header ──────────────────────────────────────────────────────── -->
	<div class="crp-header">
		<h3 class="crp-title">Correlation Regime Analysis</h3>
		{#if data.regime_shift_detected}
			<span class="crp-regime-badge crp-regime-badge--alert">Regime Shift Detected</span>
		{:else}
			<span class="crp-regime-badge crp-regime-badge--ok">Stable Regime</span>
		{/if}
	</div>

	<!-- ── KPIs ────────────────────────────────────────────────────────── -->
	<div class="crp-metrics">
		<MetricCard
			label="Avg Correlation"
			value={formatNumber(data.average_correlation, 3, "en-US")}
			sublabel="Current {data.window_days}d window"
		/>
		<MetricCard
			label="Baseline Avg"
			value={formatNumber(data.baseline_average_correlation, 3, "en-US")}
			sublabel="Long-term baseline"
		/>
		<MetricCard
			label="Absorption Ratio"
			value={formatPercent(concentration.absorption_ratio)}
			sublabel="{concentration.n_signal_eigenvalues} signal / {concentration.eigenvalues.length} total"
			status={absorptionStatusLabel(concentration.absorption_status)}
		/>
		<MetricCard
			label="Diversification"
			value={formatNumber(concentration.diversification_ratio, 2, "en-US")}
			sublabel="Concentration: {concentration.concentration_status}"
			status={concentrationStatusLabel(concentration.concentration_status)}
		/>
	</div>

	<!-- ── Contagion Pairs ─────────────────────────────────────────────── -->
	{#if contagionPairs.length > 0}
		<div class="crp-contagion">
			<h4 class="crp-sub-title">
				Contagion Pairs
				<span class="crp-contagion-count">{contagionPairs.length}</span>
			</h4>
			<div class="crp-contagion-list">
				{#each contagionPairs as pair (pair.instrument_a_id + pair.instrument_b_id)}
					<button
						class="crp-contagion-row"
						onclick={() => handlePairSelect(pair.instrument_a_name, pair.instrument_b_name)}
					>
						<span class="crp-pair-names">
							{pair.instrument_a_name} / {pair.instrument_b_name}
						</span>
						<span class="crp-pair-corr">
							{formatNumber(pair.current_correlation, 3, "en-US")}
						</span>
						<span class="crp-pair-delta" class:crp-pair-delta--up={pair.correlation_change > 0}>
							{pair.correlation_change > 0 ? "+" : ""}{formatNumber(pair.correlation_change, 3, "en-US")}
						</span>
					</button>
				{/each}
			</div>
		</div>
	{/if}

	<!-- ── Heatmap ─────────────────────────────────────────────────────── -->
	<div class="crp-heatmap">
		<CorrelationHeatmap
			matrix={data.correlation_matrix}
			labels={data.instrument_labels}
			contagionPairs={contagionPairs}
			onPairSelect={handlePairSelect}
			height={Math.min(500, Math.max(300, data.instrument_labels.length * 18))}
		/>
	</div>

	<!-- ── Eigenvalue Decomposition ────────────────────────────────────── -->
	<div class="crp-eigen">
		<h4 class="crp-sub-title">Eigenvalue Decomposition (Marchenko-Pastur)</h4>
		<EigenvalueChart
			eigenvalues={concentration.eigenvalues}
			mpThreshold={concentration.mp_threshold}
			nSignal={concentration.n_signal_eigenvalues}
		/>
	</div>

	<!-- ── Pair Drill-Down ─────────────────────────────────────────────── -->
	{#if pairSelection}
		<div class="crp-pair-drilldown">
			<h4 class="crp-sub-title">
				Rolling Correlation: {pairSelection.a} vs {pairSelection.b}
			</h4>
			{#if pairLoading}
				<div class="crp-empty">Loading pair correlation...</div>
			{:else if pairError}
				<div class="crp-error">{pairError}</div>
			{:else if pairData && pairChartSeries.length > 0}
				<RegimeChart
					series={pairChartSeries}
					regimes={[]}
					height={260}
					ariaLabel="Rolling correlation for {pairSelection.a} vs {pairSelection.b}"
					optionsOverride={{
						yAxis: { min: -1, max: 1, axisLabel: { fontSize: 10 } },
						series: [{
							type: "line",
							data: pairChartSeries[0]?.data ?? [],
							name: pairChartSeries[0]?.name ?? "",
							smooth: true,
							showSymbol: false,
							markLine: {
								silent: true,
								data: [{ yAxis: 0, lineStyle: { color: "#94a3b8", type: "dashed" } }],
							},
						}],
					}}
				/>
			{:else}
				<div class="crp-empty">No data available for this pair.</div>
			{/if}
		</div>
	{/if}
</div>

<style>
	.crp-section {
		margin: var(--ii-space-stack-md, 16px) var(--ii-space-inline-lg, 24px) 0;
		border: 1px solid var(--ii-border-subtle);
		border-radius: var(--ii-radius-md, 12px);
		background: var(--ii-surface-elevated);
		overflow: hidden;
	}

	.crp-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--ii-space-stack-xs, 10px) var(--ii-space-inline-md, 16px);
		border-bottom: 1px solid var(--ii-border-subtle);
		background: var(--ii-surface-alt);
	}

	.crp-title {
		font-size: var(--ii-text-small, 0.8125rem);
		font-weight: 600;
		color: var(--ii-text-primary);
	}

	.crp-regime-badge {
		padding: 2px 10px;
		border-radius: var(--ii-radius-sm, 8px);
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 600;
	}

	.crp-regime-badge--alert {
		background: color-mix(in srgb, var(--ii-danger) 12%, transparent);
		color: var(--ii-danger);
	}

	.crp-regime-badge--ok {
		background: color-mix(in srgb, var(--ii-success) 12%, transparent);
		color: var(--ii-success);
	}

	/* ── Metrics row ──────────────────────────────────────────────────── */
	.crp-metrics {
		display: grid;
		grid-template-columns: repeat(4, 1fr);
		gap: 1px;
		margin: 0;
		background: var(--ii-border-subtle);
		border-bottom: 1px solid var(--ii-border-subtle);
	}

	@media (max-width: 768px) {
		.crp-metrics {
			grid-template-columns: repeat(2, 1fr);
		}
	}

	/* ── Contagion pairs ──────────────────────────────────────────────── */
	.crp-contagion {
		border-bottom: 1px solid var(--ii-border-subtle);
	}

	.crp-sub-title {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: var(--ii-space-stack-xs, 10px) var(--ii-space-inline-md, 16px);
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--ii-text-muted);
	}

	.crp-contagion-count {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		min-width: 18px;
		height: 18px;
		padding: 0 5px;
		border-radius: 9px;
		background: var(--ii-danger);
		color: #fff;
		font-size: 10px;
		font-weight: 700;
	}

	.crp-contagion-list {
		display: flex;
		flex-direction: column;
	}

	.crp-contagion-row {
		display: flex;
		align-items: center;
		gap: var(--ii-space-inline-sm, 10px);
		padding: var(--ii-space-stack-2xs, 5px) var(--ii-space-inline-md, 16px);
		border: none;
		border-bottom: 1px solid var(--ii-border-subtle);
		background: transparent;
		font-family: var(--ii-font-sans);
		cursor: pointer;
		transition: background-color 120ms ease;
		text-align: left;
		width: 100%;
	}

	.crp-contagion-row:hover {
		background: var(--ii-surface-alt);
	}

	.crp-pair-names {
		flex: 1;
		font-size: var(--ii-text-small, 0.8125rem);
		font-weight: 500;
		color: var(--ii-text-primary);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.crp-pair-corr {
		font-size: var(--ii-text-small, 0.8125rem);
		font-weight: 600;
		font-variant-numeric: tabular-nums;
		color: var(--ii-text-primary);
	}

	.crp-pair-delta {
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 600;
		font-variant-numeric: tabular-nums;
		color: var(--ii-success);
	}

	.crp-pair-delta--up {
		color: var(--ii-danger);
	}

	/* ── Heatmap / Eigen ──────────────────────────────────────────────── */
	.crp-heatmap {
		padding: var(--ii-space-stack-sm, 12px) var(--ii-space-inline-md, 16px);
	}

	.crp-eigen {
		padding: 0 var(--ii-space-inline-md, 16px) var(--ii-space-stack-md, 16px);
	}

	/* ── Pair drill-down ──────────────────────────────────────────────── */
	.crp-pair-drilldown {
		padding: var(--ii-space-stack-md, 16px) var(--ii-space-inline-md, 16px);
		border-top: 1px solid var(--ii-border-subtle);
	}

	.crp-empty {
		padding: var(--ii-space-stack-lg, 32px);
		text-align: center;
		color: var(--ii-text-muted);
		font-size: var(--ii-text-small, 0.8125rem);
	}

	.crp-error {
		padding: var(--ii-space-stack-sm, 12px) var(--ii-space-inline-md, 16px);
		color: var(--ii-danger);
		font-size: var(--ii-text-small, 0.8125rem);
	}
</style>
