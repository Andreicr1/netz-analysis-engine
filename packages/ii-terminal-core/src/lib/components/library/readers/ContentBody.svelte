<!--
  ContentBody — standalone reader for `wealth_content` documents
  (Investment Outlooks, Flash Reports, Manager Spotlights).

  Phase 0 of the Wealth Library refactor: extracted from
  routes/(app)/content/[id]/+page.svelte so the same body can be
  embedded inside the future LibraryPreviewPane (Library shell,
  Phase 3) and any other host that has token context.

  Contract
  --------
  * Strictly props: only `id`. Token comes from "netz:getToken".
  * Optional `netz:content-actor` context exposes actor info for
    the approval UI; LibraryPreviewPane (read-only host) leaves it
    empty so the Approve button never renders.
  * Self-contained client fetch via `/content/{id}`.
-->
<script lang="ts">
	import { getContext } from "svelte";
	import {
		Button,
		ConsequenceDialog,
		StatusBadge,
		formatDateTime,
	} from "@investintell/ui";
	import type { ConsequenceDialogPayload } from "@investintell/ui";
	import { PanelEmptyState, PanelErrorState } from "@investintell/ui/runtime";
	import { ForbiddenError } from "@investintell/ui/utils";
	import { createClientApiClient } from "../../../api/client";
	import type { ContentFull } from "../../../types/content";
	import { contentTypeColor, contentTypeLabel } from "../../../types/content";
	import { flattenObject, renderMarkdown } from "../../../utils/render-markdown";

	let { id }: { id: string } = $props();

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	interface ActorContext {
		actorId: string | null;
		actorRole: string | null;
	}
	const actorCtx = getContext<ActorContext | null>("netz:content-actor") ?? null;
	const actorId = actorCtx?.actorId ?? null;
	const actorRole = actorCtx?.actorRole ?? null;

	// ── Self-managed content state ───────────────────────────────────
	let content = $state<ContentFull | null>(null);
	let loading = $state(true);
	let loadError = $state<string | null>(null);

	async function loadContent() {
		loading = true;
		loadError = null;
		try {
			const api = createClientApiClient(getToken);
			content = await api.get<ContentFull>(`/content/${id}`);
		} catch (err: unknown) {
			loadError =
				err instanceof Error ? err.message : "Failed to load content.";
			content = null;
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		void id;
		void loadContent();
	});

	// ── Approval logic ───────────────────────────────────────────────
	const IC_ROLES = ["admin", "super_admin", "investment_team"];
	let canApprove = $derived(
		content !== null &&
			(content.status === "draft" || content.status === "review") &&
			actorRole !== null &&
			IC_ROLES.includes(actorRole) &&
			actorId !== content.created_by,
	);
	let isSelfAuthored = $derived(
		content !== null &&
			actorId !== null &&
			content.created_by === actorId,
	);

	let approveDialogOpen = $state(false);
	let actionError = $state<string | null>(null);

	async function handleApprove(payload: ConsequenceDialogPayload) {
		if (!content) return;
		try {
			const api = createClientApiClient(getToken);
			await api.post(`/content/${content.id}/approve`, {
				rationale: payload.rationale,
			});
			approveDialogOpen = false;
			await loadContent();
		} catch (e) {
			if (e instanceof ForbiddenError) {
				actionError =
					"Cannot approve your own content. Another team member must approve.";
			} else {
				actionError = e instanceof Error ? e.message : "Approval failed";
			}
			approveDialogOpen = false;
		}
	}

	// ── Download ─────────────────────────────────────────────────────
	let downloading = $state(false);

	function canDownload(): boolean {
		return (
			content !== null &&
			(content.status === "approved" || content.status === "published")
		);
	}

	async function downloadPdf() {
		if (!content) return;
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
			actionError = e instanceof Error ? e.message : "Download failed";
		} finally {
			downloading = false;
		}
	}

	let hasContentData = $derived(
		content !== null &&
			content.content_data !== null &&
			content.content_data !== undefined &&
			Object.keys(content.content_data).length > 0,
	);
</script>

