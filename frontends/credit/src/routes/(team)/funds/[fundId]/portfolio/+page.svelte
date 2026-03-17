<!--
  Portfolio — tabs: Assets, Obligations, Alerts, Actions.
-->
<script lang="ts">
	import { PageTabs, DataTable, StatusBadge, EmptyState, Button, Dialog, Card } from "@netz/ui";
	import type { PageData } from "./$types";
	import type { PaginatedResponse, PortfolioAsset, PortfolioObligation, PortfolioAlert, PortfolioAction } from "$lib/types/api";

	let { data }: { data: PageData } = $props();
	let activeTab = $state("assets");

	let assets = $derived((data.assets as PaginatedResponse<PortfolioAsset>)?.items ?? []);
	let obligations = $derived((data.obligations as PaginatedResponse<PortfolioObligation>)?.items ?? []);
	let alerts = $derived((data.alerts as PaginatedResponse<PortfolioAlert>)?.items ?? []);
	let actions = $derived((data.actions as PaginatedResponse<PortfolioAction>)?.items ?? []);

	const assetColumns = [
		{ accessorKey: "name", header: "Name" },
		{ accessorKey: "asset_type", header: "Type" },
		{ accessorKey: "strategy", header: "Strategy" },
		{ accessorKey: "status", header: "Status" },
	];

	const obligationColumns = [
		{ accessorKey: "type", header: "Type" },
		{ accessorKey: "due_date", header: "Due Date" },
		{ accessorKey: "status", header: "Status" },
		{ accessorKey: "asset_name", header: "Asset" },
	];

	const alertColumns = [
		{ accessorKey: "severity", header: "Severity" },
		{ accessorKey: "message", header: "Message" },
		{ accessorKey: "asset_name", header: "Asset" },
		{ accessorKey: "created_at", header: "Date" },
	];

	const actionColumns = [
		{ accessorKey: "title", header: "Action" },
		{ accessorKey: "status", header: "Status" },
		{ accessorKey: "due_date", header: "Due" },
		{ accessorKey: "evidence_notes", header: "Notes" },
	];
</script>

<div class="p-6">
	<div class="mb-4 flex items-center justify-between">
		<h2 class="text-xl font-semibold text-[var(--netz-text-primary)]">Portfolio</h2>
	</div>

	<PageTabs
		tabs={[
			{ id: "assets", label: "Assets" },
			{ id: "obligations", label: "Obligations" },
			{ id: "alerts", label: "Alerts" },
			{ id: "actions", label: "Actions" },
		]}
		active={activeTab}
		onChange={(tab) => activeTab = tab}
	/>

	<div class="mt-4">
		{#if activeTab === "assets"}
			{#if assets.length === 0}
				<EmptyState title="No Assets" description="Portfolio assets will appear here after deal conversion." />
			{:else}
				<DataTable data={assets} columns={assetColumns} />
			{/if}

		{:else if activeTab === "obligations"}
			{#if obligations.length === 0}
				<EmptyState title="No Obligations" description="Obligation tracking for portfolio assets." />
			{:else}
				<DataTable data={obligations} columns={obligationColumns} />
			{/if}

		{:else if activeTab === "alerts"}
			{#if alerts.length === 0}
				<EmptyState title="No Alerts" description="Portfolio alerts will appear here." />
			{:else}
				<DataTable data={alerts} columns={alertColumns} />
			{/if}

		{:else if activeTab === "actions"}
			{#if actions.length === 0}
				<EmptyState title="No Actions" description="Action items will appear here." />
			{:else}
				<DataTable data={actions} columns={actionColumns} />
			{/if}
		{/if}
	</div>
</div>
