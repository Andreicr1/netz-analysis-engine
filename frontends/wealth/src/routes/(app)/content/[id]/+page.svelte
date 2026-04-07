<!--
  Content Detail — markdown reader with approve/download actions.
  Layout: sticky header + rendered content body + content_data sidebar.
  Mirrors DD report viewer patterns for approval workflow.
-->
<script lang="ts">
	import { getContext } from "svelte";
	import { invalidateAll, invalidate } from "$app/navigation";
	import { page as pageState } from "$app/state";
	import {
		PageHeader, StatusBadge, Button, ConsequenceDialog,
		formatDateTime,
	} from "@investintell/ui";
	import { PanelErrorState, PanelEmptyState } from "@investintell/ui/runtime";
	import { ForbiddenError } from "@investintell/ui/utils";
	import type { ConsequenceDialogPayload } from "@investintell/ui";
	import { createClientApiClient } from "$lib/api/client";
	import type { PageData } from "./$types";
	import type { ContentFull } from "$lib/types/content";
	import { contentTypeLabel, contentTypeColor } from "$lib/types/content";
	import { renderMarkdown, flattenObject } from "$lib/utils/render-markdown";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let { data }: { data: PageData } = $props();

	// ── Route Data Contract (§3.2) ──────────────────────────────────────
	// `data.content` is a RouteData<ContentFull>. The template guards
	// render-error / empty / data in three explicit branches — the
	// script-level `content` cast assumes the success branch because
	// every downstream `$derived` only evaluates inside that branch at
	// runtime (Svelte recomputes when `routeData.data` flips to null).
	const routeData = $derived(data.content);
	let content = $derived(routeData.data as ContentFull);
	let actorId = $derived((data.actorId ?? null) as string | null);
	let actorRole = $derived((data.actorRole ?? null) as string | null);

	function retryLoad() {
		invalidate(pageState.url.pathname);
	}

	// ── Approval logic ────────────────────────────────────────────────────

	const IC_ROLES = ["admin", "super_admin", "investment_team"];
	let canApprove = $derived(
		(content.status === "draft" || content.status === "review") &&
		actorRole !== null &&
		IC_ROLES.includes(actorRole) &&
		actorId !== content.created_by,
	);
	let isSelfAuthored = $derived(
		actorId !== null && content.created_by === actorId,
	);

	let approveDialogOpen = $state(false);
	let error = $state<string | null>(null);

	async function handleApprove(payload: ConsequenceDialogPayload) {
		try {
			const api = createClientApiClient(getToken);
			await api.post(`/content/${content.id}/approve`, { rationale: payload.rationale });
			approveDialogOpen = false;
			await invalidateAll();
		} catch (e) {
			if (e instanceof ForbiddenError) {
				error = "Cannot approve your own content. Another team member must approve.";
			} else {
				error = e instanceof Error ? e.message : "Approval failed";
			}
			approveDialogOpen = false;
		}
	}

	// ── Download ──────────────────────────────────────────────────────────

	let downloading = $state(false);

	function canDownload(): boolean {
		return content.status === "approved" || content.status === "published";
	}

	async function downloadPdf() {
		downloading = true;
		try {
			const api = createClientApiClient(getToken);
			const blob = await api.getBlob(`/content/${content.id}/download`);
			const url = URL.createObjectURL(blob);
			const a = document.createElement("a");
			a.href = url;
			a.download = `${content.content_type}_${content.language}.pdf`;
			a.click();
			URL.revokeObjectURL(url);
		} catch (e) {
			error = e instanceof Error ? e.message : "Download failed";
		} finally {
			downloading = false;
		}
	}

	// ── Content data display ─────────────────────────────────────────────

	let hasContentData = $derived(
		content.content_data !== null &&
		content.content_data !== undefined &&
		Object.keys(content.content_data).length > 0,
	);
</script>