{#if loading && content === null}
	<PanelEmptyState
		title="Loading content"
		message="Fetching the document from the server..."
	/>
{:else if loadError}
	<PanelErrorState
		title="Unable to load content"
		message={loadError}
		onRetry={loadContent}
	/>
{:else if content === null}
	<PanelEmptyState
		title="No content available"
		message="This content is not available at the moment."
	/>
{:else}
	<!-- ── Action bar (no PageHeader / no breadcrumbs) ─────────── -->
	<div class="cd-actions-bar">
		{#if canApprove}
			<Button
				size="sm"
				variant="outline"
				onclick={() => (approveDialogOpen = true)}
			>
				Approve
			</Button>
		{:else if (content.status === "draft" || content.status === "review") && isSelfAuthored}
			<span class="cd-self-hint" title="Cannot approve your own content">
				<Button size="sm" variant="outline" disabled>Approve</Button>
			</span>
		{/if}
		{#if canDownload()}
			<Button size="sm" onclick={downloadPdf} disabled={downloading}>
				{downloading ? "Downloading..." : "Download PDF"}
			</Button>
		{/if}
	</div>

	{#if actionError}
		<div class="cd-error">
			<span>{actionError}</span>
			<button
				class="cd-error-dismiss"
				onclick={() => (actionError = null)}
				type="button"
				aria-label="Dismiss error"
			>
				&times;
			</button>
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
				<!-- renderMarkdown applies DOMPurify with strict ALLOWED_TAGS/ATTR allowlist.
				     Backend also sanitizes via nh3 at the persist boundary. Two-layer defense. -->
				<!-- eslint-disable-next-line svelte/no-at-html-tags -->
				{@html renderMarkdown(content.content_md)}
			</div>
		{/if}

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
	.cd-actions-bar {
		display: flex;
		gap: var(--ii-space-inline-xs, 6px);
		padding: var(--ii-space-stack-xs, 8px) var(--ii-space-inline-lg, 24px);
		border-bottom: 1px solid var(--ii-border-subtle);
		background: var(--ii-surface-elevated);
	}

	.cd-self-hint { cursor: not-allowed; }

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

	.cd-date,
	.cd-author { color: var(--ii-text-muted); }

	.cd-approved { color: var(--ii-success); }

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

	@keyframes cd-spin { to { transform: rotate(360deg); } }

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

	.cd-body :global(p) { margin: 0 0 var(--ii-space-stack-sm, 12px); }

	.cd-body :global(ul),
	.cd-body :global(ol) {
		margin: 0 0 var(--ii-space-stack-sm, 12px);
		padding-left: var(--ii-space-inline-lg, 24px);
	}

	.cd-body :global(li) { margin: 0 0 var(--ii-space-stack-2xs, 4px); }

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
		border: 1px solid var(--ii-border-subtle);
		padding: 0.5rem 0.75rem;
		text-align: left;
	}

	.cd-body :global(th) {
		background: var(--ii-surface-alt);
		font-weight: 600;
	}

	.cd-body :global(hr) {
		border: none;
		border-top: 1px solid var(--ii-border-subtle);
		margin: 1.5rem 0;
	}

	.cd-body :global(blockquote) {
		border-left: 3px solid var(--ii-border-subtle);
		margin: 0 0 var(--ii-space-stack-sm, 12px);
		padding-left: var(--ii-space-inline-md, 16px);
		color: var(--ii-text-secondary);
	}

	.cd-body :global(.rw-empty) {
		color: var(--ii-text-muted);
		font-style: italic;
	}

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

	.cd-data-row { display: contents; }

	.cd-data-key,
	.cd-data-val {
		padding: var(--ii-space-stack-2xs, 4px) var(--ii-space-inline-md, 16px);
		font-size: var(--ii-text-label, 0.75rem);
		border-bottom: 1px solid var(--ii-border-subtle);
		word-break: break-word;
	}

	.cd-data-key {
		font-weight: 600;
		color: var(--ii-text-secondary);
	}

	.cd-data-val { color: var(--ii-text-primary); }
</style>
