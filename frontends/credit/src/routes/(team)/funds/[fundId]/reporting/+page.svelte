<!--
  Reporting overview — tabs: NAV, Report Packs, Evidence Packs.
  Actions: Create NAV, Generate/Publish report packs, Export evidence.
-->
<script lang="ts">
	import { PageTabs, DataTable, EmptyState, Button, Card, StatusBadge, PageHeader } from "@netz/ui";
	import { ActionButton, ConfirmDialog } from "@netz/ui";
	import type { PageData } from "./$types";
	import type { PaginatedResponse, NavSnapshot, ReportPack } from "$lib/types/api";
	import { createClientApiClient } from "$lib/api/client";
	import { invalidateAll } from "$app/navigation";
	import { getContext } from "svelte";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let { data }: { data: PageData } = $props();
	let activeTab = $state("nav");
	let loading = $state(false);
	let actionError = $state<string | null>(null);

	let navSnapshots = $derived((data.navSnapshots as PaginatedResponse<NavSnapshot>)?.items ?? []);
	let reportPacks = $derived((data.reportPacks as PaginatedResponse<ReportPack>)?.items ?? []);

	// ── Report Pack Actions ──
	let generatingPackId = $state<string | null>(null);
	let publishingPackId = $state<string | null>(null);
	let showPublishConfirm = $state(false);
	let packToPublish = $state<string | null>(null);

	async function generatePack(packId: string) {
		generatingPackId = packId;
		actionError = null;
		try {
			const api = createClientApiClient(getToken);
			await api.post(`/funds/${data.fundId}/report-packs/${packId}/generate`, {});
			await invalidateAll();
		} catch (e) {
			actionError = e instanceof Error ? e.message : "Generation failed";
		} finally {
			generatingPackId = null;
		}
	}

	function confirmPublish(packId: string) {
		packToPublish = packId;
		showPublishConfirm = true;
	}

	async function publishPack() {
		if (!packToPublish) return;
		publishingPackId = packToPublish;
		actionError = null;
		showPublishConfirm = false;
		try {
			const api = createClientApiClient(getToken);
			await api.post(`/funds/${data.fundId}/report-packs/${packToPublish}/publish`, {});
			await invalidateAll();
		} catch (e) {
			actionError = e instanceof Error ? e.message : "Publish failed";
		} finally {
			publishingPackId = null;
			packToPublish = null;
		}
	}

	function humanizeEnum(value: string): string {
		return value.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
	}

	const navColumns = [
		{ accessorKey: "reference_date", header: "Date" },
		{ accessorKey: "status", header: "Status", cell: (info: { getValue: () => unknown }) => humanizeEnum(String(info.getValue() ?? "")) },
		{ accessorKey: "total_nav", header: "Total NAV" },
		{ accessorKey: "created_at", header: "Created" },
	];

	async function createNavSnapshot() {
		loading = true;
		actionError = null;
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
		} catch (e) {
			actionError = e instanceof Error ? e.message : "Failed to create NAV snapshot";
		} finally {
			loading = false;
		}
	}

	async function generateReportPack() {
		loading = true;
		actionError = null;
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
		} catch (e) {
			actionError = e instanceof Error ? e.message : "Failed to create report pack";
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
			const response = await api.getBlob(`/funds/${data.fundId}/reports/evidence-pack/pdf`);
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

<div class="px-6">
	<PageHeader
		title="Reporting"
		breadcrumbs={[{ label: "Funds", href: "/funds" }, { label: "Reporting" }]}
	/>

	{#if actionError}
		<div class="mb-4 rounded-md border border-(--netz-status-error) bg-(--netz-status-error)/10 p-3 text-sm text-(--netz-status-error)">
			{actionError}
			<button class="ml-2 underline" onclick={() => actionError = null}>dismiss</button>
		</div>
	{/if}

	<PageTabs
		tabs={[
			{ id: "nav", label: "NAV" },
			{ id: "report-packs", label: `Report Packs (${reportPacks.length})` },
			{ id: "evidence", label: "Evidence Packs" },
		]}
		active={activeTab}
		onChange={(tab) => activeTab = tab}
	/>

	<div class="mt-4">
		{#if activeTab === "nav"}
			<div class="mb-4">
				<ActionButton onclick={createNavSnapshot} loading={loading} loadingText="Creating...">
					Create NAV Snapshot
				</ActionButton>
			</div>
			{#if navSnapshots.length === 0}
				<EmptyState title="No NAV Snapshots" description="Create a NAV snapshot to track fund valuation." />
			{:else}
				<DataTable data={navSnapshots} columns={navColumns} />
			{/if}

		{:else if activeTab === "report-packs"}
			<div class="mb-4">
				<ActionButton onclick={generateReportPack} loading={loading} loadingText="Creating...">
					Create Report Pack
				</ActionButton>
			</div>
			{#if reportPacks.length === 0}
				<EmptyState title="No Report Packs" description="Monthly report packs will appear here." />
			{:else}
				<div class="space-y-3">
					{#each reportPacks as pack (pack.id)}
						<Card class="flex items-center justify-between p-4">
							<div>
								<p class="text-sm font-medium text-(--netz-text-primary)">
									{pack.period_start ?? pack.period} — {pack.period_end ?? ""}
								</p>
								<div class="mt-1 flex items-center gap-2">
									<StatusBadge status={pack.status} type="default" />
									<span class="text-xs text-(--netz-text-muted)">{pack.created_at}</span>
								</div>
							</div>
							<div class="flex gap-2">
								{#if pack.status === "DRAFT"}
									<ActionButton
										size="sm"
										onclick={() => generatePack(pack.id)}
										loading={generatingPackId === pack.id}
										loadingText="Generating..."
									>
										Generate
									</ActionButton>
								{:else if pack.status === "GENERATED"}
									<ActionButton
										size="sm"
										onclick={() => confirmPublish(pack.id)}
										loading={publishingPackId === pack.id}
										loadingText="Publishing..."
									>
										Publish
									</ActionButton>
								{:else if pack.status === "PUBLISHED"}
									<span class="text-xs text-(--netz-text-muted)">
										Published {pack.published_at ?? ""}
									</span>
								{/if}
							</div>
						</Card>
					{/each}
				</div>
			{/if}

		{:else if activeTab === "evidence"}
			<EmptyState
				title="Evidence Packs"
				description="Export Q&A evidence packs with citations from the Fund Copilot."
			/>
			<div class="mt-4 flex gap-2">
				<ActionButton onclick={exportEvidenceJSON} loading={loading} loadingText="Exporting...">
					Export JSON
				</ActionButton>
				<ActionButton variant="outline" onclick={exportEvidencePDF} loading={loading} loadingText="Exporting...">
					Export PDF
				</ActionButton>
			</div>
		{/if}
	</div>
</div>

<!-- Publish Confirmation -->
<ConfirmDialog
	bind:open={showPublishConfirm}
	title="Publish Report Pack"
	message="Publishing is permanent. This will make the report available to investors and create an evidence record. Continue?"
	confirmLabel="Publish"
	confirmVariant="default"
	onConfirm={publishPack}
	onCancel={() => { showPublishConfirm = false; packToPublish = null; }}
/>
