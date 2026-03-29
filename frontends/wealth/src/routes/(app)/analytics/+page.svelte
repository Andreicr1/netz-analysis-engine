<!--
  Analytics — Brinson-Fachler Attribution + Strategy Drift.
  Master/Detail: sector list (left) + attribution bars (right).
  Timeframe filter via $state propagated through $derived.
-->
<script lang="ts">
	import { goto } from "$app/navigation";
	import { page } from "$app/stores";
	import { getContext } from "svelte";
	import {
		PageHeader, StatusBadge, MetricCard,
		formatPercent, formatDateTime, formatNumber,
	} from "@investintell/ui";
	import { CorrelationHeatmap, ChartContainer, RegimeChart } from "@investintell/ui/charts";
	import { createClientApiClient } from "$lib/api/client";
	import type { PageData } from "./$types";
	import type {
		AttributionResult, ParetoResult, SectorAttribution, StrategyDriftAlert, Timeframe,
		CorrelationResult, RollingCorrelation, BacktestResult, BacktestFoldResult,
	} from "$lib/types/analytics";
	import { effectColor, severityColor } from "$lib/types/analytics";
	import { Button } from "@investintell/ui";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let { data }: { data: PageData } = $props();

	let attribution = $derived(data.attribution as AttributionResult | null);
	let driftAlerts = $derived((data.driftAlerts ?? []) as StrategyDriftAlert[]);
	let profile = $derived(data.profile as string);

	// ── Filter state ──────────────────────────────────────────────────────

	const initialProfile = data.profile as string;
	let selectedProfile = $state(initialProfile);
	let timeframe = $state<Timeframe>("1y");

	// Navigate on profile change
	$effect(() => {
		if (selectedProfile !== initialProfile) {
			goto(`/analytics?profile=${selectedProfile}`, { replaceState: true });
		}
	});

	// ── Derived attribution data ──────────────────────────────────────────

	let sectors = $derived(attribution?.sectors ?? [] as SectorAttribution[]);
	let selectedSector = $state<string | null>(null);
	let activeSector = $derived(
		sectors.find((s) => s.block_id === selectedSector) ?? null
	);

	// Bar scale: max absolute effect determines 100% width
	let maxEffect = $derived(
		Math.max(
			...sectors.map((s) => Math.max(Math.abs(s.allocation_effect), Math.abs(s.selection_effect))),
			0.001
		)
	);

	function barWidth(value: number): number {
		return (Math.abs(value) / maxEffect) * 100;
	}

	function barSide(value: number): "positive" | "negative" {
		return value >= 0 ? "positive" : "negative";
	}

	// ── Helpers ───────────────────────────────────────────────────────────

	function fmtBps(v: number): string {
		return `${(v * 10000).toFixed(1)} bps`;
	}

	function fmtEffect(v: number): string {
		const sign = v >= 0 ? "+" : "";
		return `${sign}${(v * 10000).toFixed(1)} bps`;
	}

	// ── Correlation ──────────────────────────────────────────────────────

	let correlation = $derived(data.correlation as CorrelationResult | null);
	let concentration = $derived(correlation?.concentration ?? null);

	function absorptionStatus(ratio: number): "ok" | "warn" | "breach" {
		if (ratio > 0.90) return "breach";
		if (ratio > 0.80) return "warn";
		return "ok";
	}

	// Eigenvalue bar chart option
	let eigenOption = $derived.by(() => {
		if (!concentration) return null;
		const evs = concentration.eigenvalues;
		const mpT = concentration.mp_threshold;
		return {
			tooltip: { trigger: "axis" },
			grid: { left: 60, right: 20, top: 20, bottom: 30 },
			xAxis: {
				type: "category",
				data: evs.map((_: number, i: number) => `\u03BB${i + 1}`),
				axisLabel: { fontSize: 10 },
			},
			yAxis: { type: "value", axisLabel: { fontSize: 10 } },
			series: [{
				type: "bar",
				data: evs.map((v: number) => ({
					value: v,
					itemStyle: { color: v > mpT ? "#2166ac" : "#94a3b8" },
				})),
				markLine: {
					silent: true,
					data: [{ yAxis: mpT, lineStyle: { color: "#ef4444", type: "dashed", width: 2 }, label: { formatter: "MP threshold", position: "end", fontSize: 10 } }],
				},
			}],
		} as Record<string, unknown>;
	});

	// ── Rolling Correlation (drill-down from heatmap click) ──────────────

	let rollingPair = $state<{ a: string; b: string } | null>(null);
	let rollingData = $state<RollingCorrelation | null>(null);
	let rollingLoading = $state(false);
	let rollingError = $state<string | null>(null);

	function handlePairSelect(a: string, b: string) {
		rollingPair = { a, b };
		rollingData = null;
		rollingLoading = true;
		rollingError = null;

		const controller = new AbortController();

		(async () => {
			try {
				const api = createClientApiClient(getToken);
				const result = await api.get<RollingCorrelation>("/analytics/rolling-correlation", {
					inst_a: a,
					inst_b: b,
					profile: selectedProfile,
				});
				if (!controller.signal.aborted) {
					rollingData = result;
				}
			} catch (e) {
				if (!controller.signal.aborted) {
					rollingError = e instanceof Error ? e.message : "Failed to load rolling correlation";
				}
			} finally {
				if (!controller.signal.aborted) {
					rollingLoading = false;
				}
			}
		})();

		// Store cleanup for next click
		rollingAbort?.();
		rollingAbort = () => controller.abort();
	}

	let rollingAbort: (() => void) | null = $state(null);

	let rollingChartSeries = $derived.by(() => {
		if (!rollingData) return [];
		return [{
			name: `${rollingData.instrument_a} vs ${rollingData.instrument_b}`,
			data: rollingData.dates.map((d, i) => [d, rollingData!.values[i]] as [string, number]),
		}];
	});

	// ── Backtest ────────────────────────────────────────────────────────

	let backtestRunning = $state(false);
	let backtestResult = $state<BacktestResult | null>(null);
	let backtestError = $state<string | null>(null);
	let backtestElapsed = $state(0);
	let backtestTimer: ReturnType<typeof setInterval> | null = null;

	async function runBacktest() {
		backtestRunning = true;
		backtestResult = null;
		backtestError = null;
		backtestElapsed = 0;

		backtestTimer = setInterval(() => {
			backtestElapsed += 1;
		}, 1000);

		try {
			const api = createClientApiClient(getToken);
			const result = await api.post<BacktestResult>("/analytics/backtest", {
				profile: selectedProfile,
			}, { timeoutMs: 180000 });
			backtestResult = result;
		} catch (e) {
			backtestError = e instanceof Error ? e.message : "Backtest failed";
		} finally {
			backtestRunning = false;
			if (backtestTimer) {
				clearInterval(backtestTimer);
				backtestTimer = null;
			}
		}
	}

	// ── Pareto optimization ──────────────────────────────────────────────

	let paretoRunning = $state(false);
	let paretoProgress = $state<string | null>(null);
	let paretoResult = $state<ParetoResult | null>(null);
	let paretoError = $state<string | null>(null);

	async function runPareto() {
		paretoRunning = true;
		paretoProgress = "Submitting…";
		paretoResult = null;
		paretoError = null;

		try {
			const api = createClientApiClient(getToken);
			const initial = await api.post<ParetoResult>("/analytics/optimize/pareto", {
				profile: selectedProfile,
			});

			const jobId = initial.job_id;
			if (!jobId) {
				paretoResult = initial;
				paretoRunning = false;
				paretoProgress = null;
				return;
			}

			// Connect to SSE stream via fetch + ReadableStream
			const token = await getToken();
			const apiBase = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";
			const res = await fetch(`${apiBase}/analytics/optimize/pareto/${jobId}/stream`, {
				headers: { Authorization: `Bearer ${token}` },
			});

			if (!res.ok || !res.body) {
				paretoError = "Failed to connect to progress stream";
				paretoRunning = false;
				paretoProgress = null;
				return;
			}

			const reader = res.body.getReader();
			const decoder = new TextDecoder();
			let buffer = "";
			let currentEvent = "message";

			while (true) {
				const { done, value } = await reader.read();
				if (done) break;

				buffer += decoder.decode(value, { stream: true });
				const lines = buffer.split("\n");
				buffer = lines.pop() ?? "";

				for (const line of lines) {
					if (line.startsWith("event: ")) {
						currentEvent = line.slice(7).trim();
					} else if (line.startsWith("data: ")) {
						try {
							const data = JSON.parse(line.slice(6));
							if (currentEvent === "progress") {
								paretoProgress = `${data.stage ?? "optimizing"}… ${data.pct ?? ""}%`;
							} else if (currentEvent === "done") {
								paretoResult = data as ParetoResult;
								paretoProgress = null;
							} else if (currentEvent === "error") {
								paretoError = data.message ?? "Optimization failed";
								paretoProgress = null;
							}
						} catch {
							// skip malformed SSE lines
						}
						currentEvent = "message";
					} else if (line === "") {
						currentEvent = "message";
					}
				}
			}
		} catch (e) {
			paretoError = e instanceof Error ? e.message : "Pareto optimization failed";
		} finally {
			paretoRunning = false;
			if (paretoProgress) paretoProgress = null;
		}
	}
