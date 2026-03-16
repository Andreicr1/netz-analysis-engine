<!--
  Pipeline list — DataTable with deal columns, click row for ContextPanel.
-->
<script lang="ts">
	import { DataTable, DataTableToolbar, StatusBadge, ContextPanel, EmptyState, Button } from "@netz/ui";
	import type { PageData } from "./$types";

	let { data }: { data: PageData } = $props();

	let selectedDeal = $state<Record<string, unknown> | null>(null);
	let panelOpen = $derived(selectedDeal !== null);

	const columns = [
		{ accessorKey: "name", header: "Deal Name" },
		{ accessorKey: "stage", header: "Stage", cell: (info: { getValue: () => string }) => info.getValue() },
		{ accessorKey: "strategy_type", header: "Strategy" },
		{ accessorKey: "qualification_status", header: "Qualification" },
		{ accessorKey: "created_at", header: "Created" },
	];

	function handleRowClick(row: Record<string, unknown>) {
		selectedDeal = row;
	}
</script>

<div class="flex h-full">
	<div class="flex-1 p-6">
		<div class="mb-4 flex items-center justify-between">
			<h2 class="text-xl font-semibold text-[var(--netz-text-primary)]">Deal Pipeline</h2>
			<Button href="/funds/{data.fundId}/pipeline/new">New Deal</Button>
		</div>

		{#if data.deals.items.length === 0}
			<EmptyState
				title="No Deals"
				description="Create your first deal to get started with the pipeline."
			/>
		{:else}
			<DataTable
				data={data.deals.items}
				{columns}
				onRowClick={handleRowClick}
			/>
		{/if}
	</div>

	<!-- Context panel for quick deal summary -->
	{#if selectedDeal}
		<ContextPanel
			open={panelOpen}
			title={String(selectedDeal.name ?? "Deal")}
			onClose={() => selectedDeal = null}
		>
			<div class="space-y-4 p-4">
				<div>
					<p class="text-xs text-[var(--netz-text-muted)]">Stage</p>
					<StatusBadge status={String(selectedDeal.stage)} type="deal" />
				</div>
				<div>
					<p class="text-xs text-[var(--netz-text-muted)]">Strategy</p>
					<p class="text-sm">{selectedDeal.strategy_type ?? "—"}</p>
				</div>
				<div>
					<p class="text-xs text-[var(--netz-text-muted)]">Qualification</p>
					<p class="text-sm">{selectedDeal.qualification_status ?? "—"}</p>
				</div>
				<div class="flex gap-2 pt-2">
					<Button href="/funds/{data.fundId}/pipeline/{selectedDeal.id}" class="flex-1">
						Open Deal
					</Button>
				</div>
			</div>
		</ContextPanel>
	{/if}
</div>
