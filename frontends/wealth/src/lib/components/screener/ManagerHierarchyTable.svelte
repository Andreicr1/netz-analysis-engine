<!--
  Manager hierarchy table — manager rows (L1) + fund sub-rows (L2) with expand/collapse.
-->
<script lang="ts">
	import "./screener.css";
	import { goto } from "$app/navigation";
	import { page } from "$app/stores";
	import { Button } from "@investintell/ui/components/ui/button";
	import { Checkbox } from "@investintell/ui/components/ui/checkbox";
	import { StatusBadge, formatAUM, formatPercent } from "@investintell/ui";
	import type { ScreeningResult } from "$lib/types/screening";
	import type { ManagerRow, ScreenerPage } from "$lib/types/manager-screener";

	interface Props {
		screener: ScreenerPage;
		filteredResults: ScreeningResult[];
		hasFundFilters: boolean;
		expandedManagers: Set<string>;
		selectedManagers: Set<string>;
		onToggleExpand: (crd: string) => void;
		onToggleSelection: (crd: string) => void;
		onOpenManagerDetail: (manager: ManagerRow) => void;
		onOpenFundDetail: (fund: ScreeningResult) => void;
	}

	let {
		screener, filteredResults, hasFundFilters,
		expandedManagers, selectedManagers,
		onToggleExpand, onToggleSelection, onOpenManagerDetail, onOpenFundDetail,
	}: Props = $props();

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

	function fundSubRows(crd: string): ScreeningResult[] {
		return filteredResults.filter((r) => r.manager_crd === crd);
	}

	function isLastFund(crd: string, idx: number): boolean {
		return idx === fundSubRows(crd).length - 1;
	}

	function goToPage(p: number) {
		const params = new URLSearchParams($page.url.searchParams);
		params.set("page", String(p));
		goto(`/screener?${params.toString()}`, { invalidateAll: true });
	}
</script>

<div class="scr-data-header">
	<span class="scr-data-count">
		{screener.total_count} manager{screener.total_count !== 1 ? "s" : ""}
		{#if hasFundFilters}
			<span class="scr-data-count-muted">· {filteredResults.length} fund{filteredResults.length !== 1 ? "s" : ""}</span>
		{/if}
	</span>
</div>

{#if screener.managers.length === 0}
	<div class="scr-empty">No managers found. Adjust filters or search.</div>
{:else}
	<div class="scr-table-wrap">
		<table class="scr-table">
			<thead>
				<tr>
					<th class="sth-check"></th>
					<th class="sth-expand"></th>
					<th class="sth-name">Firm / Fund</th>
					<th class="sth-aum">AUM</th>
					<th class="sth-loc">Location</th>
					<th class="sth-layers">L1</th>
					<th class="sth-layers">L2</th>
					<th class="sth-layers">L3</th>
					<th class="sth-score">Score</th>
					<th class="sth-status">Status</th>
					<th class="sth-univ">Universe</th>
				</tr>
			</thead>
			<tbody>
				{#each screener.managers as manager (manager.crd_number)}
					<!-- Level 1: Manager row -->
					<tr
						class="scr-mgr-row"
						class:scr-mgr-row--selected={selectedManagers.has(manager.crd_number)}
						class:scr-mgr-row--expanded={expandedManagers.has(manager.crd_number)}
						onclick={() => onOpenManagerDetail(manager)}
					>
						<td class="std-check" onclick={(e) => e.stopPropagation()}>
							<Checkbox
								checked={selectedManagers.has(manager.crd_number)}
								onCheckedChange={() => onToggleSelection(manager.crd_number)}
							/>
						</td>
						<td class="std-expand" onclick={(e) => { e.stopPropagation(); onToggleExpand(manager.crd_number); }}>
							<span class="expand-chevron" class:expand-chevron--open={expandedManagers.has(manager.crd_number)}>&#9654;</span>
						</td>
						<td class="std-name">
							<span class="mgr-name">{manager.firm_name}</span>
							<span class="mgr-crd">CRD {manager.crd_number}</span>
						</td>
						<td class="std-aum">{manager.aum_total ? formatAUM(manager.aum_total) : "—"}</td>
						<td class="std-loc">{manager.state ?? ""}{manager.state && manager.country ? ", " : ""}{manager.country ?? ""}</td>
						<td class="std-layer"></td>
						<td class="std-layer"></td>
						<td class="std-layer"></td>
						<td class="std-score"></td>
						<td class="std-status">
							{#if manager.compliance_disclosures !== null && manager.compliance_disclosures > 0}
								<span class="mgr-disclosures">{manager.compliance_disclosures} disc.</span>
							{/if}
						</td>
						<td class="std-univ">
							{#if manager.universe_status}
								<StatusBadge status={manager.universe_status} />
							{:else}
								<span class="mgr-not-added">—</span>
							{/if}
						</td>
					</tr>

					<!-- Level 2: Fund sub-rows -->
					{#if expandedManagers.has(manager.crd_number)}
						{#each fundSubRows(manager.crd_number) as fund, idx (fund.instrument_id)}
							<tr class="scr-fund-row" onclick={() => onOpenFundDetail(fund)}>
								<td></td>
								<td></td>
								<td class="std-name std-name--nested">
									<span class="nest-char">{isLastFund(manager.crd_number, idx) ? "└─" : "├─"}</span>
									<span class="fund-name">{instrumentLabel(fund)}</span>
								</td>
								<td class="std-aum">{fund.aum ? formatAUM(fund.aum) : "—"}</td>
								<td class="std-loc">
									<span class="fund-type-badge fund-type-badge--{fund.instrument_type ?? 'other'}">
										{typeLabel(fund.instrument_type)}
									</span>
								</td>
								<td class="std-layer">
									<span class="layer-dot layer-dot--{layerDotStatus(fund, 1)}"></span>
								</td>
								<td class="std-layer">
									<span class="layer-dot layer-dot--{layerDotStatus(fund, 2)}"></span>
								</td>
								<td class="std-layer">
									<span class="layer-dot layer-dot--{layerDotStatus(fund, 3)}"></span>
								</td>
								<td class="std-score">
									{#if fund.score !== null}
										<span style:color={scoreColor(fund.score)}>{formatPercent(fund.score)}</span>
									{:else}
										<span class="score-na">—</span>
									{/if}
								</td>
								<td class="std-status">
									<StatusBadge status={fund.overall_status} />
								</td>
								<td class="std-univ">
									{ddLabel(fund.required_analysis_type)}
								</td>
							</tr>
						{:else}
							<tr class="scr-fund-row scr-fund-row--empty">
								<td></td>
								<td></td>
								<td class="std-name std-name--nested" colspan="9">
									<span class="nest-char">└─</span>
									<span class="fund-empty-text">No screened funds for this manager</span>
								</td>
							</tr>
						{/each}
					{/if}
				{/each}
			</tbody>
		</table>
	</div>

	<!-- Pagination -->
	<div class="flex items-center justify-center gap-3 py-3">
		<Button variant="outline" size="sm" disabled={screener.page <= 1} onclick={() => goToPage(screener.page - 1)}>Previous</Button>
		<span class="text-xs text-muted-foreground tabular-nums">Page {screener.page} · {screener.total_count} total</span>
		<Button variant="outline" size="sm" disabled={!screener.has_next} onclick={() => goToPage(screener.page + 1)}>Next</Button>
	</div>
{/if}
