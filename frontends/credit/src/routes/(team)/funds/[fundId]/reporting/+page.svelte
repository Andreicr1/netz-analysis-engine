<!--
  Reporting overview — tabs: NAV, Report Packs, Evidence Packs.
-->
<script lang="ts">
	import { PageTabs, DataTable, EmptyState, Button, PDFDownload } from "@netz/ui";
	import type { PageData } from "./$types";
	import type { PaginatedResponse, NavSnapshot, ReportPack } from "$lib/types/api";
	import { createClientApiClient } from "$lib/api/client";
	import { invalidateAll } from "$app/navigation";
	import { getContext } from "svelte";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let { data }: { data: PageData } = $props();
	let activeTab = $state("nav");
	let loading = $state(false);

	let navSnapshots = $derived((data.navSnapshots as PaginatedResponse<NavSnapshot>)?.items ?? []);
	let reportPacks = $derived((data.reportPacks as PaginatedResponse<ReportPack>)?.items ?? []);

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

	async function createNavSnapshot() {
		loading = true;
		try {
			const api = createClientApiClient(getToken);
			await api.post(`/funds/${data.fundId}/reports/nav/snapshots`, {
				period_month: new Date().toISOString().slice(0, 7),
				nav_total_usd: 0,
				cash_balance_usd: 0,
				assets_value_usd: 0,
				liabilities_usd: 0,
			});
			await invalidateAll();
		} finally {
			loading = false;
		}
	}

	async function generateReportPack() {
		loading = true;
		try {
			const api = createClientApiClient(getToken);
			const now = new Date();
			const start = new Date(now.getFullYear(), now.getMonth(), 1).toISOString().split("T")[0];
			const end = new Date(now.getFullYear(), now.getMonth() + 1, 0).toISOString().split("T")[0];
			await api.post(`/funds/${data.fundId}/report-packs`, {
				period_start: start,
				period_end: end,
			});
			await invalidateAll();
		} finally {
			loading = false;
		}
	}

	async function exportEvidenceJSON() {
		loading = true;
		try {
			const api = createClientApiClient(getToken);
			const result = await api.post<Record<string, unknown>>(`/funds/${data.fundId}/reports/evidence-pack`, { limit: 50 });
			const blob = new Blob([JSON.stringify(result, null, 2)], { type: "application/json" });
			const url = URL.createObjectURL(blob);
			const a = document.createElement("a");
			a.href = url;
			a.download = `evidence-pack-${data.fundId}.json`;
			a.click();
			URL.revokeObjectURL(url);
		} finally {
			loading = false;
		}
	}

	async function exportEvidencePDF() {
		loading = true;
		try {
			const api = createClientApiClient(getToken);
			const response = await api.post<Blob>(`/funds/${data.fundId}/reports/evidence-pack/pdf`, {});
			const url = URL.createObjectURL(response);
			const a = document.createElement("a");
			a.href = url;
			a.download = `evidence-pack-${data.fundId}.pdf`;
			a.click();
			URL.revokeObjectURL(url);
		} finally {
			loading = false;
		}
	}
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
				<Button onclick={createNavSnapshot} disabled={loading}>
					{loading ? "Creating..." : "Create NAV Snapshot"}
				</Button>
			</div>
			{#if navSnapshots.length === 0}
				<EmptyState title="No NAV Snapshots" description="Create a NAV snapshot to track fund valuation." />
			{:else}
				<DataTable data={navSnapshots} columns={navColumns} />
			{/if}

		{:else if activeTab === "report-packs"}
			<div class="mb-4">
				<Button onclick={generateReportPack} disabled={loading}>
					{loading ? "Generating..." : "Generate Report Pack"}
				</Button>
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
				<Button onclick={exportEvidenceJSON} disabled={loading}>
					{loading ? "Exporting..." : "Export JSON"}
				</Button>
				<Button variant="outline" onclick={exportEvidencePDF} disabled={loading}>
					{loading ? "Exporting..." : "Export PDF"}
				</Button>
			</div>
		{/if}
	</div>
</div>
