<!--
  DD Reports for a fund — version history + trigger generation.
-->
<script lang="ts">
	import { DataTable, StatusBadge, PageHeader, EmptyState, Button } from "@netz/ui";
	import type { PageData } from "./$types";
	import { createClientApiClient } from "$lib/api/client";
	import { invalidateAll, goto } from "$app/navigation";

	let { data }: { data: PageData } = $props();

	type FundDetail = { id: string; name: string };
	type DDReportSummary = {
		report_id: string;
		status: string;
		version: number;
		created_at: string;
	};

	let fund = $derived(data.fund as FundDetail | null);
	let reports = $derived((data.reports ?? []) as DDReportSummary[]);
	let generating = $state(false);

	const columns = [
		{
			accessorKey: "version",
			header: "Version",
			cell: (info: { getValue: () => unknown }) => `v${info.getValue()}`,
		},
		{ accessorKey: "status", header: "Status" },
		{
			accessorKey: "created_at",
			header: "Generated",
			cell: (info: { getValue: () => unknown }) =>
				new Date(info.getValue() as string).toLocaleDateString(),
		},
	];

	async function triggerGeneration() {
		generating = true;
		try {
			const api = createClientApiClient(async () => "dev-token");
			await api.post(`/dd-reports/funds/${data.fundId}`, {});
			await invalidateAll();
		} catch {
			// Handled by api-client
		} finally {
			generating = false;
		}
	}

	function viewReport(report: DDReportSummary) {
		goto(`/dd-reports/${data.fundId}/${report.report_id}`);
	}
</script>

<div class="space-y-6 p-6">
	<PageHeader title={fund ? `DD Reports — ${fund.name}` : "DD Reports"}>
		{#snippet actions()}
			<Button onclick={triggerGeneration} disabled={generating}>
				{generating ? "Generating..." : "Generate New Report"}
			</Button>
		{/snippet}
	</PageHeader>

	{#if reports.length > 0}
		<DataTable data={reports} {columns} />
	{:else}
		<EmptyState
			title="No DD Reports"
			message="Generate a due diligence report for this fund."
		/>
	{/if}
</div>
