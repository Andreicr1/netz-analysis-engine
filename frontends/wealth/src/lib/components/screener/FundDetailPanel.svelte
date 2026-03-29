<!--
  Fund detail panel — screening layers, score, history.
-->
<script lang="ts">
	import "./screener.css";
	import { getContext } from "svelte";
	import { StatusBadge, formatPercent, formatDateTime } from "@investintell/ui";
	import { createClientApiClient } from "$lib/api/client";
	import type { ScreeningResult, CriterionResult } from "$lib/types/screening";

	interface Props {
		selectedFund: ScreeningResult;
	}

	let { selectedFund }: Props = $props();

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let fundHistory = $state<ScreeningResult[]>([]);
	let fundHistoryLoading = $state(false);

	$effect(() => {
		if (selectedFund?.instrument_id) {
			void loadFundHistory(selectedFund.instrument_id);
		}
	});

	async function loadFundHistory(instrumentId: string) {
		fundHistoryLoading = true;
		try {
			const api = createClientApiClient(getToken);
			fundHistory = await api.get<ScreeningResult[]>(`/screener/results/${instrumentId}`);
		} catch {
			fundHistory = [];
		} finally {
			fundHistoryLoading = false;
		}
	}

	function instrumentLabel(r: ScreeningResult): string {
		return r.name ?? r.instrument_id.slice(0, 8).toUpperCase();
	}

	function typeLabel(type: string | undefined): string {
		switch (type) {
			case "fund":   return "Fund";
			case "bond":   return "Fixed Income";
			case "equity": return "Equity";
			default:       return type ?? "—";
		}
	}

	function layerDotStatus(r: ScreeningResult, layer: number): "pass" | "fail" | "none" {
		if (r.failed_at_layer === layer) return "fail";
		if (r.failed_at_layer !== null && r.failed_at_layer < layer) return "none";
		return "pass";
	}

	function scoreColor(score: number | null): string {
		if (score === null) return "var(--ii-text-muted)";
		if (score >= 0.7) return "var(--ii-success)";
		if (score >= 0.4) return "var(--ii-warning)";
		return "var(--ii-danger)";
	}

	function ddLabel(type: string): string {
		switch (type) {
			case "dd_report":  return "DD Report";
			case "bond_brief": return "Bond Brief";
			case "none":       return "—";
			default:           return type;
		}
	}

	function layerCriteria(r: ScreeningResult, layer: number): CriterionResult[] {
		return r.layer_results.filter((c) => c.layer === layer);
	}
</script>

<div class="dt-section">
	<div class="dt-header-row">
		<StatusBadge status={selectedFund.overall_status} />
		{#if selectedFund.score !== null}
			<span class="dt-score" style:color={scoreColor(selectedFund.score)}>
				Score: {formatPercent(selectedFund.score)}
			</span>
		{/if}
	</div>
	<div class="dt-fund-meta">
		{#if selectedFund.isin}<span>ISIN: {selectedFund.isin}</span>{/if}
		{#if selectedFund.ticker}<span>Ticker: {selectedFund.ticker}</span>{/if}
		{#if selectedFund.instrument_type}<span>Type: {typeLabel(selectedFund.instrument_type)}</span>{/if}
		{#if selectedFund.manager}<span>Manager: {selectedFund.manager}</span>{/if}
		<span>Screened: {formatDateTime(selectedFund.screened_at)}</span>
		<span>Next: {ddLabel(selectedFund.required_analysis_type)}</span>
	</div>
</div>

{#each [1, 2, 3] as layer (layer)}
	{@const criteria = layerCriteria(selectedFund, layer)}
	{#if criteria.length > 0}
		<div class="dt-layer">
			<h4 class="dt-layer-title">
				<span class="layer-dot layer-dot--{layerDotStatus(selectedFund, layer)}"></span>
				Layer {layer}
				{#if layer === 1}— Eliminatory{:else if layer === 2}— Mandate Fit{:else}— Quant{/if}
			</h4>
			<table class="criteria-table">
				<thead>
					<tr>
						<th>Criterion</th>
						<th>Expected</th>
						<th>Actual</th>
						<th></th>
					</tr>
				</thead>
				<tbody>
					{#each criteria as c (c.criterion)}
						<tr class:criteria-fail={!c.passed}>
							<td class="criteria-name">{c.criterion}</td>
							<td class="criteria-val">{c.expected}</td>
							<td class="criteria-val">{c.actual}</td>
							<td class="criteria-icon">{c.passed ? "✓" : "✗"}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}
{/each}

<!-- Screening History -->
<div class="dt-section">
	<h4 class="dt-section-title">Screening History</h4>
	{#if fundHistoryLoading}
		<p class="dt-empty">Loading history…</p>
	{:else if fundHistory.length <= 1}
		<p class="dt-empty">No previous screenings.</p>
	{:else}
		<table class="criteria-table">
			<thead>
				<tr>
					<th>Date</th>
					<th>Status</th>
					<th>Score</th>
					<th>Failed</th>
				</tr>
			</thead>
			<tbody>
				{#each fundHistory as h (h.id)}
					<tr class:criteria-fail={h.overall_status === "FAIL"}>
						<td class="criteria-val">{formatDateTime(h.screened_at)}</td>
						<td><StatusBadge status={h.overall_status} /></td>
						<td class="criteria-val" style:color={scoreColor(h.score)}>{h.score !== null ? formatPercent(h.score) : "—"}</td>
						<td class="criteria-val">{h.failed_at_layer !== null ? `L${h.failed_at_layer}` : "—"}</td>
					</tr>
				{/each}
			</tbody>
		</table>
	{/if}
</div>
