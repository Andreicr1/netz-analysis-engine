<!--
  OverlapScannerPanel — Detects hidden concentration risk: equity overlaps + cross-fund holdings (ETF/fund-of-fund).
  Live API data integrated.
  Design: dark premium (Figma One X).
-->
<script lang="ts">
	import { AlertBanner, EmptyState, formatPercent } from "@investintell/ui";
	import { workspace } from "$wealth/state/portfolio-workspace.svelte";
	import type { CusipExposure } from "$wealth/types/model-portfolio";

	let isLoading = $derived(workspace.isLoadingOverlap);
	let data = $derived(workspace.localOverlap);

	let fundCount = $derived(workspace.funds.length);
	
	let overlaps = $derived(data?.top_cusip_exposures || []);
	let totalConcentration = $derived(
		overlaps.reduce((sum: number, o: CusipExposure) => sum + o.total_exposure_pct, 0)
	);
	
	let crossHoldingCount = $derived(
		data?.sector_exposures?.length || 0 // Assuming cross block proxies or just distinct sectors
	);
</script>

{#if !workspace.portfolio}
	<div class="p-6">
		<EmptyState
			title="No portfolio selected"
			message="Select a model portfolio to scan for overlapping holdings."
		/>
	</div>
{:else if fundCount < 2}
	<div class="p-6">
		<EmptyState
			title="Not enough funds to scan"
			message="Add at least two funds to the portfolio to detect overlapping holdings."
		/>
	</div>
{:else if isLoading}
	<div class="p-6 flex items-center justify-center h-full">
		<div class="text-[#85a0bd] text-[14px]">Loading overlap analysis...</div>
	</div>
{:else if !data || !data.has_sufficient_data}
	<div class="p-6">
		<EmptyState
			title="Insufficient Holdings Data"
			message={data?.data_warning || "Not enough constituent holdings data to perform overlap analysis on these funds."}
		/>
	</div>
{:else}
	<div class="flex flex-col gap-4 p-5 h-full">
		<!-- Header -->
		<div class="flex items-center gap-2">
			<span class="text-[15px] font-bold text-white">Overlap Scanner</span>
			<span class="text-[12px] text-[#85a0bd] ml-auto">
				{data.total_holdings} distinct holdings &middot; {formatPercent(data.limit_pct)} limit
			</span>
		</div>

		<AlertBanner variant={data.breaches.length > 0 ? "error" : "warning"}>
			<span class="text-[13px] leading-relaxed">
				<strong>Concentration Alert:</strong> Detected {overlaps.length} concentrated exposures 
				and {data.breaches.length} limit breaches across {data.funds_analyzed} funds.
			</span>
		</AlertBanner>

		<!-- Table -->
		<div class="flex-1 overflow-y-auto min-h-0">
			<table class="w-full border-collapse">
				<thead class="sticky top-0 z-[1] bg-[#141519]">
					<tr>
						<th class="text-left px-4 py-2.5 text-[11px] font-semibold text-[#85a0bd] uppercase tracking-[0.04em]" style="border-bottom: 1px solid #404249;">Underlying Asset</th>
						<th class="text-right px-4 py-2.5 text-[11px] font-semibold text-[#85a0bd] uppercase tracking-[0.04em] w-[160px]" style="border-bottom: 1px solid #404249;">Consolidated Weight</th>
						<th class="text-left px-4 py-2.5 text-[11px] font-semibold text-[#85a0bd] uppercase tracking-[0.04em] w-[280px]" style="border-bottom: 1px solid #404249;">Source Funds</th>
					</tr>
				</thead>
				<tbody>
					{#each overlaps as row (row.cusip)}
						<tr class="hover:bg-white/[0.02] transition-colors" style="border-bottom: 1px solid rgba(64, 66, 73, 0.4);">
							<td class="px-4 py-3 align-middle">
								<div class="flex items-center gap-3">
									<div class="flex flex-col gap-0.5 min-w-0">
										<span class="text-[13px] font-semibold text-white truncate">{row.issuer_name || "Unknown Issuer"}</span>
										<span class="text-[11px] text-[#85a0bd] tabular-nums">{row.cusip}</span>
									</div>
									{#if row.is_breach}
										<span class="text-[10px] text-[#f85149] border border-[#f85149]/20 bg-[#f85149]/10 px-2 py-0.5 rounded-full shrink-0">Breach</span>
									{/if}
								</div>
							</td>
							<td class="px-4 py-3 text-right align-middle">
								<span class="text-[13px] font-bold tabular-nums {row.is_breach ? 'text-[#f85149]' : 'text-[#d29922]'}">{formatPercent(row.total_exposure_pct / 100)}</span>
							</td>
							<td class="px-4 py-3 align-middle">
								<div class="flex flex-wrap gap-1.5">
									{#each row.funds_holding as fundId}
										{@const fundObj = workspace.funds.find(f => f.instrument_id === fundId)}
										<span class="text-[10px] text-[#cbccd1] border border-white/10 px-2 py-0.5 rounded-full truncate max-w-[120px]">
											{fundObj ? fundObj.fund_name : fundId}
										</span>
									{/each}
								</div>
							</td>
						</tr>
					{/each}
					{#if overlaps.length === 0}
						<tr>
							<td colspan="3" class="px-4 py-8 text-center text-[#85a0bd] text-[13px]">
								No significant overlaps detected.
							</td>
						</tr>
					{/if}
				</tbody>
			</table>
		</div>
	</div>
{/if}
