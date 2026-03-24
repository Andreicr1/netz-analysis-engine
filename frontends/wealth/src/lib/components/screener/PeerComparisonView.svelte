<!--
  Peer comparison view — manager cards + sector allocation grid.
-->
<script lang="ts">
	import "./screener.css";
	import { Button, formatAUM } from "@netz/ui";
	import type { CompareResult } from "$lib/types/manager-screener";

	interface Props {
		compareResult: CompareResult;
		onClear: () => void;
	}

	let { compareResult, onClear }: Props = $props();

	let compareSectors = $derived.by(() => {
		if (!compareResult?.sector_allocations) return [];
		const all = new Set<string>();
		for (const alloc of Object.values(compareResult.sector_allocations)) {
			for (const s of Object.keys(alloc)) all.add(s);
		}
		return [...all].sort();
	});
</script>

<div class="cmp-view">
	<div class="cmp-header">
		<h3 class="cmp-title">Peer Comparison</h3>
		<span class="cmp-overlap">
			Portfolio Overlap (Jaccard): <strong>{(compareResult.jaccard_overlap * 100).toFixed(1)}%</strong>
		</span>
		<Button size="sm" variant="ghost" onclick={onClear}>Back to list</Button>
	</div>

	<div class="cmp-cards">
		{#each compareResult.managers as mgr (mgr.crd_number)}
			<div class="cmp-card">
				<span class="cmp-card-name">{mgr.firm_name}</span>
				<span class="cmp-card-aum">{mgr.aum_total ? formatAUM(mgr.aum_total) : "—"}</span>
				<span class="cmp-card-crd">CRD {mgr.crd_number}</span>
			</div>
		{/each}
	</div>

	{#if compareSectors.length > 0}
		<div class="cmp-sectors">
			<h4 class="cmp-subtitle">Sector Allocation</h4>
			<div class="cmp-sg">
				<div class="cmp-sg-header">
					<span class="cmp-sg-label">Sector</span>
					{#each compareResult.managers as mgr (mgr.crd_number)}
						<span class="cmp-sg-mgr">{mgr.firm_name.slice(0, 12)}</span>
					{/each}
				</div>
				{#each compareSectors as sector (sector)}
					<div class="cmp-sg-row">
						<span class="cmp-sg-label">{sector}</span>
						{#each compareResult.managers as mgr (mgr.crd_number)}
							{@const alloc = compareResult.sector_allocations[mgr.crd_number] ?? {}}
							{@const pct = alloc[sector] ?? 0}
							<div class="cmp-sg-cell">
								<div class="cmp-sg-bar-track">
									<div class="cmp-sg-bar-fill" style:width="{pct * 100}%"></div>
								</div>
								<span class="cmp-sg-pct">{(pct * 100).toFixed(1)}%</span>
							</div>
						{/each}
					</div>
				{/each}
			</div>
		</div>
	{/if}
</div>
