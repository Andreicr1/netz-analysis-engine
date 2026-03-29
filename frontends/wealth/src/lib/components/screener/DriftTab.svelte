<!--
  Drift tab — quarterly turnover timeline bar chart + churn metrics.
  Lazy-loaded when tab is activated.
-->
<script lang="ts">
	import "./screener.css";
	import { getContext } from "svelte";
	import { SvelteMap } from "svelte/reactivity";
	import { createClientApiClient } from "$lib/api/client";
	import { formatPercent, formatNumber } from "@investintell/ui";
	import type { ManagerDriftData, DriftQuarter } from "$lib/types/manager-screener";

	interface Props {
		crd: string | null;
	}

	let { crd }: Props = $props();

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	// Cache per CRD
	const cache = new SvelteMap<string, ManagerDriftData>();

	let loading = $state(false);
	let error = $state<string | null>(null);
	let data = $state<ManagerDriftData | null>(null);

	$effect(() => {
		if (!crd) {
			data = null;
			return;
		}

		const currentCrd = crd;
		const controller = new AbortController();

		const cached = cache.get(currentCrd);
		if (cached) {
			data = cached;
			return;
		}

		loading = true;
		error = null;

		(async () => {
			try {
				const api = createClientApiClient(getToken);
				const result = await api.get<ManagerDriftData>(
					`/manager-screener/managers/${currentCrd}/drift`,
				);
				if (!controller.signal.aborted) {
					cache.set(currentCrd, result);
					data = result;
				}
			} catch (e) {
				if (!controller.signal.aborted) {
					error = e instanceof Error ? e.message : "Failed to load drift data";
				}
			} finally {
				if (!controller.signal.aborted) {
					loading = false;
				}
			}
		})();

		return () => controller.abort();
	});

	function topGainers(q: DriftQuarter) {
		return q.new_positions + q.increased;
	}

	function topLosers(q: DriftQuarter) {
		return q.exited_positions + q.decreased;
	}

	function turnoverColor(turnover: number): string {
		if (turnover > 0.3) return "var(--ii-danger)";
		if (turnover > 0.15) return "var(--ii-warning)";
		return "var(--ii-success)";
	}
</script>

{#if !crd}
	<div class="dt-section">
		<p class="dt-empty-text">Institutional data unavailable — This manager is not registered with the SEC.</p>
	</div>
{:else if loading}
	<div class="dt-loading">Loading drift data…</div>
{:else if error}
	<div class="dt-section">
		<p class="dt-empty-text" style="color: var(--ii-danger)">{error}</p>
	</div>
{:else if data && data.quarters.length > 0}
	{#if data.style_drift_detected}
		<div class="drift-alert">
			Style drift detected — turnover exceeded 30% in one or more quarters
		</div>
	{/if}

	<!-- Turnover timeline bar chart -->
	<div class="dt-section">
		<h4 class="dt-section-title">Quarterly Turnover</h4>
		<div class="drift-chart">
			{#each data.quarters as q (q.quarter)}
				<div class="drift-bar-col">
					<div class="drift-bar-track">
						<div
							class="drift-bar-fill"
							style:height="{Math.min(q.turnover * 100, 100)}%"
							style:background={turnoverColor(q.turnover)}
						></div>
					</div>
					<span class="drift-bar-label">{q.quarter.slice(0, 7)}</span>
					<span class="drift-bar-value">{formatPercent(q.turnover)}</span>
				</div>
			{/each}
		</div>
	</div>

	<!-- Churn metrics table -->
	<div class="dt-section">
		<h4 class="dt-section-title">Churn Metrics</h4>
		<table class="criteria-table">
			<thead>
				<tr>
					<th>Quarter</th>
					<th>Turnover</th>
					<th>Gainers</th>
					<th>Losers</th>
					<th>Total</th>
				</tr>
			</thead>
			<tbody>
				{#each data.quarters as q (q.quarter)}
					<tr>
						<td class="criteria-val">{q.quarter.slice(0, 7)}</td>
						<td class="criteria-val" style:color={turnoverColor(q.turnover)}>{formatPercent(q.turnover)}</td>
						<td class="criteria-val" style="color: var(--ii-success)">{formatNumber(topGainers(q))}</td>
						<td class="criteria-val" style="color: var(--ii-danger)">{formatNumber(topLosers(q))}</td>
						<td class="criteria-val">{formatNumber(q.total_changes)}</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
{:else}
	<div class="dt-empty">No drift data available.</div>
{/if}

<style>
	.drift-alert {
		padding: var(--ii-space-stack-xs, 8px) var(--ii-space-inline-md, 16px);
		background: color-mix(in srgb, var(--ii-danger) 8%, transparent);
		color: var(--ii-danger);
		font-size: var(--ii-text-small, 0.8125rem);
		font-weight: 500;
		border-bottom: 1px solid var(--ii-border-subtle);
	}

	.drift-chart {
		display: flex;
		gap: var(--ii-space-inline-xs, 6px);
		align-items: flex-end;
		height: 120px;
		padding-top: var(--ii-space-stack-xs, 8px);
	}

	.drift-bar-col {
		flex: 1;
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 2px;
		min-width: 32px;
	}

	.drift-bar-track {
		width: 100%;
		height: 80px;
		background: var(--ii-surface-alt);
		border-radius: 3px;
		overflow: hidden;
		display: flex;
		align-items: flex-end;
	}

	.drift-bar-fill {
		width: 100%;
		border-radius: 3px 3px 0 0;
		transition: height 300ms ease;
	}

	.drift-bar-label {
		font-size: 9px;
		color: var(--ii-text-muted);
		white-space: nowrap;
	}

	.drift-bar-value {
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 600;
		font-variant-numeric: tabular-nums;
		color: var(--ii-text-primary);
	}
</style>
