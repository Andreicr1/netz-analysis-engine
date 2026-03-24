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
		PageHeader, StatusBadge,
		formatPercent, formatDateTime,
	} from "@netz/ui";
	import { createClientApiClient } from "$lib/api/client";
	import type { PageData } from "./$types";
	import type { AttributionResult, ParetoResult, SectorAttribution, StrategyDriftAlert, Timeframe } from "$lib/types/analytics";
	import { effectColor, severityColor } from "$lib/types/analytics";
	import { Button } from "@netz/ui";

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

<style>
	/* ── Controls ─────────────────────────────────────────────────────────── */
	.an-controls {
		display: flex;
		align-items: center;
		gap: var(--netz-space-inline-sm, 10px);
	}

	.an-select {
		height: var(--netz-space-control-height-sm, 32px);
		padding: 0 var(--netz-space-inline-sm, 10px);
		border: 1px solid var(--netz-border);
		border-radius: var(--netz-radius-sm, 8px);
		background: var(--netz-surface-elevated);
		color: var(--netz-text-primary);
		font-size: var(--netz-text-small, 0.8125rem);
		font-family: var(--netz-font-sans);
	}

	.an-timeframe {
		display: flex;
		border: 1px solid var(--netz-border);
		border-radius: var(--netz-radius-sm, 8px);
		overflow: hidden;
	}

	.an-tf-btn {
		padding: 4px 12px;
		border: none;
		border-right: 1px solid var(--netz-border);
		background: transparent;
		color: var(--netz-text-secondary);
		font-size: var(--netz-text-label, 0.75rem);
		font-weight: 600;
		font-family: var(--netz-font-sans);
		cursor: pointer;
		transition: background-color 120ms ease, color 120ms ease;
	}

	.an-tf-btn:last-child {
		border-right: none;
	}

	.an-tf-btn:hover {
		background: var(--netz-surface-alt);
	}

	.an-tf-btn--active {
		background: color-mix(in srgb, var(--netz-brand-primary) 12%, transparent);
		color: var(--netz-brand-primary);
	}

	/* ── KPI row ─────────────────────────────────────────────────────────── */
	.an-kpi-row {
		display: grid;
		grid-template-columns: repeat(6, 1fr);
		gap: 1px;
		margin: 0 var(--netz-space-inline-lg, 24px);
		border: 1px solid var(--netz-border-subtle);
		border-radius: var(--netz-radius-md, 12px);
		overflow: hidden;
		background: var(--netz-border-subtle);
	}

	.an-kpi {
		display: flex;
		flex-direction: column;
		gap: 2px;
		padding: var(--netz-space-stack-xs, 10px) var(--netz-space-inline-sm, 12px);
		background: var(--netz-surface-elevated);
	}

	.an-kpi-label {
		font-size: var(--netz-text-label, 0.75rem);
		color: var(--netz-text-muted);
	}

	.an-kpi-value {
		font-size: var(--netz-text-body, 0.9375rem);
		font-weight: 700;
		color: var(--netz-text-primary);
		font-variant-numeric: tabular-nums;
	}

	/* ── Master/Detail layout ────────────────────────────────────────────── */
	.an-layout {
		display: grid;
		grid-template-columns: 260px 1fr;
		gap: 0;
		height: calc(100vh - 180px);
		margin: var(--netz-space-stack-sm, 12px) var(--netz-space-inline-lg, 24px) 0;
		border: 1px solid var(--netz-border-subtle);
		border-radius: var(--netz-radius-md, 12px);
		overflow: hidden;
	}

	/* Master (left) */
	.an-master {
		overflow-y: auto;
		border-right: 1px solid var(--netz-border-subtle);
		background: var(--netz-surface-elevated);
	}

	.an-master-title {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--netz-space-stack-xs, 10px) var(--netz-space-inline-md, 16px);
		font-size: var(--netz-text-label, 0.75rem);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--netz-text-muted);
		border-bottom: 1px solid var(--netz-border-subtle);
		background: var(--netz-surface-alt);
	}

	.an-empty {
		padding: var(--netz-space-stack-lg, 32px);
		text-align: center;
		color: var(--netz-text-muted);
		font-size: var(--netz-text-small, 0.8125rem);
	}

	.an-sector-list {
		display: flex;
		flex-direction: column;
	}

	.an-sector-item {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: var(--netz-space-stack-2xs, 8px) var(--netz-space-inline-md, 16px);
		border: none;
		border-bottom: 1px solid var(--netz-border-subtle);
		background: transparent;
		font-family: var(--netz-font-sans);
		cursor: pointer;
		transition: background-color 120ms ease;
		text-align: left;
	}

	.an-sector-item:hover {
		background: var(--netz-surface-alt);
	}

	.an-sector-item--active {
		background: color-mix(in srgb, var(--netz-brand-primary) 8%, transparent);
	}

	.an-sector-name {
		font-size: var(--netz-text-small, 0.8125rem);
		font-weight: 500;
		color: var(--netz-text-primary);
	}

	.an-sector-effect {
		font-size: var(--netz-text-small, 0.8125rem);
		font-weight: 600;
		font-variant-numeric: tabular-nums;
	}

	/* Drift section */
	.an-drift-section {
		border-top: 2px solid var(--netz-border);
	}

	.an-drift-count {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		min-width: 18px;
		height: 18px;
		padding: 0 5px;
		border-radius: 9px;
		background: var(--netz-warning);
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
		gap: var(--netz-space-inline-xs, 6px);
		padding: var(--netz-space-stack-2xs, 5px) var(--netz-space-inline-md, 16px);
		border-bottom: 1px solid var(--netz-border-subtle);
		font-size: var(--netz-text-small, 0.8125rem);
	}

	.an-drift-name {
		flex: 1;
		color: var(--netz-text-primary);
		font-weight: 500;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.an-drift-badge {
		font-size: var(--netz-text-label, 0.75rem);
		font-weight: 600;
		text-transform: uppercase;
	}

	.an-drift-meta {
		font-size: var(--netz-text-label, 0.75rem);
		color: var(--netz-text-muted);
		font-variant-numeric: tabular-nums;
	}

	/* Detail (right) */
	.an-detail {
		overflow-y: auto;
		padding: var(--netz-space-stack-md, 16px) var(--netz-space-inline-lg, 24px);
		background: var(--netz-surface);
	}

	.an-detail-title {
		font-size: var(--netz-text-body, 0.9375rem);
		font-weight: 600;
		color: var(--netz-text-primary);
		margin-bottom: var(--netz-space-stack-md, 16px);
	}

	/* Single sector bars */
	.an-bar-group {
		display: flex;
		flex-direction: column;
		gap: var(--netz-space-stack-md, 16px);
	}

	.an-bar-row {
		display: flex;
		align-items: center;
		gap: var(--netz-space-inline-sm, 10px);
	}

	.an-bar-label {
		width: 80px;
		font-size: var(--netz-text-small, 0.8125rem);
		font-weight: 500;
		color: var(--netz-text-secondary);
		flex-shrink: 0;
	}

	.an-bar-track {
		flex: 1;
		height: 24px;
		background: var(--netz-surface-alt);
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
		background: var(--netz-border);
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
		background: var(--netz-success);
	}

	.an-bar-fill--negative {
		right: 50%;
		background: var(--netz-danger);
	}

	.an-bar-value {
		width: 80px;
		text-align: right;
		font-size: var(--netz-text-small, 0.8125rem);
		font-weight: 600;
		font-variant-numeric: tabular-nums;
		flex-shrink: 0;
	}

	.an-sector-total {
		margin-top: var(--netz-space-stack-md, 16px);
		padding-top: var(--netz-space-stack-sm, 12px);
		border-top: 1px solid var(--netz-border-subtle);
		font-size: var(--netz-text-body, 0.9375rem);
		color: var(--netz-text-secondary);
	}

	/* All sectors comparative */
	.an-all-sectors {
		display: flex;
		flex-direction: column;
		gap: var(--netz-space-stack-xs, 8px);
	}

	.an-comp-row {
		display: flex;
		align-items: center;
		gap: var(--netz-space-inline-sm, 10px);
	}

	.an-comp-label {
		width: 140px;
		font-size: var(--netz-text-small, 0.8125rem);
		font-weight: 500;
		color: var(--netz-text-primary);
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
		background: var(--netz-surface-alt);
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
		background: var(--netz-border);
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

	.an-comp-fill--alloc.an-comp-fill--positive { background: color-mix(in srgb, var(--netz-success) 70%, transparent); }
	.an-comp-fill--alloc.an-comp-fill--negative { background: color-mix(in srgb, var(--netz-danger) 70%, transparent); }
	.an-comp-fill--sel.an-comp-fill--positive { background: var(--netz-info); }
	.an-comp-fill--sel.an-comp-fill--negative { background: var(--netz-warning); }

	.an-comp-total {
		width: 70px;
		text-align: right;
		font-size: var(--netz-text-small, 0.8125rem);
		font-weight: 600;
		font-variant-numeric: tabular-nums;
		flex-shrink: 0;
	}

	.an-legend {
		display: flex;
		gap: var(--netz-space-inline-md, 16px);
		padding-top: var(--netz-space-stack-xs, 8px);
		border-top: 1px solid var(--netz-border-subtle);
	}

	.an-legend-item {
		display: flex;
		align-items: center;
		gap: 4px;
		font-size: var(--netz-text-label, 0.75rem);
		color: var(--netz-text-muted);
	}

	.an-legend-dot {
		width: 10px;
		height: 6px;
		border-radius: 2px;
	}

	.an-legend-dot--alloc { background: var(--netz-success); }
	.an-legend-dot--sel { background: var(--netz-info); }

	/* ── Pareto section ──────────────────────────────────────────────────── */
	.an-pareto-section {
		margin: var(--netz-space-stack-md, 16px) var(--netz-space-inline-lg, 24px) 0;
		border: 1px solid var(--netz-border-subtle);
		border-radius: var(--netz-radius-md, 12px);
		background: var(--netz-surface-elevated);
		overflow: hidden;
	}

	.an-pareto-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--netz-space-stack-xs, 10px) var(--netz-space-inline-md, 16px);
		border-bottom: 1px solid var(--netz-border-subtle);
		background: var(--netz-surface-alt);
	}

	.an-pareto-title {
		font-size: var(--netz-text-small, 0.8125rem);
		font-weight: 600;
		color: var(--netz-text-primary);
	}

	.an-pareto-progress {
		padding: var(--netz-space-stack-sm, 12px) var(--netz-space-inline-md, 16px);
		font-size: var(--netz-text-small, 0.8125rem);
		color: var(--netz-info);
		font-weight: 500;
	}

	.an-pareto-error {
		padding: var(--netz-space-stack-sm, 12px) var(--netz-space-inline-md, 16px);
		font-size: var(--netz-text-small, 0.8125rem);
		color: var(--netz-danger);
	}

	.an-pareto-result {
		padding: var(--netz-space-stack-sm, 12px) var(--netz-space-inline-md, 16px);
	}

	.an-pareto-subtitle {
		font-size: var(--netz-text-label, 0.75rem);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--netz-text-muted);
		margin: var(--netz-space-stack-sm, 12px) 0 var(--netz-space-stack-xs, 8px);
	}

	.an-weight-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
		gap: var(--netz-space-stack-2xs, 6px);
	}

	.an-weight-item {
		display: flex;
		justify-content: space-between;
		padding: var(--netz-space-stack-2xs, 4px) var(--netz-space-inline-sm, 8px);
		border-radius: var(--netz-radius-sm, 8px);
		background: var(--netz-surface-alt);
	}

	.an-weight-label {
		font-size: var(--netz-text-small, 0.8125rem);
		color: var(--netz-text-primary);
		font-weight: 500;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.an-weight-value {
		font-size: var(--netz-text-small, 0.8125rem);
		font-weight: 600;
		color: var(--netz-text-primary);
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
			border-bottom: 1px solid var(--netz-border-subtle);
			max-height: 250px;
		}
	}
</style>
