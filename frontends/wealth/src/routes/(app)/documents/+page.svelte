<!--
  Documents — List + Process Pending + navigate to upload/detail.
-->
<script lang="ts">
	import { goto, invalidateAll } from "$app/navigation";
	import { getContext } from "svelte";
	import {
		PageHeader, Button, StatusBadge, EmptyState,
		formatDateTime,
	} from "@netz/ui";
	import { createClientApiClient } from "$lib/api/client";
	import type { PageData } from "./$types";
	import type { WealthDocument, DocumentPage, ProcessPendingResponse } from "$lib/types/document";
	import { domainLabel } from "$lib/types/document";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let { data }: { data: PageData } = $props();

	let docs = $derived(data.documents as DocumentPage);
	let items = $derived(docs.items ?? []);

	// ── Domain filter ─────────────────────────────────────────────────────

	let domainFilter = $state<string | null>(null);

	let filtered = $derived.by(() => {
		if (!domainFilter) return items;
		return items.filter((d) => d.domain === domainFilter);
	});

	let distinctDomains = $derived(
		[...new Set(items.map((d) => d.domain).filter(Boolean))] as string[]
	);

	// ── Process pending ───────────────────────────────────────────────────

	let processing = $state(false);
	let processResult = $state<ProcessPendingResponse | null>(null);
	let error = $state<string | null>(null);

	async function processPending() {
		processing = true;
		error = null;
		processResult = null;
		try {
			const api = createClientApiClient(getToken);
			processResult = await api.post<ProcessPendingResponse>("/wealth/documents/ingestion/process-pending", { limit: 10 });
			await invalidateAll();
		} catch (e) {
			error = e instanceof Error ? e.message : "Processing failed";
		} finally {
			processing = false;
		}
	}
</script>

