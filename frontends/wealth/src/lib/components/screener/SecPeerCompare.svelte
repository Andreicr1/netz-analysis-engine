<!-- Peer Compare: compare 2-5 managers side by side.
     Moved from us-fund-analysis/components/PeerCompare.svelte -->
<script lang="ts">
	import { formatPercent, formatCompact } from "@netz/ui/utils";
	import { Button } from "@netz/ui";
	import { ChartContainer } from "@netz/ui/charts";
	import type { SecPeerCompare, SecManagerFundBreakdown } from "$lib/types/sec-analysis";

	let {
		api,
		ciks,
	}: {
		api: { get: <T>(url: string, params?: Record<string, string>) => Promise<T> };
		ciks: string[];
	} = $props();

	let result = $state<SecPeerCompare | null>(null);
	let loading = $state(false);
	let error = $state<string | null>(null);

	async function runCompare() {
		if (ciks.length < 2) {
			error = "Select at least 2 managers to compare.";
			return;
		}
		loading = true;
		error = null;
		try {
			result = await api.get<SecPeerCompare>(
				`/sec/managers/compare?${ciks.map((c) => `ciks=${c}`).join("&")}`,
			);
		} catch {
			error = "Comparison failed. Please try again.";
			result = null;
		} finally {
			loading = false;
		}
	}

	let allSectors = $derived.by(() => {
		if (!result) return [];
		const sectors = new Set<string>();
		for (const alloc of Object.values(result.sector_allocations)) {
			for (const s of Object.keys(alloc)) sectors.add(s);
		}
		return [...sectors].sort();
	});
</script>

