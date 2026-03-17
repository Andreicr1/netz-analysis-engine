<!--
  Auditor Evidence View — DataTable with all evidence, filterable by status.
-->
<script lang="ts">
	import { DataTable, PageHeader, EmptyState } from "@netz/ui";
	import { ActionButton } from "@netz/ui";
	import { createClientApiClient } from "$lib/api/client";
	import { getContext } from "svelte";
	import type { PageData } from "./$types";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let { data }: { data: PageData } = $props();

	type Evidence = {
		id: string;
		filename: string;
		status: string;
		document_title: string | null;
		uploaded_at: string | null;
		created_at: string;
	};

	let evidence = $derived(((data.evidence as { items: Evidence[] })?.items ?? []) as Evidence[]);
	let markingId = $state<string | null>(null);

	async function markComplete(evidenceId: string) {
		markingId = evidenceId;
		try {
			const api = createClientApiClient(getToken);
			await api.patch(`/funds/${data.fundId}/evidence/${evidenceId}/complete`, {});
			window.location.reload();
		} catch {
			// Error handled by api-client
		} finally {
			markingId = null;
		}
	}

	const columns = [
		{ accessorKey: "filename", header: "Filename" },
		{ accessorKey: "document_title", header: "Document" },
		{ accessorKey: "status", header: "Status" },
		{ accessorKey: "uploaded_at", header: "Uploaded" },
		{ accessorKey: "created_at", header: "Created" },
	];
</script>

<div class="p-6">
	<PageHeader title="Auditor Evidence View" />

	{#if evidence.length === 0}
		<EmptyState title="No Evidence" description="Evidence documents across all deals will appear here." />
	{:else}
		<div class="space-y-3">
			{#each evidence as item (item.id)}
				<div class="flex items-center justify-between rounded-md border border-[var(--netz-border)] p-4">
					<div>
						<p class="text-sm font-medium text-[var(--netz-text-primary)]">{item.filename}</p>
						<p class="text-xs text-[var(--netz-text-muted)]">
							{item.document_title ?? ""} | {item.status} | {item.created_at}
						</p>
					</div>
					{#if item.status !== "complete" && item.status !== "completed"}
						<ActionButton
							size="sm"
							onclick={() => markComplete(item.id)}
							loading={markingId === item.id}
							loadingText="..."
						>
							Mark Complete
						</ActionButton>
					{/if}
				</div>
			{/each}
		</div>
	{/if}
</div>