<PageHeader title="Documents">
	{#snippet actions()}
		<div class="doc-actions">
			<Button size="sm" variant="outline" onclick={processPending} disabled={processing}>
				{processing ? "Processing…" : "Process Pending"}
			</Button>
			<Button size="sm" onclick={() => goto("/documents/upload")}>Upload</Button>
		</div>
	{/snippet}
</PageHeader>

<div class="doc-page">
	<!-- Process result banner -->
	{#if processResult}
		<div class="doc-result">
			Processed: {processResult.processed} · Indexed: {processResult.indexed} · Failed: {processResult.failed} · Skipped: {processResult.skipped}
		</div>
	{/if}

	{#if error}
		<div class="doc-error">{error}</div>
	{/if}

	<!-- Toolbar -->
	<div class="doc-toolbar">
		<select class="doc-filter" bind:value={domainFilter}>
			<option value={null}>All domains</option>
			{#each distinctDomains as d (d)}
				<option value={d}>{domainLabel(d)}</option>
			{/each}
		</select>
		<span class="doc-count">{filtered.length} document{filtered.length !== 1 ? "s" : ""}</span>
	</div>

	{#if filtered.length === 0}
		<EmptyState title="No documents" message="Upload PDFs to start the ingestion pipeline." />
	{:else}
		<div class="doc-table-wrap">
			<table class="doc-table">
				<thead>
					<tr>
						<th class="dth-title">Title</th>
						<th class="dth-file">Filename</th>
						<th class="dth-domain">Domain</th>
						<th class="dth-ver">Version</th>
						<th class="dth-date">Created</th>
					</tr>
				</thead>
				<tbody>
					{#each filtered as doc (doc.id)}
						<tr class="doc-row" onclick={() => goto(`/documents/${doc.id}`)}>
							<td class="dtd-title">{doc.title}</td>
							<td class="dtd-file">{doc.filename}</td>
							<td class="dtd-domain">
								<span class="domain-badge">{domainLabel(doc.domain)}</span>
							</td>
							<td class="dtd-ver">v{doc.current_version}</td>
							<td class="dtd-date">{doc.created_at ? formatDateTime(doc.created_at) : "—"}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}
</div>

<style>
	.doc-page {
		display: flex;
		flex-direction: column;
		height: calc(100vh - 64px);
		overflow: hidden;
	}

	.doc-actions {
		display: flex;
		gap: var(--netz-space-inline-xs, 6px);
	}

	.doc-result {
		padding: var(--netz-space-stack-xs, 8px) var(--netz-space-inline-md, 16px);
		background: color-mix(in srgb, var(--netz-success) 8%, transparent);
		color: var(--netz-success);
		font-size: var(--netz-text-small, 0.8125rem);
		font-variant-numeric: tabular-nums;
	}

	.doc-error {
		padding: var(--netz-space-stack-xs, 8px) var(--netz-space-inline-md, 16px);
		background: color-mix(in srgb, var(--netz-danger) 8%, transparent);
		color: var(--netz-danger);
		font-size: var(--netz-text-small, 0.8125rem);
	}

	.doc-toolbar {
		display: flex;
		align-items: center;
		gap: var(--netz-space-inline-sm, 10px);
		padding: var(--netz-space-stack-xs, 8px) var(--netz-space-inline-md, 16px);
		border-bottom: 1px solid var(--netz-border-subtle);
		flex-shrink: 0;
	}

	.doc-filter {
		height: var(--netz-space-control-height-sm, 30px);
		padding: 0 var(--netz-space-inline-xs, 8px);
		border: 1px solid var(--netz-border);
		border-radius: var(--netz-radius-sm, 6px);
		background: var(--netz-surface-elevated);
		color: var(--netz-text-primary);
		font-size: var(--netz-text-small, 0.8125rem);
		font-family: var(--netz-font-sans);
	}

	.doc-count {
		font-size: var(--netz-text-small, 0.8125rem);
		color: var(--netz-text-muted);
		margin-left: auto;
	}

	.doc-table-wrap { flex: 1; overflow: auto; }

	.doc-table {
		width: 100%;
		border-collapse: collapse;
		font-size: var(--netz-text-small, 0.8125rem);
	}

	.doc-table thead { position: sticky; top: 0; z-index: 1; }

	.doc-table th {
		padding: var(--netz-space-stack-2xs, 5px) var(--netz-space-inline-sm, 12px);
		text-align: left;
		font-size: var(--netz-text-label, 0.75rem);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.02em;
		color: var(--netz-text-muted);
		background: var(--netz-surface-alt);
		border-bottom: 1px solid var(--netz-border-subtle);
	}

	.doc-table td {
		padding: var(--netz-space-stack-2xs, 6px) var(--netz-space-inline-sm, 12px);
		border-bottom: 1px solid var(--netz-border-subtle);
	}

	.doc-row { cursor: pointer; transition: background-color 80ms ease; }
	.doc-row:hover { background: var(--netz-surface-highlight, color-mix(in srgb, var(--netz-brand-primary) 4%, transparent)); }

	.dth-title { min-width: 200px; }
	.dth-file { min-width: 160px; }
	.dth-domain { width: 100px; }
	.dth-ver { width: 60px; }
	.dth-date { width: 140px; }

	.dtd-title { font-weight: 500; color: var(--netz-text-primary); }
	.dtd-file { color: var(--netz-text-secondary); font-family: var(--netz-font-mono); font-size: var(--netz-text-label, 0.75rem); }
	.dtd-ver { font-variant-numeric: tabular-nums; color: var(--netz-text-secondary); }
	.dtd-date { color: var(--netz-text-muted); font-variant-numeric: tabular-nums; }

	.domain-badge {
		font-size: var(--netz-text-label, 0.75rem);
		padding: 1px 8px;
		border-radius: var(--netz-radius-pill, 999px);
		background: var(--netz-surface-alt);
		color: var(--netz-text-secondary);
		white-space: nowrap;
	}
</style>
