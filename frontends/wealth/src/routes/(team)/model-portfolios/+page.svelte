<!--
  Model Portfolios — list view with status and key metrics.
-->
<script lang="ts">
	import { DataTable, PageHeader, EmptyState, StatusBadge } from "@netz/ui";
	import type { PageData } from "./$types";
	import { goto } from "$app/navigation";

	let { data }: { data: PageData } = $props();

	type ModelPortfolio = {
		id: string;
		profile: string;
		display_name: string;
		description: string | null;
		benchmark_composite: string | null;
		inception_date: string | null;
		inception_nav: number;
		status: string;
		created_at: string;
	};

	let portfolios = $derived((data.modelPortfolios ?? []) as ModelPortfolio[]);

	const columns = [
		{ accessorKey: "display_name", header: "Name" },
		{ accessorKey: "profile", header: "Profile" },
		{ accessorKey: "benchmark_composite", header: "Benchmark" },
		{ accessorKey: "inception_date", header: "Inception" },
		{
			accessorKey: "inception_nav",
			header: "Inception NAV",
			cell: (info: { getValue: () => unknown }) => {
				const v = info.getValue() as number;
				return v.toFixed(2);
			},
		},
		{ accessorKey: "status", header: "Status" },
	];

	function handleRowClick(portfolio: ModelPortfolio) {
		goto(`/model-portfolios/${portfolio.id}`);
	}
</script>

<div class="space-y-6 p-6">
	<PageHeader title="Model Portfolios" />

	{#if portfolios.length > 0}
		<DataTable
			data={portfolios}
			{columns}
		/>
	{:else}
		<EmptyState
			title="No Model Portfolios"
			message="Create a model portfolio to get started."
		/>
	{/if}
</div>