{#if routeData.error}
	<PanelErrorState
		title="Unable to load content"
		message={routeData.error.message}
		onRetry={routeData.error.recoverable ? retryLoad : undefined}
	/>
{:else if !routeData.data}
	<PanelEmptyState
		title="No content available"
		message="This content is not available at the moment."
	/>
{:else}
<PageHeader
	title={content.title ?? contentTypeLabel(content.content_type)}
	breadcrumbs={[{ label: "Content", href: "/content" }, { label: content.title ?? contentTypeLabel(content.content_type) }]}
>
	{#snippet actions()}
		<div class="cd-actions">
			{#if canApprove}
				<Button size="sm" variant="outline" onclick={() => approveDialogOpen = true}>
					Approve
				</Button>
			{:else if (content.status === "draft" || content.status === "review") && isSelfAuthored}
				<span class="cd-self-hint" title="Cannot approve your own content">
					<Button size="sm" variant="outline" disabled>Approve</Button>
				</span>
			{/if}
			{#if canDownload()}
				<Button size="sm" onclick={downloadPdf} disabled={downloading}>
					{downloading ? "Downloading\u2026" : "Download PDF"}
				</Button>
			{/if}
		</div>
	{/snippet}
</PageHeader>

{#if error}
	<div class="cd-error">
		<span>{error}</span>
		<button class="cd-error-dismiss" onclick={() => error = null} type="button">&times;</button>
	</div>
{/if}

<!-- Meta bar -->
<div class="cd-meta-bar">
	<span class="cd-type" style:color={contentTypeColor(content.content_type)}>
		{contentTypeLabel(content.content_type)}
	</span>
	<StatusBadge status={content.status} />
	<span class="cd-lang">{content.language.toUpperCase()}</span>
	<span class="cd-date">{formatDateTime(content.created_at)}</span>
	{#if content.created_by}
		<span class="cd-author">by {content.created_by}</span>
	{/if}
	{#if content.approved_at}
		<span class="cd-approved">
			Approved {formatDateTime(content.approved_at)}
			{#if content.approved_by} by {content.approved_by}{/if}
		</span>
	{/if}
</div>

<!-- Content body -->
<div class="cd-page">
	{#if content.status === "draft" && !content.content_md}
		<div class="cd-generating">
			<span class="cd-spinner"></span>
			Content is being generated&hellip;
		</div>
	{:else}
		<div class="cd-body">
			{@html renderMarkdown(content.content_md)}
		</div>
	{/if}

	<!-- Content data (collapsible) -->
	{#if hasContentData}
		<details class="cd-data-section">
			<summary class="cd-data-toggle">View Content Data</summary>
			<div class="cd-data-grid">
				{#each flattenObject(content.content_data!) as entry (entry.key)}
					<div class="cd-data-row">
						<span class="cd-data-key">{entry.key}</span>
						<span class="cd-data-val">{entry.value}</span>
					</div>
				{/each}
			</div>
		</details>
	{/if}
</div>

<!-- Approve dialog -->
<ConsequenceDialog
	bind:open={approveDialogOpen}
	title="Approve Content"
	impactSummary="This content will be marked as approved and available for distribution."
	requireRationale={true}
	rationaleLabel="Approval Rationale"
	rationalePlaceholder="Confirm this content meets committee standards (min 10 chars)."
	rationaleMinLength={10}
	confirmLabel="Approve"
	metadata={[
		{ label: "Type", value: contentTypeLabel(content.content_type) },
		{ label: "Language", value: content.language.toUpperCase() },
	]}
	onConfirm={handleApprove}
/>
{/if}

<style>
	.cd-actions {
		display: flex;
		gap: var(--ii-space-inline-xs, 6px);
	}

	.cd-self-hint {
		cursor: not-allowed;
	}

	.cd-error {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--ii-space-stack-xs, 8px) var(--ii-space-inline-lg, 24px);
		background: color-mix(in srgb, var(--ii-danger) 8%, transparent);
		color: var(--ii-danger);
		font-size: var(--ii-text-small, 0.8125rem);
	}

	.cd-error-dismiss {
		background: none;
		border: none;
		color: var(--ii-danger);
		cursor: pointer;
		font-size: 1.2em;
		padding: 0 4px;
		line-height: 1;
	}

	/* Meta bar */
	.cd-meta-bar {
		display: flex;
		align-items: center;
		gap: var(--ii-space-inline-sm, 10px);
		padding: var(--ii-space-stack-xs, 8px) var(--ii-space-inline-lg, 24px);
		border-bottom: 1px solid var(--ii-border-subtle);
		font-size: var(--ii-text-small, 0.8125rem);
		color: var(--ii-text-muted);
		flex-wrap: wrap;
	}

	.cd-type {
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		font-size: var(--ii-text-label, 0.75rem);
	}

	.cd-lang {
		font-weight: 600;
		color: var(--ii-text-secondary);
	}

	.cd-date, .cd-author {
		color: var(--ii-text-muted);
	}

	.cd-approved {
		color: var(--ii-success);
	}

	/* Page content */
	.cd-page {
		padding: var(--ii-space-stack-lg, 24px) var(--ii-space-inline-lg, 24px);
		max-width: 820px;
	}

	.cd-generating {
		display: flex;
		align-items: center;
		gap: 8px;
		padding: var(--ii-space-stack-xl, 40px) 0;
		color: var(--ii-info);
		font-size: var(--ii-text-body, 0.9375rem);
	}

	.cd-spinner {
		display: inline-block;
		width: 16px;
		height: 16px;
		border: 2px solid color-mix(in srgb, var(--ii-info) 30%, transparent);
		border-top-color: var(--ii-info);
		border-radius: 50%;
		animation: cd-spin 0.8s linear infinite;
	}

	@keyframes cd-spin {
		to { transform: rotate(360deg); }
	}

	/* Rendered markdown body */
	.cd-body {
		line-height: var(--ii-leading-body, 1.65);
		color: var(--ii-text-primary);
		font-size: var(--ii-text-body, 0.9375rem);
	}

	.cd-body :global(h1) {
		font-size: var(--ii-text-h2, 1.75rem);
		font-weight: 700;
		margin: var(--ii-space-stack-lg, 28px) 0 var(--ii-space-stack-sm, 12px);
		color: var(--ii-text-primary);
	}

	.cd-body :global(h2) {
		font-size: var(--ii-text-h3, 1.375rem);
		font-weight: 600;
		margin: var(--ii-space-stack-md, 20px) 0 var(--ii-space-stack-xs, 8px);
		color: var(--ii-text-primary);
	}

	.cd-body :global(h3) {
		font-size: var(--ii-text-h4, 1.125rem);
		font-weight: 600;
		margin: var(--ii-space-stack-sm, 16px) 0 var(--ii-space-stack-2xs, 4px);
		color: var(--ii-text-primary);
	}

	.cd-body :global(p) {
		margin: 0 0 var(--ii-space-stack-sm, 12px);
	}

	.cd-body :global(ul) {
		margin: 0 0 var(--ii-space-stack-sm, 12px);
		padding-left: var(--ii-space-inline-lg, 24px);
	}

	.cd-body :global(ol) {
		margin: 0 0 var(--ii-space-stack-sm, 12px);
		padding-left: var(--ii-space-inline-lg, 24px);
	}

	.cd-body :global(li) {
		margin: 0 0 var(--ii-space-stack-2xs, 4px);
	}

	.cd-body :global(code) {
		font-family: var(--ii-font-mono);
		font-size: var(--ii-text-mono, 0.875rem);
		padding: 1px 5px;
		border-radius: 4px;
		background: var(--ii-surface-alt);
	}

	.cd-body :global(table) {
		width: 100%;
		border-collapse: collapse;
		margin: 1rem 0;
		font-size: 0.875rem;
	}

	.cd-body :global(th),
	.cd-body :global(td) {
		border: 1px solid var(--ii-border-subtle, var(--border));
		padding: 0.5rem 0.75rem;
		text-align: left;
	}

	.cd-body :global(th) {
		background: var(--ii-surface-alt, var(--muted));
		font-weight: 600;
	}

	.cd-body :global(hr) {
		border: none;
		border-top: 1px solid var(--ii-border-subtle, var(--border));
		margin: 1.5rem 0;
	}

	.cd-body :global(blockquote) {
		border-left: 3px solid var(--ii-border-subtle, var(--border));
		margin: 0 0 var(--ii-space-stack-sm, 12px);
		padding-left: var(--ii-space-inline-md, 16px);
		color: var(--ii-text-secondary);
	}

	.cd-body :global(.rw-empty) {
		color: var(--ii-text-muted);
		font-style: italic;
	}

	/* Content data section */
	.cd-data-section {
		margin-top: var(--ii-space-stack-lg, 28px);
		border: 1px solid var(--ii-border-subtle);
		border-radius: var(--ii-radius-sm, 8px);
		overflow: hidden;
	}

	.cd-data-toggle {
		padding: var(--ii-space-stack-xs, 10px) var(--ii-space-inline-md, 16px);
		font-size: var(--ii-text-small, 0.8125rem);
		font-weight: 600;
		color: var(--ii-text-secondary);
		cursor: pointer;
		background: var(--ii-surface-alt);
		border-bottom: 1px solid var(--ii-border-subtle);
	}

	.cd-data-grid {
		display: grid;
		grid-template-columns: minmax(120px, auto) 1fr;
		gap: 0;
	}

	.cd-data-row {
		display: contents;
	}

	.cd-data-key {
		padding: var(--ii-space-stack-2xs, 4px) var(--ii-space-inline-md, 16px);
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 600;
		color: var(--ii-text-secondary);
		border-bottom: 1px solid var(--ii-border-subtle);
		word-break: break-word;
	}

	.cd-data-val {
		padding: var(--ii-space-stack-2xs, 4px) var(--ii-space-inline-md, 16px);
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-primary);
		border-bottom: 1px solid var(--ii-border-subtle);
		word-break: break-word;
	}

</style>
