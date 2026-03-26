<!-- Style Drift: stacked bar chart + drift signal table.
     Moved from us-fund-analysis/components/StyleDriftChart.svelte -->
<script lang="ts">
	import { formatPercent } from "@netz/ui/utils";
	import { ChartContainer } from "@netz/ui/charts";
	import type { SecStyleDrift } from "$lib/types/sec-analysis";
	import { EMPTY_STYLE_DRIFT } from "$lib/types/sec-analysis";

	let {
		api,
		cik,
		managerName,
	}: {
		api: { get: <T>(url: string) => Promise<T> };
		cik: string | null;
		managerName: string;
	} = $props();

	let drift = $state<SecStyleDrift>(EMPTY_STYLE_DRIFT);
	let loading = $state(false);

	$effect(() => {
		if (cik) {
			loading = true;
			api
				.get<SecStyleDrift>(`/sec/managers/${cik}/style-drift`)
				.then((d) => (drift = d))
				.catch(() => (drift = EMPTY_STYLE_DRIFT))
				.finally(() => (loading = false));
		}
	});

	let chartOption = $derived.by(() => {
		if (drift.history.length === 0) return null;
		const quarterMap = new Map<string, Map<string, number>>();
		const allSectors = new Set<string>();
		for (const point of drift.history) {
			if (!quarterMap.has(point.quarter)) quarterMap.set(point.quarter, new Map());
			quarterMap.get(point.quarter)!.set(point.sector, point.weight_pct);
			allSectors.add(point.sector);
		}
		const quarters = [...quarterMap.keys()].sort();
		const sectors = [...allSectors].sort();
		const series = sectors.map((sector) => ({
			name: sector,
			type: "bar" as const,
			stack: "total",
			emphasis: { focus: "series" as const },
			data: quarters.map((q) => {
				const val = quarterMap.get(q)?.get(sector) ?? 0;
				return +(val * 100).toFixed(2);
			}),
		}));
		return {
			tooltip: {
				trigger: "axis",
				axisPointer: { type: "shadow" },
				// eslint-disable-next-line @typescript-eslint/no-explicit-any
				formatter: (params: any[]) => {
					if (!Array.isArray(params)) return "";
					const header = `<strong>${params[0]?.axisValue ?? ""}</strong><br/>`;
					const rows = params.filter((p) => p.value > 0).map((p) => `${p.marker} ${p.seriesName}: ${p.value.toFixed(1)}%`).join("<br/>");
					return header + rows;
				},
			},
			legend: { type: "scroll", bottom: 0, textStyle: { fontSize: 11 } },
			grid: { left: 50, right: 20, top: 20, bottom: 60, containLabel: false },
			xAxis: { type: "category", data: quarters, axisLabel: { fontSize: 11 } },
			yAxis: { type: "value", axisLabel: { fontSize: 11, formatter: "{value}%" }, max: 100 },
			series,
		} as Record<string, unknown>;
	});
</script>

{#if !cik}
	<div class="sd-empty"><p>Select a fund with style analysis to view drift.</p></div>
{:else if loading}
	<p class="sd-loading">Loading style drift...</p>
{:else}
	<div class="sd-header">
		<h3 class="sd-title">{managerName} — Sector Allocation History</h3>
	</div>
	{#if chartOption}
		<div class="sd-chart"><ChartContainer option={chartOption} height={360} /></div>
	{:else}
		<div class="sd-empty"><p>No allocation history available.</p></div>
	{/if}
	{#if drift.drift_signals.length > 0}
		<h4 class="sd-subtitle">Drift Signals (Latest Quarter)</h4>
		<div class="sd-table-wrap">
			<table class="sd-table">
				<thead><tr>
					<th class="sd-th">Sector</th>
					<th class="sd-th sd-th--right">Current</th>
					<th class="sd-th sd-th--right">Previous</th>
					<th class="sd-th sd-th--right">Delta</th>
					<th class="sd-th">Signal</th>
				</tr></thead>
				<tbody>
					{#each drift.drift_signals as sig (sig.sector)}
						<tr class="sd-row">
							<td class="sd-td">{sig.sector}</td>
							<td class="sd-td sd-td--right">{formatPercent(sig.weight_current)}</td>
							<td class="sd-td sd-td--right">{formatPercent(sig.weight_prev)}</td>
							<td class="sd-td sd-td--right">
								<span class:sd-delta--up={sig.delta > 0} class:sd-delta--down={sig.delta < 0}>
									{sig.delta > 0 ? "+" : ""}{formatPercent(sig.delta)}
								</span>
							</td>
							<td class="sd-td">
								<span class="sd-signal" class:sd-signal--drift={sig.signal === "DRIFT"} class:sd-signal--stable={sig.signal === "STABLE"}>
									{sig.signal}
								</span>
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}
{/if}

<style>
	.sd-empty { padding: 48px 24px; text-align: center; color: var(--netz-text-muted); font-size: 14px; }
	.sd-loading { padding: 24px; color: var(--netz-text-muted); font-size: 13px; }
	.sd-header { padding: 8px 0; }
	.sd-title { font-size: 15px; font-weight: 600; color: var(--netz-text-primary); }
	.sd-chart { margin: 16px 0; }
	.sd-subtitle { font-size: 13px; font-weight: 600; color: var(--netz-text-secondary); margin: 16px 0 8px; }
	.sd-table-wrap { overflow-x: auto; }
	.sd-table { width: 100%; border-collapse: collapse; font-size: 13px; }
	.sd-th { padding: 8px 12px; text-align: left; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; color: var(--netz-text-muted); border-bottom: 1px solid var(--netz-border-subtle); white-space: nowrap; }
	.sd-th--right { text-align: right; }
	.sd-row:hover { background: var(--netz-surface-secondary); }
	.sd-td { padding: 8px 12px; border-bottom: 1px solid var(--netz-border-subtle); }
	.sd-td--right { text-align: right; font-variant-numeric: tabular-nums; }
	.sd-delta--up { color: var(--netz-color-success, #22c55e); }
	.sd-delta--down { color: var(--netz-color-error, #ef4444); }
	.sd-signal { display: inline-block; padding: 2px 8px; font-size: 11px; font-weight: 600; border-radius: 4px; }
	.sd-signal--drift { background: rgba(239, 68, 68, 0.1); color: var(--netz-color-error, #ef4444); }
	.sd-signal--stable { background: rgba(34, 197, 94, 0.1); color: var(--netz-color-success, #22c55e); }
</style>