<div class="pc-header">
	<div class="pc-status">
		{#if ciks.length === 0}
			<p class="pc-hint">Select managers using checkboxes, then compare here.</p>
		{:else}
			<p class="pc-hint">{ciks.length} manager{ciks.length !== 1 ? "s" : ""} selected</p>
		{/if}
	</div>
	<Button size="sm" variant="default" disabled={ciks.length < 2} onclick={runCompare}>
		Compare ({ciks.length})
	</Button>
</div>

{#if loading}
	<p class="pc-loading">Comparing managers...</p>
{:else if error}
	<p class="pc-error">{error}</p>
{:else if result}
	<div class="pc-cards">
		{#each result.managers as mgr (mgr.cik)}
			<div class="pc-card">
				<div class="pc-card__name">{mgr.firm_name}</div>
				<div class="pc-card__row"><span class="pc-card__label">CIK</span><span class="pc-card__mono">{mgr.cik ?? "\u2014"}</span></div>
				<div class="pc-card__row"><span class="pc-card__label">AUM</span><span>{mgr.aum_total != null ? formatCompact(mgr.aum_total) : "\u2014"}</span></div>
				<div class="pc-card__row"><span class="pc-card__label">Holdings</span><span>{mgr.holdings_count}</span></div>
				<div class="pc-card__row"><span class="pc-card__label">HHI</span><span>{result.hhi_scores[mgr.cik ?? ""] != null ? formatPercent(result.hhi_scores[mgr.cik ?? ""]) : "\u2014"}</span></div>
			</div>
		{/each}
	</div>

	{#if allSectors.length > 0}
		<h4 class="pc-subtitle">Sector Allocation</h4>
		<div class="pc-table-wrap">
			<table class="pc-table">
				<thead><tr>
					<th class="pc-th">Sector</th>
					{#each result.managers as mgr (mgr.cik)}
						<th class="pc-th pc-th--right">{mgr.firm_name.slice(0, 20)}</th>
					{/each}
				</tr></thead>
				<tbody>
					{#each allSectors as sector}
						<tr class="pc-row">
							<td class="pc-td">{sector}</td>
							{#each result.managers as mgr (mgr.cik)}
								<td class="pc-td pc-td--right">{formatPercent(result.sector_allocations[mgr.cik ?? ""]?.[sector] ?? 0)}</td>
							{/each}
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}

	{#if result.overlaps.length > 0}
		<h4 class="pc-subtitle">Portfolio Overlap (Jaccard)</h4>
		<div class="pc-overlaps">
			{#each result.overlaps as o}
				<div class="pc-overlap">
					<span class="pc-overlap__pair">
						{result.managers.find((m) => m.cik === o.cik_a)?.firm_name?.slice(0, 15) ?? o.cik_a}
						&harr;
						{result.managers.find((m) => m.cik === o.cik_b)?.firm_name?.slice(0, 15) ?? o.cik_b}
					</span>
					<span class="pc-overlap__value">{formatPercent(o.overlap_pct)}</span>
				</div>
			{/each}
		</div>
	{/if}

	{@const fundEntries = Object.entries(result.fund_breakdowns ?? {})}
	{#if fundEntries.length > 0}
		<h4 class="pc-subtitle">Fund Structure Comparison</h4>
		<div class="pc-fund-grid">
			{#each fundEntries as [cik, bd] (cik)}
				{@const mgr = result.managers.find((m) => m.cik === cik)}
				<div class="pc-fund-card">
					<div class="pc-fund-card__name">{mgr?.firm_name?.slice(0, 25) ?? cik}</div>
					<div class="pc-fund-card__count">{bd.total_funds} fund{bd.total_funds !== 1 ? "s" : ""}</div>
					{#if bd.breakdown.length > 0}
						<ChartContainer
							height={180}
							option={{
								tooltip: { trigger: "item", formatter: "{b}: {c} ({d}%)" },
								color: ["#6366f1", "#22d3ee", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6", "#ec4899"],
								series: [{
									type: "pie", radius: ["35%", "65%"], avoidLabelOverlap: true,
									itemStyle: { borderRadius: 4, borderColor: "transparent", borderWidth: 1 },
									label: { show: true, fontSize: 10, formatter: "{b}" },
									data: bd.breakdown.map((b) => ({ name: b.fund_type, value: b.fund_count })),
								}],
							}}
						/>
					{:else}
						<div class="pc-fund-empty">No fund data</div>
					{/if}
				</div>
			{/each}
		</div>
	{/if}
{/if}

<style>
	.pc-header { display: flex; justify-content: space-between; align-items: center; padding: 8px 0; }
	.pc-hint { font-size: 13px; color: var(--netz-text-muted); }
	.pc-loading, .pc-error { padding: 24px; font-size: 13px; }
	.pc-loading { color: var(--netz-text-muted); }
	.pc-error { color: var(--netz-color-error, #ef4444); }
	.pc-cards { display: grid; grid-template-columns: repeat(auto-fill, minmax(200px, 1fr)); gap: 12px; margin: 16px 0; }
	.pc-card { padding: 12px; border: 1px solid var(--netz-border-subtle); border-radius: 8px; background: var(--netz-surface-secondary); }
	.pc-card__name { font-size: 13px; font-weight: 600; margin-bottom: 8px; color: var(--netz-text-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
	.pc-card__row { display: flex; justify-content: space-between; font-size: 12px; padding: 2px 0; }
	.pc-card__label { color: var(--netz-text-muted); }
	.pc-card__mono { font-family: "IBM Plex Mono", monospace; font-size: 11px; }
	.pc-subtitle { font-size: 13px; font-weight: 600; color: var(--netz-text-secondary); margin: 16px 0 8px; }
	.pc-table-wrap { overflow-x: auto; }
	.pc-table { width: 100%; border-collapse: collapse; font-size: 13px; }
	.pc-th { padding: 8px 12px; text-align: left; font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.04em; color: var(--netz-text-muted); border-bottom: 1px solid var(--netz-border-subtle); white-space: nowrap; }
	.pc-th--right { text-align: right; }
	.pc-row:hover { background: var(--netz-surface-secondary); }
	.pc-td { padding: 8px 12px; border-bottom: 1px solid var(--netz-border-subtle); }
	.pc-td--right { text-align: right; font-variant-numeric: tabular-nums; }
	.pc-overlaps { display: flex; flex-direction: column; gap: 8px; }
	.pc-overlap { display: flex; justify-content: space-between; padding: 8px 12px; border: 1px solid var(--netz-border-subtle); border-radius: 6px; font-size: 13px; }
	.pc-overlap__pair { color: var(--netz-text-secondary); }
	.pc-overlap__value { font-weight: 600; font-variant-numeric: tabular-nums; }
	.pc-fund-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); gap: 12px; margin: 12px 0; }
	.pc-fund-card { padding: 12px; border: 1px solid var(--netz-border-subtle); border-radius: 8px; background: var(--netz-surface-secondary); }
	.pc-fund-card__name { font-size: 13px; font-weight: 600; color: var(--netz-text-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-bottom: 2px; }
	.pc-fund-card__count { font-size: 11px; color: var(--netz-text-muted); margin-bottom: 8px; }
	.pc-fund-empty { font-size: 12px; color: var(--netz-text-muted); padding: 20px 0; text-align: center; }
</style>
