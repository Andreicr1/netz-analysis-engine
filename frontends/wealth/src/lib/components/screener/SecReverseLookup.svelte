<!-- Reverse Lookup: search by CUSIP to show all holders.
     Moved from us-fund-analysis/components/ReverseLookup.svelte -->
<script lang="ts">
	import { formatNumber, formatCompact, formatPercent } from "@netz/ui/utils";
	import { Button } from "@netz/ui";
	import { ChartContainer } from "@netz/ui/charts";
	import type { SecReverseLookup, SecHoldingsHistory } from "$lib/types/sec-analysis";
	import { EMPTY_REVERSE } from "$lib/types/sec-analysis";

	let {
		api,
	}: {
		api: { get: <T>(url: string, params?: Record<string, string>) => Promise<T> };
	} = $props();

	let cusipInput = $state("");
	let result = $state<SecReverseLookup>(EMPTY_REVERSE);
	let history = $state<SecHoldingsHistory | null>(null);
	let loading = $state(false);
	let searched = $state(false);

	async function search() {
		const cusip = cusipInput.trim().toUpperCase();
		if (cusip.length < 6) return;
		loading = true;
		searched = true;
		history = null;
		try {
			const [holders, hist] = await Promise.all([
				api.get<SecReverseLookup>("/sec/holdings/reverse", { cusip }),
				api.get<SecHoldingsHistory>("/sec/holdings/history", { cusip }).catch(() => null),
			]);
			result = holders;
			history = hist;
		} catch {
			result = EMPTY_REVERSE;
		} finally {
			loading = false;
		}
	}

	let historyChartOption = $derived.by(() => {
		if (!history || history.quarters.length === 0) return null;
		const quarters = history.quarters.map((q) => q.quarter);
		const holders = history.quarters.map((q) => q.total_holders);
		const values = history.quarters.map((q) => q.total_market_value / 1e9);
		return {
			tooltip: { trigger: "axis" },
			legend: { data: ["Holders", "Market Value ($B)"], bottom: 0, textStyle: { fontSize: 11 } },
			grid: { left: 50, right: 50, top: 20, bottom: 40 },
			xAxis: { type: "category", data: quarters, axisLabel: { fontSize: 10 } },
			yAxis: [
				{ type: "value", name: "Holders", position: "left", axisLabel: { fontSize: 10 } },
				{ type: "value", name: "$B", position: "right", axisLabel: { fontSize: 10 } },
			],
			series: [
				{ name: "Holders", type: "line", data: holders, smooth: true, yAxisIndex: 0 },
				{ name: "Market Value ($B)", type: "line", data: values, smooth: true, yAxisIndex: 1 },
			],
		};
	});
</script>

<form class="rl-search" onsubmit={(e) => { e.preventDefault(); search(); }} role="search">
	<input class="rl-input" type="text" placeholder="Enter CUSIP (e.g. 594918104)..." bind:value={cusipInput} />
	<Button size="sm" variant="default" onclick={search}>Search</Button>
</form>

{#if loading}
	<p class="rl-loading">Searching holders...</p>
{:else if searched && result.holders.length === 0}
	<div class="rl-empty"><p>No holders found for this CUSIP.</p></div>
{:else if result.holders.length > 0}
	<div class="rl-header">
		<h3 class="rl-title">{result.company_name ?? result.cusip}</h3>
		<span class="rl-count">{formatNumber(result.total_holders, 0)} holders</span>
	</div>
	{#if historyChartOption}
		<div class="rl-chart-section">
			<span class="rl-chart-label">Institutional Ownership — {result.company_name ?? result.cusip}</span>
			<ChartContainer height={200} option={historyChartOption} />
		</div>
	{/if}
	<div class="rl-table-wrap">
		<table class="rl-table">
			<thead><tr>
				<th class="rl-th">Manager</th>
				<th class="rl-th">CIK</th>
				<th class="rl-th rl-th--right">Shares</th>
				<th class="rl-th rl-th--right">Value ($)</th>
				<th class="rl-th rl-th--right">% of Total</th>
				<th class="rl-th">Quarter</th>
			</tr></thead>
			<tbody>
				{#each result.holders as holder (holder.cik)}
					<tr class="rl-row">
						<td class="rl-td rl-td--name">{holder.firm_name}</td>
						<td class="rl-td rl-td--mono">{holder.cik}</td>
						<td class="rl-td rl-td--right">{holder.shares != null ? formatNumber(holder.shares, 0) : "\u2014"}</td>
						<td class="rl-td rl-td--right">{holder.market_value != null ? formatCompact(holder.market_value) : "\u2014"}</td>
						<td class="rl-td rl-td--right">{holder.pct_of_total != null ? formatPercent(holder.pct_of_total) : "\u2014"}</td>
						<td class="rl-td">{holder.report_date}</td>
					</tr>
				{/each}
			</tbody>
		</table>
	</div>
{:else if !searched}
	<div class="rl-empty"><p>Enter a CUSIP to find which managers hold this security.</p></div>
{/if}

<style>
	.rl-search { display: flex; gap: 8px; align-items: center; padding: 8px 0; }
	.rl-input { flex: 1; max-width: 300px; padding: 6px 10px; font-size: 13px; font-family: "IBM Plex Mono", monospace; border: 1px solid var(--netz-border-subtle); border-radius: 6px; background: var(--netz-surface-primary); color: var(--netz-text-primary); }
	.rl-input:focus { outline: none; border-color: var(--netz-border-accent); }
	.rl-loading { padding: 24px; color: var(--netz-text-muted); font-size: 13px; }
	.rl-empty { padding: 48px 24px; text-align: center; color: var(--netz-text-muted); font-size: 14px; }
	.rl-header { display: flex; justify-content: space-between; align-items: center; padding: 8px 0; }
	.rl-title { font-size: 15px; font-weight: 600; color: var(--netz-text-primary); }
	.rl-count { font-size: 12px; color: var(--netz-text-muted); }
	.rl-table-wrap { overflow-x: auto; }
	.rl-table { width: 100%; border-collapse: collapse; font-size: 13px; }
	.rl-th { padding: 8px 12px; text-align: left; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; color: var(--netz-text-muted); border-bottom: 1px solid var(--netz-border-subtle); white-space: nowrap; }
	.rl-th--right { text-align: right; }
	.rl-row:hover { background: var(--netz-surface-secondary); }
	.rl-td { padding: 8px 12px; border-bottom: 1px solid var(--netz-border-subtle); white-space: nowrap; }
	.rl-td--name { max-width: 280px; overflow: hidden; text-overflow: ellipsis; font-weight: 500; }
	.rl-td--mono { font-family: "IBM Plex Mono", monospace; font-size: 12px; }
	.rl-td--right { text-align: right; font-variant-numeric: tabular-nums; }
	.rl-chart-section { padding: 8px 0 16px; border-bottom: 1px solid var(--netz-border-subtle); margin-bottom: 12px; }
	.rl-chart-label { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; color: var(--netz-text-muted); }
</style>
