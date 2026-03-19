<!--
  Wealth Document Detail — shows document metadata and version history.
-->
<script lang="ts">
	import { PageHeader, Card, SectionCard, EmptyState, Badge, Button } from "@netz/ui";
	import { ActionButton } from "@netz/ui";
	import { formatDateTime } from "@netz/ui";
	import { createClientApiClient } from "$lib/api/client";
	import { invalidateAll } from "$app/navigation";
	import { getContext } from "svelte";
	import type { PageData } from "./$types";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let { data }: { data: PageData } = $props();

	type WealthDocument = {
		id: string;
		organization_id: string;
		portfolio_id: string | null;
		instrument_id: string | null;
		title: string;
		filename: string;
		content_type: string | null;
		root_folder: string;
		subfolder_path: string | null;
		domain: string | null;
		current_version: number;
		created_at: string | null;
		updated_at: string | null;
		created_by: string | null;
	};

	let document = $derived(data.document as WealthDocument | null);

	let actionError = $state<string | null>(null);
	let reprocessing = $state(false);

	async function reprocess() {
		if (!document) return;
		reprocessing = true;
		actionError = null;
		try {
			const api = createClientApiClient(getToken);
			await api.post("/wealth/documents/ingestion/process-pending", { limit: 1 });
			await invalidateAll();
		} catch (e) {
			actionError = e instanceof Error ? e.message : "Re-process failed";
		} finally {
			reprocessing = false;
		}
	}
</script>

<div class="space-y-(--netz-space-section-gap) p-(--netz-space-page-gutter)">
	{#if document}
		<PageHeader
			title={document.title || document.filename}
			breadcrumbs={[{ label: "Documents", href: "/documents" }, { label: document.title || document.filename }]}
		>
			{#snippet actions()}
				<ActionButton
					size="sm"
					variant="outline"
					onclick={reprocess}
					loading={reprocessing}
					loadingText="Re-processing..."
				>
					Re-process
				</ActionButton>
			{/snippet}
		</PageHeader>

		{#if actionError}
			<div class="rounded-md border border-(--netz-status-error) bg-(--netz-status-error)/10 p-3 text-sm text-(--netz-status-error)">
				{actionError}
				<button class="ml-2 underline" onclick={() => actionError = null}>dismiss</button>
			</div>
		{/if}

		<Card class="p-6">
			<div class="grid gap-4 sm:grid-cols-2">
				<div>
					<p class="text-xs text-(--netz-text-muted)">Filename</p>
					<p class="text-sm font-medium text-(--netz-text-primary)">{document.filename}</p>
				</div>
				<div>
					<p class="text-xs text-(--netz-text-muted)">Content Type</p>
					<p class="text-sm text-(--netz-text-primary)">{document.content_type ?? "—"}</p>
				</div>
				<div>
					<p class="text-xs text-(--netz-text-muted)">Domain</p>
					<p class="text-sm text-(--netz-text-primary)">
						{#if document.domain}
							<Badge variant="secondary">{document.domain}</Badge>
						{:else}
							—
						{/if}
					</p>
				</div>
				<div>
					<p class="text-xs text-(--netz-text-muted)">Version</p>
					<p class="text-sm text-(--netz-text-primary)">{document.current_version}</p>
				</div>
				<div>
					<p class="text-xs text-(--netz-text-muted)">Root Folder</p>
					<p class="text-sm text-(--netz-text-primary)">{document.root_folder}</p>
				</div>
				{#if document.subfolder_path}
					<div>
						<p class="text-xs text-(--netz-text-muted)">Subfolder</p>
						<p class="text-sm text-(--netz-text-primary)">{document.subfolder_path}</p>
					</div>
				{/if}
				<div>
					<p class="text-xs text-(--netz-text-muted)">Created</p>
					<p class="text-sm text-(--netz-text-primary)">{document.created_at ? formatDateTime(document.created_at) : "—"}</p>
				</div>
				{#if document.created_by}
					<div>
						<p class="text-xs text-(--netz-text-muted)">Created By</p>
						<p class="text-sm text-(--netz-text-primary)">{document.created_by}</p>
					</div>
				{/if}
			</div>
		</Card>
	{:else}
		<PageHeader
			title="Document Not Found"
			breadcrumbs={[{ label: "Documents", href: "/documents" }, { label: "Not Found" }]}
		/>
		<EmptyState
			title="Document not found"
			description="The requested document does not exist or you don't have access."
		/>
	{/if}
</div>
