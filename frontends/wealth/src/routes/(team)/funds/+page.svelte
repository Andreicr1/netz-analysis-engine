<!--
  Fund Universe — DataTable with filters for block, geography, asset class.
-->
<script lang="ts">
	import { DataTable, PageHeader, EmptyState, Select, Badge } from "@netz/ui";
	import type { PageData } from "./$types";
	import { goto } from "$app/navigation";
	import { page } from "$app/stores";

	let { data }: { data: PageData } = $props();

	type Fund = {
		id: string;
		name: string;
		ticker: string | null;
		block: string | null;
		geography: string | null;
		asset_class: string | null;
		manager_score: number | null;
		return_consistency: number | null;
		drawdown_control: number | null;
	};

	let funds = $derived((data.funds ?? []) as Fund[]);

	// Filter state
	let blockFilter = $state(data.filters.block ?? "");
	let geoFilter = $state(data.filters.geography ?? "");
	let assetFilter = $state(data.filters.asset_class ?? "");

	// Extract unique filter values from funds
	let blocks = $derived([...new Set(funds.map((f) => f.block).filter(Boolean))] as string[]);
	let geographies = $derived([...new Set(funds.map((f) => f.geography).filter(Boolean))] as string[]);
	let assetClasses = $derived([...new Set(funds.map((f) => f.asset_class).filter(Boolean))] as string[]);

	// Client-side filtering (server already filtered, but supports additional client filtering)
	let filteredFunds = $derived(
		funds.filter((f) => {
			if (blockFilter && f.block !== blockFilter) return false;
			if (geoFilter && f.geography !== geoFilter) return false;
			if (assetFilter && f.asset_class !== assetFilter) return false;
			return true;
		}),
	);

	// Table columns
	const columns = [
		{ accessorKey: "name", header: "Fund Name" },
		{ accessorKey: "ticker", header: "Ticker" },
		{ accessorKey: "block", header: "Block" },
		{ accessorKey: "geography", header: "Geography" },
		{ accessorKey: "asset_class", header: "Asset Class" },
		{
			accessorKey: "manager_score",
			header: "Manager Score",
			cell: (info: { getValue: () => unknown }) => {
				const v = info.getValue() as number | null;
				return v !== null ? v.toFixed(1) : "—";
			},
		},
	];

	function handleRowClick(fund: Fund) {
		goto(`/funds/${fund.id}`);
	}

	function clearFilters() {
		blockFilter = "";
		geoFilter = "";
		assetFilter = "";
	}
</script>

<div class="space-y-6 p-6">
	<PageHeader title="Fund Universe">
		{#snippet actions()}
			<span class="text-sm text-[var(--netz-text-muted)]">
				{filteredFunds.length} funds
			</span>
		{/snippet}
	</PageHeader>

	<!-- Filters -->
	<div class="flex flex-wrap items-center gap-3">
		<select
			class="rounded-md border border-[var(--netz-border)] bg-[var(--netz-surface-elevated)] px-3 py-1.5 text-sm text-[var(--netz-text-primary)]"
			bind:value={blockFilter}
		>
			<option value="">All Blocks</option>
			{#each blocks as b (b)}
				<option value={b}>{b}</option>
			{/each}
		</select>
		<select
			class="rounded-md border border-[var(--netz-border)] bg-[var(--netz-surface-elevated)] px-3 py-1.5 text-sm text-[var(--netz-text-primary)]"
			bind:value={geoFilter}
		>
			<option value="">All Geographies</option>
			{#each geographies as g (g)}
				<option value={g}>{g}</option>
			{/each}
		</select>
		<select
			class="rounded-md border border-[var(--netz-border)] bg-[var(--netz-surface-elevated)] px-3 py-1.5 text-sm text-[var(--netz-text-primary)]"
			bind:value={assetFilter}
		>
			<option value="">All Asset Classes</option>
			{#each assetClasses as a (a)}
				<option value={a}>{a}</option>
			{/each}
		</select>
		{#if blockFilter || geoFilter || assetFilter}
			<button
				class="text-xs text-[var(--netz-primary)] hover:underline"
				onclick={clearFilters}
			>
				Clear filters
			</button>
		{/if}
	</div>

	<!-- Fund Table -->
	{#if filteredFunds.length > 0}
		<DataTable
			data={filteredFunds}
			{columns}
		/>
	{:else}
		<EmptyState
			title="No Funds Found"
			message="No funds match the current filters. Try adjusting your criteria."
		/>
	{/if}
</div>
