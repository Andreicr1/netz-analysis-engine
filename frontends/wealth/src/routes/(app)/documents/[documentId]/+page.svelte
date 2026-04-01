<!--
  Document detail — metadata display + inline preview (PDF/image) + re-process action.
-->
<script lang="ts">
	import { getContext, onDestroy } from "svelte";
	import { invalidateAll } from "$app/navigation";
	import { PageHeader, Button, StatusBadge, EmptyState, formatDateTime } from "@investintell/ui";
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

	// ── Preview state ────────────────────────────────────────────────
	let previewUrl = $state<string | null>(null);
	let previewContentType = $state<string | null>(null);
	let previewFilename = $state<string>("document");
	let previewLoading = $state(false);
	let previewError = $state<string | null>(null);
	let previewExpiresAt = $state<number>(0);

	let isPdf = $derived(previewContentType?.startsWith("application/pdf") ?? false);
	let isImage = $derived(previewContentType?.startsWith("image/") ?? false);
	let isExpired = $derived(previewExpiresAt > 0 && Date.now() > previewExpiresAt);

	async function loadPreview() {
		if (!doc || doc.current_version < 1) return;
		previewLoading = true;
		previewError = null;
		try {
			const api = createClientApiClient(getToken);
			const res = await api.get<{ url: string; content_type: string; filename: string }>(
				`/wealth/documents/${documentId}/preview-url`,
			);
			previewUrl = res.url;
			previewContentType = res.content_type;
			previewFilename = res.filename;
			previewExpiresAt = Date.now() + 5 * 60 * 1000; // 5 min TTL
		} catch (e) {
			previewError = e instanceof Error ? e.message : "Failed to load preview";
		} finally {
			previewLoading = false;
		}
	}

	// Auto-load preview when doc is available with a version
	$effect(() => {
		if (doc && doc.current_version >= 1 && !previewUrl && !previewLoading && !previewError) {
			loadPreview();
		}
	});

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

		<!-- Preview section -->
		{#if doc.current_version >= 1}
			<div class="dd-preview-section">
				<div class="dd-preview-header">
					<h3 class="dd-preview-title">Preview</h3>
					{#if isExpired || previewError}
						<Button size="sm" variant="outline" onclick={loadPreview} disabled={previewLoading}>
							{previewLoading ? "Loading…" : "Refresh"}
						</Button>
					{/if}
				</div>

				{#if previewLoading}
					<div class="dd-preview-loading">Loading preview…</div>
				{:else if previewError}
					<div class="dd-preview-error">{previewError}</div>
				{:else if previewUrl && isPdf}
					<div class="dd-pdf-preview">
						<object data={previewUrl} type="application/pdf" title={previewFilename}>
							<p class="dd-pdf-fallback">
								PDF preview not available in this browser.
								<a href={previewUrl} download={previewFilename}>Download PDF</a>
							</p>
						</object>
					</div>
				{:else if previewUrl && isImage}
					<div class="dd-image-preview">
						<img src={previewUrl} alt={previewFilename} />
					</div>
				{:else if previewUrl}
					<div class="dd-download-only">
						<a href={previewUrl} download={previewFilename} class="dd-download-link">
							Download {previewFilename}
						</a>
					</div>
				{/if}
			</div>
		{/if}
	{/if}
</div>

<style>
	.dd-page {
		padding: var(--ii-space-stack-md, 16px) var(--ii-space-inline-lg, 24px);
		max-width: 900px;
	}

	.dd-error {
		padding: var(--ii-space-stack-xs, 8px) var(--ii-space-inline-sm, 12px);
		border-radius: var(--ii-radius-sm, 8px);
		background: color-mix(in srgb, var(--ii-danger) 8%, transparent);
		color: var(--ii-danger);
		font-size: var(--ii-text-small, 0.8125rem);
		margin-bottom: var(--ii-space-stack-md, 16px);
	}

	.dd-meta-grid {
		border: 1px solid var(--ii-border-subtle);
		border-radius: var(--ii-radius-md, 12px);
		overflow: hidden;
	}

	.dd-kv {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: var(--ii-space-stack-xs, 10px) var(--ii-space-inline-md, 16px);
		border-bottom: 1px solid var(--ii-border-subtle);
		font-size: var(--ii-text-small, 0.8125rem);
	}

	.dd-kv:last-child { border-bottom: none; }

	.dd-k { color: var(--ii-text-muted); }
	.dd-v { color: var(--ii-text-primary); font-weight: 500; }
	.dd-v--mono { font-family: var(--ii-font-mono); font-size: var(--ii-text-label, 0.75rem); }

	/* Preview section */
	.dd-preview-section {
		margin-top: var(--ii-space-stack-md, 16px);
	}

	.dd-preview-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: var(--ii-space-stack-xs, 8px);
	}

	.dd-preview-title {
		font-size: var(--ii-text-body, 0.9375rem);
		font-weight: 600;
		color: var(--ii-text-primary);
	}

	.dd-preview-loading {
		padding: var(--ii-space-stack-lg, 24px);
		text-align: center;
		color: var(--ii-text-muted);
		font-size: var(--ii-text-small, 0.8125rem);
		border: 1px solid var(--ii-border-subtle);
		border-radius: var(--ii-radius-md, 12px);
	}

	.dd-preview-error {
		padding: var(--ii-space-stack-sm, 12px) var(--ii-space-inline-md, 16px);
		border-radius: var(--ii-radius-sm, 8px);
		background: color-mix(in srgb, var(--ii-danger) 8%, transparent);
		color: var(--ii-danger);
		font-size: var(--ii-text-small, 0.8125rem);
	}

	.dd-pdf-preview {
		width: 100%;
		border: 1px solid var(--ii-border-subtle);
		border-radius: var(--ii-radius-md, 12px);
		overflow: hidden;
	}

	.dd-pdf-preview object {
		width: 100%;
		height: 80vh;
		min-height: 600px;
	}

	.dd-pdf-fallback {
		padding: var(--ii-space-stack-lg, 24px);
		text-align: center;
		color: var(--ii-text-muted);
		font-size: var(--ii-text-small, 0.8125rem);
	}

	.dd-pdf-fallback a {
		color: var(--ii-brand-primary);
		text-decoration: underline;
	}

	.dd-image-preview {
		border: 1px solid var(--ii-border-subtle);
		border-radius: var(--ii-radius-md, 12px);
		overflow: hidden;
	}

	.dd-image-preview img {
		width: 100%;
		height: auto;
		display: block;
	}

	.dd-download-only {
		padding: var(--ii-space-stack-md, 16px);
		text-align: center;
		border: 1px solid var(--ii-border-subtle);
		border-radius: var(--ii-radius-md, 12px);
	}

	.dd-download-link {
		color: var(--ii-brand-primary);
		text-decoration: underline;
		font-size: var(--ii-text-small, 0.8125rem);
	}
</style>
