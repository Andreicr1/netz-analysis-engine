<!--
  Wealth Document List — paginated table with domain filtering and ingestion control.
-->
<script lang="ts">
	import { DataTable, PageHeader, EmptyState, Button, Select } from "@netz/ui";
	import { ActionButton } from "@netz/ui";
	import IngestionProgress from "$lib/components/IngestionProgress.svelte";
	import { createClientApiClient } from "$lib/api/client";
	import { invalidateAll, goto } from "$app/navigation";
	import { getContext } from "svelte";
	import { formatDateTime } from "@netz/ui";
	import type { PageData } from "./$types";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let { data }: { data: PageData } = $props();

	type WealthDocument = {
		id: string;
		title: string;
		filename: string;
		content_type: string | null;
		domain: string | null;
		current_version: number;
		created_at: string | null;
	};

	type DocumentPage = {
		items: WealthDocument[];
		limit: number;
		offset: number;
	};

	let docPage = $derived((data.documents ?? { items: [], limit: 100, offset: 0 }) as DocumentPage);
	let documents = $derived(docPage.items);

	// ── Domain filter ──
	let domainFilter = $state("");
	let filtered = $derived(
		domainFilter
			? documents.filter(d => d.domain === domainFilter)
			: documents
	);

	// ── Ingestion control ──
	let processing = $state(false);
	let ingestionJobId = $state<string | null>(null);
	let actionError = $state<string | null>(null);

	async function processPending() {
		processing = true;
		actionError = null;
		try {
			const api = createClientApiClient(getToken);
			const res = await api.post<{ processed: number; indexed: number; failed: number; skipped: number }>(
				"/wealth/documents/ingestion/process-pending",
				{ limit: 10 },
			);
			// No SSE job_id from this endpoint — just show result summary
			actionError = null;
			await invalidateAll();
		} catch (e) {
			actionError = e instanceof Error ? e.message : "Failed to process pending documents";
		} finally {
			processing = false;
		}
	}

	const columns = [
		{ accessorKey: "title", header: "Title" },
		{ accessorKey: "filename", header: "Filename" },
		{ accessorKey: "domain", header: "Domain" },
		{ accessorKey: "current_version", header: "Version" },
		{
			accessorKey: "created_at",
			header: "Uploaded",
			cell: (info: { getValue: () => unknown }) => {
				const v = info.getValue();
				return typeof v === "string" ? formatDateTime(v) : "—";
			},
		},
	];
</script>

<div class="space-y-(--netz-space-section-gap) p-(--netz-space-page-gutter)">
	<PageHeader title="Documents ({documents.length})">
		{#snippet actions()}
			<div class="flex gap-2">
				<ActionButton
					size="sm"
					variant="outline"
					onclick={processPending}
					loading={processing}
					loadingText="Processing..."
				>
					Process Pending
				</ActionButton>
				<Button size="sm" href="/documents/upload">Upload</Button>
			</div>
		{/snippet}
	</PageHeader>

	{#if actionError}
		<div class="rounded-md border border-(--netz-status-error) bg-(--netz-status-error)/10 p-3 text-sm text-(--netz-status-error)">
			{actionError}
			<button class="ml-2 underline" onclick={() => actionError = null}>dismiss</button>
		</div>
	{/if}

	{#if ingestionJobId}
		<IngestionProgress jobId={ingestionJobId} />
	{/if}

	<!-- Domain filter -->
	<div class="max-w-xs">
		<Select
			bind:value={domainFilter}
			options={[
				{ value: "", label: "All Domains" },
				{ value: "dd_report", label: "DD Report" },
				{ value: "fact_sheet", label: "Fact Sheet" },
				{ value: "compliance", label: "Compliance" },
				{ value: "other", label: "Other" },
			]}
		/>
	</div>

	{#if filtered.length === 0}
		<EmptyState
			title="No documents yet"
			message="Upload a fund prospectus, DDQ, or financial statement to start analysis."
			actionLabel="Upload Document"
			onAction={() => goto('/documents/upload')}
		/>
	{:else}
		<DataTable
			data={filtered}
			{columns}
			onRowClick={(row) => goto(`/documents/${(row as Record<string, unknown>).id}`)}
		/>
	{/if}
</div>