</script>

<PageHeader title="Analytics">
	{#snippet actions()}
		<div class="an-controls">
			<select class="an-select" bind:value={selectedProfile}>
				<option value="conservative">Conservative</option>
				<option value="moderate">Moderate</option>
				<option value="growth">Growth</option>
			</select>
			<div class="an-timeframe">
				{#each (["ytd", "1y", "3y"] as Timeframe[]) as tf (tf)}
					<button
						class="an-tf-btn"
						class:an-tf-btn--active={timeframe === tf}
						onclick={() => timeframe = tf}
					>
						{tf.toUpperCase()}
					</button>
				{/each}
			</div>
		</div>
	{/snippet}
</PageHeader>

{#if attribution}
	<!-- Summary KPIs -->
	<div class="an-kpi-row">
		<div class="an-kpi">
			<span class="an-kpi-label">Portfolio</span>
			<span class="an-kpi-value">{formatPercent(attribution.total_portfolio_return)}</span>
		</div>
		<div class="an-kpi">
			<span class="an-kpi-label">Benchmark</span>
			<span class="an-kpi-value">{formatPercent(attribution.total_benchmark_return)}</span>
		</div>
		<div class="an-kpi">
			<span class="an-kpi-label">Excess</span>
			<span class="an-kpi-value" style:color={effectColor(attribution.total_excess_return)}>
				{fmtEffect(attribution.total_excess_return)}
			</span>
		</div>
		<div class="an-kpi">
			<span class="an-kpi-label">Allocation</span>
			<span class="an-kpi-value" style:color={effectColor(attribution.allocation_total)}>
				{fmtEffect(attribution.allocation_total)}
			</span>
		</div>
		<div class="an-kpi">
			<span class="an-kpi-label">Selection</span>
			<span class="an-kpi-value" style:color={effectColor(attribution.selection_total)}>
				{fmtEffect(attribution.selection_total)}
			</span>
		</div>
		<div class="an-kpi">
			<span class="an-kpi-label">Periods</span>
			<span class="an-kpi-value">{attribution.n_periods}</span>
		</div>
	</div>
{/if}

<div class="an-layout">
	<!-- ═══════════════════════════════════════════════════════════════════ -->
	<!-- LEFT: Sector master list                                           -->
	<!-- ═══════════════════════════════════════════════════════════════════ -->
	<aside class="an-master">
		<h3 class="an-master-title">Sectors</h3>
		{#if sectors.length === 0}
			<div class="an-empty">No attribution data.</div>
		{:else}
			<div class="an-sector-list">
				{#each sectors as sector (sector.block_id)}
					<button
						class="an-sector-item"
						class:an-sector-item--active={selectedSector === sector.block_id}
						onclick={() => selectedSector = selectedSector === sector.block_id ? null : sector.block_id}
					>
						<span class="an-sector-name">{sector.sector}</span>
						<span class="an-sector-effect" style:color={effectColor(sector.total_effect)}>
							{fmtEffect(sector.total_effect)}
						</span>
					</button>
				{/each}
			</div>
		{/if}

		<!-- Drift alerts below sectors -->
		{#if driftAlerts.length > 0}
			<div class="an-drift-section">
				<h3 class="an-master-title">
					Strategy Drift
					<span class="an-drift-count">{driftAlerts.length}</span>
				</h3>
				<div class="an-drift-list">
					{#each driftAlerts as alert (alert.instrument_id)}
						<div class="an-drift-row">
							<span class="an-drift-name">{alert.instrument_name}</span>
							<span class="an-drift-badge" style:color={severityColor(alert.severity)}>
								{alert.severity}
							</span>
							<span class="an-drift-meta">{alert.anomalous_count}/{alert.total_metrics}</span>
						</div>
					{/each}
				</div>
			</div>
		{/if}
	</aside>

	<!-- ═══════════════════════════════════════════════════════════════════ -->
	<!-- RIGHT: Brinson-Fachler attribution bars                            -->
	<!-- ═══════════════════════════════════════════════════════════════════ -->
	<section class="an-detail">
		{#if activeSector}
			<!-- Single sector deep-dive -->
			<div class="an-sector-detail">
				<h3 class="an-detail-title">{activeSector.sector}</h3>
				<div class="an-bar-group">
					<div class="an-bar-row">
						<span class="an-bar-label">Allocation</span>
						<div class="an-bar-track">
							<div
								class="an-bar-fill an-bar-fill--{barSide(activeSector.allocation_effect)}"
								style:width="{barWidth(activeSector.allocation_effect)}%"
								style:margin-left={activeSector.allocation_effect < 0 ? "auto" : "50%"}
								style:margin-right={activeSector.allocation_effect >= 0 ? "auto" : "50%"}
							></div>
							<div class="an-bar-zero"></div>
						</div>
						<span class="an-bar-value" style:color={effectColor(activeSector.allocation_effect)}>
							{fmtEffect(activeSector.allocation_effect)}
						</span>
					</div>
					<div class="an-bar-row">
						<span class="an-bar-label">Selection</span>
						<div class="an-bar-track">
							<div
								class="an-bar-fill an-bar-fill--{barSide(activeSector.selection_effect)}"
								style:width="{barWidth(activeSector.selection_effect)}%"
								style:margin-left={activeSector.selection_effect < 0 ? "auto" : "50%"}
								style:margin-right={activeSector.selection_effect >= 0 ? "auto" : "50%"}
							></div>
							<div class="an-bar-zero"></div>
						</div>
						<span class="an-bar-value" style:color={effectColor(activeSector.selection_effect)}>
							{fmtEffect(activeSector.selection_effect)}
						</span>
					</div>
					<div class="an-bar-row">
						<span class="an-bar-label">Interaction</span>
						<div class="an-bar-track">
							<div
								class="an-bar-fill an-bar-fill--{barSide(activeSector.interaction_effect)}"
								style:width="{barWidth(activeSector.interaction_effect)}%"
								style:margin-left={activeSector.interaction_effect < 0 ? "auto" : "50%"}
								style:margin-right={activeSector.interaction_effect >= 0 ? "auto" : "50%"}
							></div>
							<div class="an-bar-zero"></div>
						</div>
						<span class="an-bar-value" style:color={effectColor(activeSector.interaction_effect)}>
							{fmtEffect(activeSector.interaction_effect)}
						</span>
					</div>
				</div>
				<div class="an-sector-total">
					Total Effect: <strong style:color={effectColor(activeSector.total_effect)}>{fmtEffect(activeSector.total_effect)}</strong>
				</div>
			</div>
		{:else}
			<!-- All sectors comparative view -->
			<h3 class="an-detail-title">Attribution by Sector — Allocation vs Selection</h3>
			<div class="an-all-sectors">
				{#each sectors as sector (sector.block_id)}
					<div class="an-comp-row">
						<span class="an-comp-label">{sector.sector}</span>
						<div class="an-comp-bars">
							<!-- Allocation bar -->
							<div class="an-comp-bar-wrap">
								<div class="an-comp-track">
									<div
										class="an-comp-fill an-comp-fill--alloc an-comp-fill--{barSide(sector.allocation_effect)}"
										style:width="{barWidth(sector.allocation_effect) * 0.5}%"
									></div>
									<div class="an-comp-zero"></div>
								</div>
							</div>
							<!-- Selection bar -->
							<div class="an-comp-bar-wrap">
								<div class="an-comp-track">
									<div
										class="an-comp-fill an-comp-fill--sel an-comp-fill--{barSide(sector.selection_effect)}"
										style:width="{barWidth(sector.selection_effect) * 0.5}%"
									></div>
									<div class="an-comp-zero"></div>
								</div>
							</div>
						</div>
						<span class="an-comp-total" style:color={effectColor(sector.total_effect)}>
							{fmtEffect(sector.total_effect)}
						</span>
					</div>
				{/each}
				<div class="an-legend">
					<span class="an-legend-item"><span class="an-legend-dot an-legend-dot--alloc"></span>Allocation</span>
					<span class="an-legend-item"><span class="an-legend-dot an-legend-dot--sel"></span>Selection</span>
				</div>
			</div>
		{/if}
	</section>
</div>

<!-- ═══════════════════════════════════════════════════════════════════ -->
<!-- Pareto Optimization                                                -->
<!-- ═══════════════════════════════════════════════════════════════════ -->
<div class="an-pareto-section">
	<div class="an-pareto-header">
		<h3 class="an-pareto-title">Multi-Objective Optimization (Pareto)</h3>
		<Button size="sm" variant="outline" onclick={runPareto} disabled={paretoRunning}>
			{paretoRunning ? "Running…" : "Run Pareto"}
		</Button>
	</div>

	{#if paretoProgress}
		<div class="an-pareto-progress">{paretoProgress}</div>
	{/if}

	{#if paretoError}
		<div class="an-pareto-error">{paretoError}</div>
	{/if}

	{#if paretoResult}
		<div class="an-pareto-result">
			<div class="an-kpi-row">
				<div class="an-kpi">
					<span class="an-kpi-label">Solutions</span>
					<span class="an-kpi-value">{paretoResult.n_solutions}</span>
				</div>
				<div class="an-kpi">
					<span class="an-kpi-label">Status</span>
					<span class="an-kpi-value">{paretoResult.status}</span>
				</div>
				<div class="an-kpi">
					<span class="an-kpi-label">Seed</span>
					<span class="an-kpi-value">{paretoResult.seed}</span>
				</div>
			</div>

			{#if Object.keys(paretoResult.recommended_weights).length > 0}
				<div class="an-pareto-weights">
					<h4 class="an-pareto-subtitle">Recommended Weights</h4>
					<div class="an-weight-grid">
						{#each Object.entries(paretoResult.recommended_weights) as [block, weight] (block)}
							<div class="an-weight-item">
								<span class="an-weight-label">{block}</span>
								<span class="an-weight-value">{formatPercent(weight)}</span>
							</div>
						{/each}
					</div>
				</div>
			{/if}
		</div>
	{/if}
</div>

<!-- ═══════════════════════════════════════════════════════════════════ -->
<!-- Correlation Heatmap + Eigenvalue Chart                             -->
<!-- ═══════════════════════════════════════════════════════════════════ -->
{#if correlation}
	<div class="an-corr-section">
		<div class="an-corr-header">
			<h3 class="an-section-title">Correlation Matrix</h3>
		</div>

		<div class="an-corr-metrics">
			{#if concentration}
				<MetricCard
					label="Absorption Ratio"
					value={formatPercent(concentration.absorption_ratio)}
					sublabel="Top {concentration.n_signal_eigenvalues} eigenvalues of {concentration.eigenvalues.length} total"
					status={absorptionStatus(concentration.absorption_ratio)}
				/>
			{/if}
		</div>

		<div class="an-corr-body">
			<div class="an-corr-heatmap">
				<CorrelationHeatmap
					matrix={correlation.matrix}
					labels={correlation.labels}
					onPairSelect={handlePairSelect}
					height={Math.min(500, Math.max(300, correlation.labels.length * 18))}
					ariaLabel="Correlation heatmap"
				/>
			</div>

			{#if eigenOption}
				<div class="an-corr-eigen">
					<h4 class="an-subsection-title">Eigenvalue Decomposition (Marchenko-Pastur)</h4>
					<ChartContainer option={eigenOption} height={220} ariaLabel="Eigenvalue bar chart" />
				</div>
			{/if}
		</div>

		<!-- Rolling Correlation Drill-Down -->
		{#if rollingPair}
			<div class="an-rolling-section">
				<h4 class="an-subsection-title">
					Rolling Correlation: {rollingPair.a} vs {rollingPair.b}
				</h4>
				{#if rollingLoading}
					<div class="an-empty">Loading rolling correlation…</div>
				{:else if rollingError}
					<div class="an-rolling-error">{rollingError}</div>
				{:else if rollingData && rollingChartSeries.length > 0}
					<RegimeChart
						series={rollingChartSeries}
						regimes={[]}
						height={260}
						ariaLabel="Rolling correlation chart"
						optionsOverride={{
							yAxis: { min: -1, max: 1, axisLabel: { fontSize: 10 } },
							series: [{
								type: "line",
								data: rollingChartSeries[0]?.data ?? [],
								name: rollingChartSeries[0]?.name ?? "",
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
					<div class="an-empty">No data available for this pair.</div>
				{/if}
			</div>
		{/if}
	</div>
{/if}

<!-- ═══════════════════════════════════════════════════════════════════ -->
<!-- Backtest                                                           -->
<!-- ═══════════════════════════════════════════════════════════════════ -->
<div class="an-backtest-section">
	<div class="an-pareto-header">
		<h3 class="an-pareto-title">Walk-Forward Backtest</h3>
		<Button size="sm" variant="outline" onclick={runBacktest} disabled={backtestRunning}>
			{backtestRunning ? "Running…" : "Run Backtest"}
		</Button>
	</div>

	{#if backtestRunning}
		<div class="an-backtest-progress">
			<div class="an-backtest-pulse"></div>
			<span>
				{#if backtestElapsed < 15}
					Running backtest…
				{:else if backtestElapsed < 90}
					Running backtest… ({backtestElapsed}s elapsed)
				{:else}
					This is taking longer than expected. ({backtestElapsed}s elapsed)
				{/if}
			</span>
		</div>
	{/if}

	{#if backtestError}
		<div class="an-pareto-error">{backtestError}</div>
	{/if}

	{#if backtestResult}
		<div class="an-backtest-result">
			<div class="an-kpi-row an-kpi-row--3">
				<div class="an-kpi">
					<span class="an-kpi-label">Mean Sharpe</span>
					<span class="an-kpi-value">
						{backtestResult.mean_sharpe !== null ? backtestResult.mean_sharpe.toFixed(3) : "—"}
					</span>
				</div>
				<div class="an-kpi">
					<span class="an-kpi-label">Std Sharpe</span>
					<span class="an-kpi-value">
						{backtestResult.std_sharpe !== null ? backtestResult.std_sharpe.toFixed(3) : "—"}
					</span>
				</div>
				<div class="an-kpi">
					<span class="an-kpi-label">Positive Folds</span>
					<span class="an-kpi-value">{backtestResult.positive_folds}/{backtestResult.total_folds}</span>
				</div>
			</div>

			{#if backtestResult.folds.length > 0}
				<table class="an-folds-table">
					<thead>
						<tr>
							<th>Fold</th>
							<th>Period</th>
							<th>Sharpe</th>
							<th>CVaR 95%</th>
							<th>Max DD</th>
						</tr>
					</thead>
					<tbody>
						{#each backtestResult.folds as fold (fold.fold)}
							<tr>
								<td class="fold-num">{fold.fold}</td>
								<td class="fold-period">
									{#if fold.period_start && fold.period_end}
										{fold.period_start} — {fold.period_end}
									{:else}
										—
									{/if}
								</td>
								<td>{fold.sharpe !== null ? fold.sharpe.toFixed(3) : "—"}</td>
								<td>{fold.cvar_95 !== null ? formatPercent(fold.cvar_95) : "—"}</td>
								<td>{fold.max_drawdown !== null ? formatPercent(fold.max_drawdown) : "—"}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			{/if}
		</div>
	{/if}
</div>

<style>
	/* ── Controls ─────────────────────────────────────────────────────────── */
	.an-controls {
		display: flex;
		align-items: center;
		gap: var(--ii-space-inline-sm, 10px);
	}

	.an-select {
		height: var(--ii-space-control-height-sm, 32px);
		padding: 0 var(--ii-space-inline-sm, 10px);
		border: 1px solid var(--ii-border);
		border-radius: var(--ii-radius-sm, 8px);
		background: var(--ii-surface-elevated);
		color: var(--ii-text-primary);
		font-size: var(--ii-text-small, 0.8125rem);
		font-family: var(--ii-font-sans);
	}

	.an-timeframe {
		display: flex;
		border: 1px solid var(--ii-border);
		border-radius: var(--ii-radius-sm, 8px);
		overflow: hidden;
	}

	.an-tf-btn {
		padding: 4px 12px;
		border: none;
		border-right: 1px solid var(--ii-border);
		background: transparent;
		color: var(--ii-text-secondary);
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 600;
		font-family: var(--ii-font-sans);
		cursor: pointer;
		transition: background-color 120ms ease, color 120ms ease;
	}

	.an-tf-btn:last-child {
		border-right: none;
	}

	.an-tf-btn:hover {
		background: var(--ii-surface-alt);
	}

	.an-tf-btn--active {
		background: color-mix(in srgb, var(--ii-brand-primary) 12%, transparent);
		color: var(--ii-brand-primary);
	}

	/* ── KPI row ─────────────────────────────────────────────────────────── */
	.an-kpi-row {
		display: grid;
		grid-template-columns: repeat(6, 1fr);
		gap: 1px;
		margin: 0 var(--ii-space-inline-lg, 24px);
		border: 1px solid var(--ii-border-subtle);
		border-radius: var(--ii-radius-md, 12px);
		overflow: hidden;
		background: var(--ii-border-subtle);
	}

	.an-kpi {
		display: flex;
		flex-direction: column;
		gap: 2px;
		padding: var(--ii-space-stack-xs, 10px) var(--ii-space-inline-sm, 12px);
		background: var(--ii-surface-elevated);
	}

	.an-kpi-label {
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-muted);
	}

	.an-kpi-value {
		font-size: var(--ii-text-body, 0.9375rem);
		font-weight: 700;
		color: var(--ii-text-primary);
		font-variant-numeric: tabular-nums;
	}

	/* ── Master/Detail layout ────────────────────────────────────────────── */
	.an-layout {
		display: grid;
		grid-template-columns: 260px 1fr;
		gap: 0;
		height: calc(100vh - 180px);
		margin: var(--ii-space-stack-sm, 12px) var(--ii-space-inline-lg, 24px) 0;
		border: 1px solid var(--ii-border-subtle);
		border-radius: var(--ii-radius-md, 12px);
		overflow: hidden;
	}

	/* Master (left) */
	.an-master {
		overflow-y: auto;
		border-right: 1px solid var(--ii-border-subtle);
		background: var(--ii-surface-elevated);
	}

	.an-master-title {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--ii-space-stack-xs, 10px) var(--ii-space-inline-md, 16px);
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--ii-text-muted);
		border-bottom: 1px solid var(--ii-border-subtle);
		background: var(--ii-surface-alt);
	}

	.an-empty {
		padding: var(--ii-space-stack-lg, 32px);
		text-align: center;
		color: var(--ii-text-muted);
		font-size: var(--ii-text-small, 0.8125rem);
	}

	.an-sector-list {
		display: flex;
		flex-direction: column;
	}

	.an-sector-item {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: var(--ii-space-stack-2xs, 8px) var(--ii-space-inline-md, 16px);
		border: none;
		border-bottom: 1px solid var(--ii-border-subtle);
		background: transparent;
		font-family: var(--ii-font-sans);
		cursor: pointer;
		transition: background-color 120ms ease;
		text-align: left;
	}

	.an-sector-item:hover {
		background: var(--ii-surface-alt);
	}

	.an-sector-item--active {
		background: color-mix(in srgb, var(--ii-brand-primary) 8%, transparent);
	}

	.an-sector-name {
		font-size: var(--ii-text-small, 0.8125rem);
		font-weight: 500;
		color: var(--ii-text-primary);
	}

	.an-sector-effect {
		font-size: var(--ii-text-small, 0.8125rem);
		font-weight: 600;
		font-variant-numeric: tabular-nums;
	}

	/* Drift section */
	.an-drift-section {
		border-top: 2px solid var(--ii-border);
	}

	.an-drift-count {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		min-width: 18px;
		height: 18px;
		padding: 0 5px;
		border-radius: 9px;
		background: var(--ii-warning);
		color: #fff;
		font-size: 10px;
		font-weight: 700;
	}

	.an-drift-list {
		display: flex;
		flex-direction: column;
	}

	.an-drift-row {
		display: flex;
		align-items: center;
		gap: var(--ii-space-inline-xs, 6px);
		padding: var(--ii-space-stack-2xs, 5px) var(--ii-space-inline-md, 16px);
		border-bottom: 1px solid var(--ii-border-subtle);
		font-size: var(--ii-text-small, 0.8125rem);
	}

	.an-drift-name {
		flex: 1;
		color: var(--ii-text-primary);
		font-weight: 500;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.an-drift-badge {
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 600;
		text-transform: uppercase;
	}

	.an-drift-meta {
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-muted);
		font-variant-numeric: tabular-nums;
	}

	/* Detail (right) */
	.an-detail {
		overflow-y: auto;
		padding: var(--ii-space-stack-md, 16px) var(--ii-space-inline-lg, 24px);
		background: var(--ii-surface);
	}

	.an-detail-title {
		font-size: var(--ii-text-body, 0.9375rem);
		font-weight: 600;
		color: var(--ii-text-primary);
		margin-bottom: var(--ii-space-stack-md, 16px);
	}

	/* Single sector bars */
	.an-bar-group {
		display: flex;
		flex-direction: column;
		gap: var(--ii-space-stack-md, 16px);
	}

	.an-bar-row {
		display: flex;
		align-items: center;
		gap: var(--ii-space-inline-sm, 10px);
	}

	.an-bar-label {
		width: 80px;
		font-size: var(--ii-text-small, 0.8125rem);
		font-weight: 500;
		color: var(--ii-text-secondary);
		flex-shrink: 0;
	}

	.an-bar-track {
		flex: 1;
		height: 24px;
		background: var(--ii-surface-alt);
		border-radius: 4px;
		position: relative;
		overflow: hidden;
	}

	.an-bar-zero {
		position: absolute;
		left: 50%;
		top: 0;
		bottom: 0;
		width: 1px;
		background: var(--ii-border);
	}

	.an-bar-fill {
		position: absolute;
		top: 2px;
		bottom: 2px;
		border-radius: 3px;
		transition: width 300ms ease;
	}

	.an-bar-fill--positive {
		left: 50%;
		background: var(--ii-success);
	}

	.an-bar-fill--negative {
		right: 50%;
		background: var(--ii-danger);
	}

	.an-bar-value {
		width: 80px;
		text-align: right;
		font-size: var(--ii-text-small, 0.8125rem);
		font-weight: 600;
		font-variant-numeric: tabular-nums;
		flex-shrink: 0;
	}

	.an-sector-total {
		margin-top: var(--ii-space-stack-md, 16px);
		padding-top: var(--ii-space-stack-sm, 12px);
		border-top: 1px solid var(--ii-border-subtle);
		font-size: var(--ii-text-body, 0.9375rem);
		color: var(--ii-text-secondary);
	}

	/* All sectors comparative */
	.an-all-sectors {
		display: flex;
		flex-direction: column;
		gap: var(--ii-space-stack-xs, 8px);
	}

	.an-comp-row {
		display: flex;
		align-items: center;
		gap: var(--ii-space-inline-sm, 10px);
	}

	.an-comp-label {
		width: 140px;
		font-size: var(--ii-text-small, 0.8125rem);
		font-weight: 500;
		color: var(--ii-text-primary);
		flex-shrink: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.an-comp-bars {
		flex: 1;
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.an-comp-bar-wrap {
		height: 10px;
	}

	.an-comp-track {
		height: 100%;
		background: var(--ii-surface-alt);
		border-radius: 2px;
		position: relative;
		overflow: hidden;
	}

	.an-comp-zero {
		position: absolute;
		left: 50%;
		top: 0;
		bottom: 0;
		width: 1px;
		background: var(--ii-border);
	}

	.an-comp-fill {
		position: absolute;
		top: 0;
		bottom: 0;
		border-radius: 2px;
		transition: width 300ms ease;
	}

	.an-comp-fill--positive { left: 50%; }
	.an-comp-fill--negative { right: 50%; }

	.an-comp-fill--alloc.an-comp-fill--positive { background: color-mix(in srgb, var(--ii-success) 70%, transparent); }
	.an-comp-fill--alloc.an-comp-fill--negative { background: color-mix(in srgb, var(--ii-danger) 70%, transparent); }
	.an-comp-fill--sel.an-comp-fill--positive { background: var(--ii-info); }
	.an-comp-fill--sel.an-comp-fill--negative { background: var(--ii-warning); }

	.an-comp-total {
		width: 70px;
		text-align: right;
		font-size: var(--ii-text-small, 0.8125rem);
		font-weight: 600;
		font-variant-numeric: tabular-nums;
		flex-shrink: 0;
	}

	.an-legend {
		display: flex;
		gap: var(--ii-space-inline-md, 16px);
		padding-top: var(--ii-space-stack-xs, 8px);
		border-top: 1px solid var(--ii-border-subtle);
	}

	.an-legend-item {
		display: flex;
		align-items: center;
		gap: 4px;
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-muted);
	}

	.an-legend-dot {
		width: 10px;
		height: 6px;
		border-radius: 2px;
	}

	.an-legend-dot--alloc { background: var(--ii-success); }
	.an-legend-dot--sel { background: var(--ii-info); }

	/* ── Pareto section ──────────────────────────────────────────────────── */
	.an-pareto-section {
		margin: var(--ii-space-stack-md, 16px) var(--ii-space-inline-lg, 24px) 0;
		border: 1px solid var(--ii-border-subtle);
		border-radius: var(--ii-radius-md, 12px);
		background: var(--ii-surface-elevated);
		overflow: hidden;
	}

	.an-pareto-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--ii-space-stack-xs, 10px) var(--ii-space-inline-md, 16px);
		border-bottom: 1px solid var(--ii-border-subtle);
		background: var(--ii-surface-alt);
	}

	.an-pareto-title {
		font-size: var(--ii-text-small, 0.8125rem);
		font-weight: 600;
		color: var(--ii-text-primary);
	}

	.an-pareto-progress {
		padding: var(--ii-space-stack-sm, 12px) var(--ii-space-inline-md, 16px);
		font-size: var(--ii-text-small, 0.8125rem);
		color: var(--ii-info);
		font-weight: 500;
	}

	.an-pareto-error {
		padding: var(--ii-space-stack-sm, 12px) var(--ii-space-inline-md, 16px);
		font-size: var(--ii-text-small, 0.8125rem);
		color: var(--ii-danger);
	}

	.an-pareto-result {
		padding: var(--ii-space-stack-sm, 12px) var(--ii-space-inline-md, 16px);
	}

	.an-pareto-subtitle {
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--ii-text-muted);
		margin: var(--ii-space-stack-sm, 12px) 0 var(--ii-space-stack-xs, 8px);
	}

	.an-weight-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
		gap: var(--ii-space-stack-2xs, 6px);
	}

	.an-weight-item {
		display: flex;
		justify-content: space-between;
		padding: var(--ii-space-stack-2xs, 4px) var(--ii-space-inline-sm, 8px);
		border-radius: var(--ii-radius-sm, 8px);
		background: var(--ii-surface-alt);
	}

	.an-weight-label {
		font-size: var(--ii-text-small, 0.8125rem);
		color: var(--ii-text-primary);
		font-weight: 500;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.an-weight-value {
		font-size: var(--ii-text-small, 0.8125rem);
		font-weight: 600;
		color: var(--ii-text-primary);
		font-variant-numeric: tabular-nums;
	}

	/* ── Responsive ──────────────────────────────────────────────────────── */
	@media (max-width: 768px) {
		.an-kpi-row {
			grid-template-columns: repeat(3, 1fr);
		}

		.an-layout {
			grid-template-columns: 1fr;
			grid-template-rows: auto 1fr;
			height: auto;
		}

		.an-master {
			border-right: none;
			border-bottom: 1px solid var(--ii-border-subtle);
			max-height: 250px;
		}
	}

	/* ── Correlation section ─────────────────────────────────────────────── */
	.an-corr-section {
		margin: var(--ii-space-stack-md, 16px) var(--ii-space-inline-lg, 24px) 0;
		border: 1px solid var(--ii-border-subtle);
		border-radius: var(--ii-radius-md, 12px);
		background: var(--ii-surface-elevated);
		overflow: hidden;
	}

	.an-corr-header {
		padding: var(--ii-space-stack-xs, 10px) var(--ii-space-inline-md, 16px);
		border-bottom: 1px solid var(--ii-border-subtle);
		background: var(--ii-surface-alt);
	}

	.an-section-title {
		font-size: var(--ii-text-small, 0.8125rem);
		font-weight: 600;
		color: var(--ii-text-primary);
	}

	.an-subsection-title {
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--ii-text-muted);
		margin-bottom: var(--ii-space-stack-xs, 8px);
	}

	.an-corr-metrics {
		padding: var(--ii-space-stack-sm, 12px) var(--ii-space-inline-md, 16px);
	}

	.an-corr-body {
		padding: 0 var(--ii-space-inline-md, 16px) var(--ii-space-stack-md, 16px);
	}

	.an-corr-eigen {
		margin-top: var(--ii-space-stack-md, 16px);
	}

	/* ── Rolling correlation ─────────────────────────────────────────────── */
	.an-rolling-section {
		padding: var(--ii-space-stack-md, 16px) var(--ii-space-inline-md, 16px);
		border-top: 1px solid var(--ii-border-subtle);
	}

	.an-rolling-error {
		padding: var(--ii-space-stack-xs, 8px);
		color: var(--ii-danger);
		font-size: var(--ii-text-small, 0.8125rem);
	}

	/* ── Backtest section ────────────────────────────────────────────────── */
	.an-backtest-section {
		margin: var(--ii-space-stack-md, 16px) var(--ii-space-inline-lg, 24px) 0;
		border: 1px solid var(--ii-border-subtle);
		border-radius: var(--ii-radius-md, 12px);
		background: var(--ii-surface-elevated);
		overflow: hidden;
	}

	.an-backtest-progress {
		display: flex;
		align-items: center;
		gap: var(--ii-space-inline-sm, 8px);
		padding: var(--ii-space-stack-sm, 12px) var(--ii-space-inline-md, 16px);
		font-size: var(--ii-text-small, 0.8125rem);
		color: var(--ii-info);
		font-weight: 500;
	}

	.an-backtest-pulse {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		background: var(--ii-info);
		animation: pulse 1.5s ease-in-out infinite;
	}

	@keyframes pulse {
		0%, 100% { opacity: 0.3; }
		50% { opacity: 1; }
	}

	.an-backtest-result {
		padding: var(--ii-space-stack-sm, 12px) var(--ii-space-inline-md, 16px);
	}

	.an-kpi-row--3 {
		grid-template-columns: repeat(3, 1fr);
	}

	.an-folds-table {
		width: 100%;
		border-collapse: collapse;
		font-size: var(--ii-text-small, 0.8125rem);
		margin-top: var(--ii-space-stack-sm, 12px);
	}

	.an-folds-table th {
		padding: var(--ii-space-stack-2xs, 5px) var(--ii-space-inline-sm, 10px);
		text-align: left;
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 600;
		color: var(--ii-text-muted);
		text-transform: uppercase;
		letter-spacing: 0.02em;
		border-bottom: 1px solid var(--ii-border-subtle);
	}

	.an-folds-table td {
		padding: var(--ii-space-stack-2xs, 5px) var(--ii-space-inline-sm, 10px);
		border-bottom: 1px solid var(--ii-border-subtle);
		font-variant-numeric: tabular-nums;
		color: var(--ii-text-secondary);
	}

	.fold-num {
		font-weight: 600;
		color: var(--ii-text-primary);
	}

	.fold-period {
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-muted);
	}
</style>
