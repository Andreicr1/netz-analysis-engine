<!--
  Reporting overview — tabs: NAV, Report Packs, Evidence Packs.
-->
<script lang="ts">
	import { PageTabs, DataTable, EmptyState, Button, PDFDownload } from "@netz/ui";
	import type { PageData } from "./$types";

	let { data }: { data: PageData } = $props();
	let activeTab = $state("nav");

	let navSnapshots = $derived((data.navSnapshots as Record<string, unknown>)?.items as unknown[] ?? []);
	let reportPacks = $derived((data.reportPacks as Record<string, unknown>)?.items as unknown[] ?? []);

	const navColumns = [
		{ accessorKey: "reference_date", header: "Date" },
		{ accessorKey: "status", header: "Status" },
		{ accessorKey: "total_nav", header: "Total NAV" },
		{ accessorKey: "created_at", header: "Created" },
	];

	const packColumns = [
		{ accessorKey: "period", header: "Period" },
		{ accessorKey: "status", header: "Status" },
		{ accessorKey: "created_at", header: "Generated" },
	];
</script>

<div class="p-6">
	<h2 class="mb-4 text-xl font-semibold text-[var(--netz-text-primary)]">Reporting</h2>

	<PageTabs
		tabs={[
			{ id: "nav", label: "NAV" },
			{ id: "report-packs", label: "Report Packs" },
			{ id: "evidence", label: "Evidence Packs" },
		]}
		active={activeTab}
		onChange={(tab) => activeTab = tab}
	/>

	<div class="mt-4">
		{#if activeTab === "nav"}
			<div class="mb-4">
				<Button onclick={() => {}}>Create NAV Snapshot</Button>
			</div>
			{#if navSnapshots.length === 0}
				<EmptyState title="No NAV Snapshots" description="Create a NAV snapshot to track fund valuation." />
			{:else}
				<DataTable data={navSnapshots} columns={navColumns} />
			{/if}

		{:else if activeTab === "report-packs"}
			<div class="mb-4">
				<Button onclick={() => {}}>Generate Report Pack</Button>
			</div>
			{#if reportPacks.length === 0}
				<EmptyState title="No Report Packs" description="Monthly report packs will appear here." />
			{:else}
				<DataTable data={reportPacks} columns={packColumns} />
			{/if}

		{:else if activeTab === "evidence"}
			<EmptyState
				title="Evidence Packs"
				description="Export Q&A evidence packs with citations from the Fund Copilot."
			/>
			<div class="mt-4 flex gap-2">
				<Button onclick={() => {}}>Export JSON</Button>
				<Button variant="outline" onclick={() => {}}>Export PDF</Button>
			</div>
		{/if}
	</div>
</div>
