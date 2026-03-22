<!--
  Document detail — metadata display with re-process action.
-->
<script lang="ts">
	import { getContext } from "svelte";
	import { invalidateAll } from "$app/navigation";
	import { PageHeader, Button, StatusBadge, EmptyState, formatDateTime } from "@netz/ui";
	import { createClientApiClient } from "$lib/api/client";
	import type { PageData } from "./$types";
	import type { WealthDocument, ProcessPendingResponse } from "$lib/types/document";
	import { domainLabel } from "$lib/types/document";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let { data }: { data: PageData } = $props();

	let doc = $derived(data.document as WealthDocument | null);
	let documentId = $derived(data.documentId as string);

	let reprocessing = $state(false);
	let error = $state<string | null>(null);

	async function reprocess() {
		reprocessing = true;
		error = null;
		try {
			const api = createClientApiClient(getToken);
			await api.post<ProcessPendingResponse>("/wealth/documents/ingestion/process-pending", { limit: 1 });
			await invalidateAll();
		} catch (e) {
			error = e instanceof Error ? e.message : "Re-processing failed";
		} finally {
			reprocessing = false;
		}
	}
</script>

<PageHeader
	title={doc?.title ?? "Document"}
	breadcrumbs={[{ label: "Documents", href: "/documents" }, { label: doc?.title ?? documentId }]}
>
	{#snippet actions()}
		<Button size="sm" variant="outline" onclick={reprocess} disabled={reprocessing}>
			{reprocessing ? "Processing…" : "Re-process"}
		</Button>
	{/snippet}
</PageHeader>

<div class="dd-page">
	{#if error}
		<div class="dd-error">{error}</div>
	{/if}

	{#if !doc}
		<EmptyState title="Document not found" />
	{:else}
		<div class="dd-meta-grid">
			<div class="dd-kv"><span class="dd-k">Filename</span><span class="dd-v dd-v--mono">{doc.filename}</span></div>
			<div class="dd-kv"><span class="dd-k">Content Type</span><span class="dd-v">{doc.content_type ?? "—"}</span></div>
			<div class="dd-kv"><span class="dd-k">Domain</span><span class="dd-v">{domainLabel(doc.domain)}</span></div>
			<div class="dd-kv"><span class="dd-k">Version</span><span class="dd-v">v{doc.current_version}</span></div>
			<div class="dd-kv"><span class="dd-k">Created</span><span class="dd-v">{doc.created_at ? formatDateTime(doc.created_at) : "—"}</span></div>
			{#if doc.updated_at}
				<div class="dd-kv"><span class="dd-k">Updated</span><span class="dd-v">{formatDateTime(doc.updated_at)}</span></div>
			{/if}
			{#if doc.created_by}
				<div class="dd-kv"><span class="dd-k">Created By</span><span class="dd-v">{doc.created_by}</span></div>
			{/if}
		</div>
	{/if}
</div>

<style>
	.dd-page {
		padding: var(--netz-space-stack-md, 16px) var(--netz-space-inline-lg, 24px);
		max-width: 600px;
	}

	.dd-error {
		padding: var(--netz-space-stack-xs, 8px) var(--netz-space-inline-sm, 12px);
		border-radius: var(--netz-radius-sm, 8px);
		background: color-mix(in srgb, var(--netz-danger) 8%, transparent);
		color: var(--netz-danger);
		font-size: var(--netz-text-small, 0.8125rem);
		margin-bottom: var(--netz-space-stack-md, 16px);
	}

	.dd-meta-grid {
		border: 1px solid var(--netz-border-subtle);
		border-radius: var(--netz-radius-md, 12px);
		overflow: hidden;
	}

	.dd-kv {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: var(--netz-space-stack-xs, 10px) var(--netz-space-inline-md, 16px);
		border-bottom: 1px solid var(--netz-border-subtle);
		font-size: var(--netz-text-small, 0.8125rem);
	}

	.dd-kv:last-child { border-bottom: none; }

	.dd-k { color: var(--netz-text-muted); }
	.dd-v { color: var(--netz-text-primary); font-weight: 500; }
	.dd-v--mono { font-family: var(--netz-font-mono); font-size: var(--netz-text-label, 0.75rem); }
</style>
