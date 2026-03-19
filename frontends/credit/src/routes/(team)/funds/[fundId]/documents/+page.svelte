<!--
  Document list — folders sidebar, document table, ingestion control, evidence lifecycle.
-->
<script lang="ts">
	import { DataTable, Button, EmptyState, Card, Dialog, PageHeader } from "@netz/ui";
	import { ActionButton, ConfirmDialog, FormField } from "@netz/ui";
	import IngestionProgress from "$lib/components/IngestionProgress.svelte";
	import { createClientApiClient } from "$lib/api/client";
	import { invalidateAll, goto } from "$app/navigation";
	import { getContext } from "svelte";
	import type { PageData } from "./$types";
	import type { PaginatedResponse, DocumentItem } from "$lib/types/api";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let { data }: { data: PageData } = $props();

	let documents = $derived((data.documents as PaginatedResponse<DocumentItem>)?.items ?? []);
	let rootFolders = $derived((data.rootFolders ?? []) as Array<{ id: string; name: string }>);

	let actionError = $state<string | null>(null);

	// ── Folder Management ──
	let showCreateFolder = $state(false);
	let folderName = $state("");
	let creatingFolder = $state(false);

	async function createFolder() {
		if (!folderName.trim()) return;
		creatingFolder = true;
		try {
			const api = createClientApiClient(getToken);
			await api.post("/documents/root-folders", { name: folderName.trim() });
			showCreateFolder = false;
			folderName = "";
			await invalidateAll();
		} catch (e) {
			actionError = e instanceof Error ? e.message : "Failed to create folder";
		} finally {
			creatingFolder = false;
		}
	}

	// ── Ingestion Control ──
	let processing = $state(false);
	let ingestionJobId = $state<string | null>(null);

	async function processPending() {
		processing = true;
		actionError = null;
		try {
			const api = createClientApiClient(getToken);
			const res = await api.post<{ job_id?: string }>("/documents/ingestion/process-pending", {});
			ingestionJobId = res.job_id ?? null;
		} catch (e) {
			actionError = e instanceof Error ? e.message : "Failed to process documents";
		} finally {
			processing = false;
		}
	}

	// ── Evidence Lifecycle ──
	let showEvidenceUpload = $state(false);
	let requestingEvidence = $state(false);

	async function requestEvidenceUpload() {
		requestingEvidence = true;
		try {
			const api = createClientApiClient(getToken);
			await api.post(`/funds/${data.fundId}/evidence/upload-request`, {});
			showEvidenceUpload = false;
			await invalidateAll();
		} catch (e) {
			actionError = e instanceof Error ? e.message : "Failed to request upload";
		} finally {
			requestingEvidence = false;
		}
	}

	// ── Submit for Review ──
	async function submitForReview(documentId: string) {
		try {
			const api = createClientApiClient(getToken);
			await api.post(`/funds/${data.fundId}/document-reviews`, { document_id: documentId });
			await invalidateAll();
		} catch (e) {
			actionError = e instanceof Error ? e.message : "Failed to submit for review";
		}
	}

	const columns = [
		{ accessorKey: "title", header: "Title" },
		{ accessorKey: "root_folder", header: "Folder" },
		{ accessorKey: "domain", header: "Domain" },
		{ accessorKey: "status", header: "Status" },
		{ accessorKey: "created_at", header: "Uploaded" },
	];
</script>

<div class="flex h-full">
	<!-- Folder sidebar -->
	<aside class="w-52 shrink-0 border-r border-(--netz-border) bg-(--netz-surface-alt) p-4">
		<div class="mb-3 flex items-center justify-between">
			<h3 class="text-xs font-semibold uppercase tracking-wider text-(--netz-text-muted)">Folders</h3>
			<button
				class="text-xs text-(--netz-brand-primary) hover:underline"
				onclick={() => showCreateFolder = true}
			>
				+ New
			</button>
		</div>
		<button
			class="mb-1 w-full rounded px-2 py-1.5 text-left text-xs text-(--netz-text-primary) hover:bg-(--netz-surface-alt)"
			onclick={() => goto(`/funds/${data.fundId}/documents`)}
		>
			All Documents
		</button>
		{#each rootFolders as folder (folder.id)}
			<button
				class="mb-1 w-full rounded px-2 py-1.5 text-left text-xs text-(--netz-text-secondary) hover:bg-(--netz-surface-alt)"
				onclick={() => goto(`/funds/${data.fundId}/documents?root_folder=${folder.name}`)}
			>
				{folder.name}
			</button>
		{/each}
	</aside>

	<!-- Main content -->
	<div class="flex-1 px-6">
		<PageHeader
			title="Documents"
			breadcrumbs={[{ label: "Funds", href: "/funds" }, { label: "Documents" }]}
		>
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
					<Button size="sm" variant="outline" onclick={() => showEvidenceUpload = true}>
						Request Evidence
					</Button>
					<Button size="sm" href="/funds/{data.fundId}/documents/upload">Upload</Button>
					<Button size="sm" variant="outline" href="/funds/{data.fundId}/documents/reviews">Reviews</Button>
					<Button size="sm" variant="outline" href="/funds/{data.fundId}/documents/dataroom">Dataroom</Button>
					<Button size="sm" variant="outline" href="/funds/{data.fundId}/documents/auditor">Auditor View</Button>
				</div>
			{/snippet}
		</PageHeader>

		{#if actionError}
			<div class="mb-4 rounded-md border border-(--netz-status-error) bg-(--netz-status-error)/10 p-3 text-sm text-(--netz-status-error)">
				{actionError}
				<button class="ml-2 underline" onclick={() => actionError = null}>dismiss</button>
			</div>
		{/if}

		{#if ingestionJobId}
			<div class="mb-4">
				<IngestionProgress jobId={ingestionJobId} />
			</div>
		{/if}

		{#if documents.length === 0}
			<EmptyState
				title="No Documents"
				description="Upload documents to start the ingestion pipeline."
			/>
		{:else}
			<DataTable
				data={documents}
				{columns}
				onRowClick={(row) => goto(`/funds/${data.fundId}/documents/${(row as Record<string, unknown>).id}`)}
			/>
		{/if}
	</div>
</div>

<!-- Create Folder Dialog -->
<Dialog bind:open={showCreateFolder} title="Create Root Folder">
	<div class="space-y-4">
		<FormField label="Folder Name" required>
			<input
				type="text"
				class="w-full rounded-md border border-(--netz-border) bg-(--netz-surface) px-3 py-2 text-sm text-(--netz-text-primary)"
				bind:value={folderName}
				placeholder="e.g. Legal Documents"
			/>
		</FormField>
		<div class="flex justify-end gap-2">
			<Button variant="outline" onclick={() => showCreateFolder = false}>Cancel</Button>
			<ActionButton onclick={createFolder} loading={creatingFolder} loadingText="Creating..." disabled={!folderName.trim()}>
				Create
			</ActionButton>
		</div>
	</div>
</Dialog>

<!-- Evidence Upload Request Dialog -->
<ConfirmDialog
	bind:open={showEvidenceUpload}
	title="Request Evidence Upload"
	message="This will generate a signed upload URL for evidence documents. Continue?"
	confirmLabel="Request Upload"
	confirmVariant="default"
	onConfirm={requestEvidenceUpload}
	onCancel={() => showEvidenceUpload = false}
/>
