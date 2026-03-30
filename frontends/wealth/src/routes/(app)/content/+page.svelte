<!--
  Content — Flash Reports, Investment Outlooks, Manager Spotlights.
  Tabbed grid view with generate, approve, download actions.
  Polls for status updates after generation triggers.
  Self-approval blocked: approve button disabled when actorId === created_by.
-->
<script lang="ts">
	import { getContext, onDestroy } from "svelte";
	import { invalidateAll } from "$app/navigation";
	import {
		PageHeader, Button, StatusBadge, EmptyState, ConsequenceDialog,
		formatDateTime,
	} from "@investintell/ui";
	import { ForbiddenError } from "@investintell/ui/utils";
	import type { ConsequenceDialogPayload } from "@investintell/ui";
	import { createClientApiClient } from "$lib/api/client";
	import type { PageData } from "./$types";
	import type { ContentSummary } from "$lib/types/content";
	import { contentTypeLabel, contentTypeColor } from "$lib/types/content";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let { data }: { data: PageData } = $props();

	let content = $derived((data.content ?? []) as ContentSummary[]);
	let actorId = $derived((data.actorId ?? null) as string | null);

	type FundSummary = { fund_id: string; name: string; manager_name?: string | null };
	let funds = $derived((data.funds ?? []) as FundSummary[]);

	// ── Tab filter ────────────────────────────────────────────────────────

	type TabKey = "all" | "investment_outlook" | "flash_report" | "manager_spotlight";
	let activeTab = $state<TabKey>("all");

	let filtered = $derived.by(() => {
		if (activeTab === "all") return content;
		return content.filter((c) => c.content_type === activeTab);
	});

	let tabCounts = $derived({
		all: content.length,
		investment_outlook: content.filter((c) => c.content_type === "investment_outlook").length,
		flash_report: content.filter((c) => c.content_type === "flash_report").length,
		manager_spotlight: content.filter((c) => c.content_type === "manager_spotlight").length,
	});

	// ── Polling — refresh list while any item is generating ──────────────

	let pollTimer: ReturnType<typeof setInterval> | null = null;

	let hasGenerating = $derived(content.some((c) => c.status === "draft"));

	$effect(() => {
		if (hasGenerating && !pollTimer) {
			pollTimer = setInterval(() => { invalidateAll(); }, 5000);
		} else if (!hasGenerating && pollTimer) {
			clearInterval(pollTimer);
			pollTimer = null;
		}
	});

	onDestroy(() => {
		if (pollTimer) clearInterval(pollTimer);
	});

	// ── Generate actions ──────────────────────────────────────────────────

	let generating = $state(false);
	let error = $state<string | null>(null);

	async function generateContent(endpoint: string, params?: Record<string, string>) {
		generating = true;
		error = null;
		try {
			const api = createClientApiClient(getToken);
			const qs = params ? "?" + new URLSearchParams(params).toString() : "";
			await api.post(`/content/${endpoint}${qs}`, {});
			await invalidateAll();
		} catch (e) {
			if (e instanceof Error && e.message.includes("409")) {
				error = "A flash report was already generated recently. Please wait before generating another.";
			} else {
				error = e instanceof Error ? e.message : "Generation failed";
			}
		} finally {
			generating = false;
		}
	}

	// ── Retry failed content ────────────────────────────────────────────

	async function retryContent(item: ContentSummary) {
		if (item.content_type === "manager_spotlight") {
			// Re-open fund picker since we don't have instrument_id in the summary
			requestSpotlight();
			return;
		}
		const endpointMap: Record<string, string> = {
			investment_outlook: "outlooks",
			flash_report: "flash-reports",
		};
		const endpoint = endpointMap[item.content_type];
		if (endpoint) await generateContent(endpoint);
	}

	// ── Spotlight fund picker ────────────────────────────────────────────

	let spotlightDialogOpen = $state(false);
	let spotlightFundId = $state("");

	function requestSpotlight() {
		spotlightFundId = funds[0]?.fund_id ?? "";
		spotlightDialogOpen = true;
	}

	async function handleSpotlightConfirm(_payload: ConsequenceDialogPayload) {
		if (!spotlightFundId) return;
		spotlightDialogOpen = false;
		await generateContent("spotlights", { instrument_id: spotlightFundId });
	}

	// ── Approve ───────────────────────────────────────────────────────────

	let approveDialogOpen = $state(false);
	let approveTargetId = $state<string | null>(null);
	let approveTargetTitle = $state("");

	function requestApprove(item: ContentSummary) {
		approveTargetId = item.id;
		approveTargetTitle = item.title ?? contentTypeLabel(item.content_type);
		approveDialogOpen = true;
	}

	async function handleApprove(_payload: ConsequenceDialogPayload) {
		if (!approveTargetId) return;
		try {
			const api = createClientApiClient(getToken);
			await api.post(`/content/${approveTargetId}/approve`, {});
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

	let downloadingId = $state<string | null>(null);

	async function downloadPdf(item: ContentSummary) {
		downloadingId = item.id;
		try {
			const api = createClientApiClient(getToken);
			const blob = await api.getBlob(`/content/${item.id}/download`);
			const url = URL.createObjectURL(blob);
			const a = document.createElement("a");
			a.href = url;
			a.download = `${item.content_type}_${item.language}.pdf`;
			a.click();
			URL.revokeObjectURL(url);
		} catch (e) {
			error = e instanceof Error ? e.message : "Download failed";
		} finally {
			downloadingId = null;
		}
	}

	// ── Helpers ───────────────────────────────────────────────────────────

	function isApprovable(item: ContentSummary): boolean {
		return item.status === "draft" || item.status === "review";
	}

	function isSelfAuthored(item: ContentSummary): boolean {
		return actorId !== null && item.created_by === actorId;
	}

	function canApprove(item: ContentSummary): boolean {
		return isApprovable(item) && !isSelfAuthored(item);
	}

	function canDownload(item: ContentSummary): boolean {
		return item.status === "approved" || item.status === "published";
	}
</script>

<PageHeader title="Content">
	{#snippet actions()}
		<div class="ct-actions">
			<Button size="sm" variant="outline" onclick={() => generateContent("outlooks")} disabled={generating}>
				Outlook
			</Button>
			<Button size="sm" variant="outline" onclick={() => generateContent("flash-reports")} disabled={generating}>
				Flash Report
			</Button>
			<Button size="sm" variant="outline" onclick={requestSpotlight} disabled={generating || funds.length === 0}>
				Spotlight
			</Button>
		</div>
	{/snippet}
</PageHeader>

{#if error}
	<div class="ct-error">
		<span>{error}</span>
		<button class="ct-error-dismiss" onclick={() => error = null} type="button">&times;</button>
	</div>
{/if}

<!-- Tabs -->
<div class="ct-tabs">
	{#each ([["all", "All"], ["investment_outlook", "Outlooks"], ["flash_report", "Flash Reports"], ["manager_spotlight", "Spotlights"]] as [TabKey, string][]) as [key, label] (key)}
		<button
			class="ct-tab"
			class:ct-tab--active={activeTab === key}
			onclick={() => activeTab = key}
		>
			{label}
			<span class="ct-tab-count">{tabCounts[key]}</span>
		</button>
	{/each}
</div>

<div class="ct-page">
	{#if filtered.length === 0}
		<EmptyState title="No content" message="Generate an outlook or flash report to start." />
	{:else}
		<div class="ct-grid">
			{#each filtered as item (item.id)}
				<div class="ct-card">
					<div class="ct-card-header">
						<span class="ct-type" style:color={contentTypeColor(item.content_type)}>
							{contentTypeLabel(item.content_type)}
						</span>
						<StatusBadge status={item.status} />
					</div>

					<h3 class="ct-title">{item.title ?? contentTypeLabel(item.content_type)}</h3>

					<div class="ct-meta">
						<span class="ct-lang">{item.language.toUpperCase()}</span>
						<span class="ct-date">{formatDateTime(item.created_at)}</span>
					</div>

					{#if item.created_by}
						<div class="ct-created-by">by {item.created_by}</div>
					{/if}

					{#if item.approved_at}
						<div class="ct-approved">
							Approved {formatDateTime(item.approved_at)}
							{#if item.approved_by}
								by {item.approved_by}
							{/if}
						</div>
					{/if}

					{#if item.status === "draft"}
						<div class="ct-generating">
							<span class="ct-spinner"></span>
							Generating&hellip;
						</div>
					{/if}

					<div class="ct-card-actions">
						{#if canApprove(item)}
							<Button size="sm" variant="outline" onclick={() => requestApprove(item)}>Approve</Button>
						{:else if isApprovable(item) && isSelfAuthored(item)}
							<span class="ct-self-approve-hint" title="Cannot approve your own content. Another team member must approve.">
								<Button size="sm" variant="outline" disabled>Approve</Button>
							</span>
						{/if}
						{#if canDownload(item)}
							<Button size="sm" onclick={() => downloadPdf(item)} disabled={downloadingId === item.id}>
								{downloadingId === item.id ? "Downloading\u2026" : "Download PDF"}
							</Button>
						{/if}
						{#if item.status === "failed"}
							<Button size="sm" variant="outline" onclick={() => retryContent(item)}>Retry</Button>
						{/if}
					</div>
				</div>
			{/each}
		</div>
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
	metadata={[{ label: "Content", value: approveTargetTitle }]}
	onConfirm={handleApprove}
/>

<!-- Spotlight fund picker dialog -->
<ConsequenceDialog
	bind:open={spotlightDialogOpen}
	title="Generate Manager Spotlight"
	impactSummary="A Manager Spotlight report will be generated for the selected fund."
	requireRationale={false}
	confirmLabel="Generate"
	metadata={[{ label: "Fund", value: funds.find((f) => f.fund_id === spotlightFundId)?.name ?? "\u2014" }]}
	onConfirm={handleSpotlightConfirm}
>
	<div class="ct-spotlight-picker">
		<label class="ct-spotlight-label" for="spotlight-fund-select">Select Fund</label>
		<select id="spotlight-fund-select" class="ct-spotlight-select" bind:value={spotlightFundId}>
			{#each funds as fund (fund.fund_id)}
				<option value={fund.fund_id}>
					{fund.name}{fund.manager_name ? ` \u2014 ${fund.manager_name}` : ""}
				</option>
			{/each}
		</select>
	</div>
</ConsequenceDialog>

<style>
	.ct-actions {
		display: flex;
		gap: var(--ii-space-inline-xs, 6px);
	}

	.ct-error {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--ii-space-stack-xs, 8px) var(--ii-space-inline-lg, 24px);
		background: color-mix(in srgb, var(--ii-danger) 8%, transparent);
		color: var(--ii-danger);
		font-size: var(--ii-text-small, 0.8125rem);
	}

	.ct-error-dismiss {
		background: none;
		border: none;
		color: var(--ii-danger);
		cursor: pointer;
		font-size: 1.2em;
		padding: 0 4px;
		line-height: 1;
	}

	/* Tabs */
	.ct-tabs {
		display: flex;
		gap: var(--ii-space-inline-2xs, 4px);
		padding: var(--ii-space-stack-xs, 8px) var(--ii-space-inline-lg, 24px);
		border-bottom: 1px solid var(--ii-border-subtle);
	}

	.ct-tab {
		display: flex;
		align-items: center;
		gap: 4px;
		padding: var(--ii-space-stack-2xs, 6px) var(--ii-space-inline-md, 14px);
		border: 1px solid transparent;
		border-radius: var(--ii-radius-sm, 8px);
		background: transparent;
		color: var(--ii-text-secondary);
		font-size: var(--ii-text-small, 0.8125rem);
		font-weight: 500;
		font-family: var(--ii-font-sans);
		cursor: pointer;
		transition: background-color 120ms ease;
	}

	.ct-tab:hover { background: var(--ii-surface-alt); }

	.ct-tab--active {
		background: color-mix(in srgb, var(--ii-brand-primary) 10%, transparent);
		color: var(--ii-brand-primary);
		font-weight: 600;
	}

	.ct-tab-count {
		font-size: var(--ii-text-label, 0.75rem);
		font-variant-numeric: tabular-nums;
		opacity: 0.7;
	}

	/* Grid */
	.ct-page {
		padding: var(--ii-space-stack-md, 16px) var(--ii-space-inline-lg, 24px);
	}

	.ct-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
		gap: var(--ii-space-stack-sm, 12px);
	}

	.ct-card {
		display: flex;
		flex-direction: column;
		border: 1px solid var(--ii-border-subtle);
		border-radius: var(--ii-radius-md, 12px);
		background: var(--ii-surface-elevated);
		overflow: hidden;
	}

	.ct-card-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: var(--ii-space-stack-xs, 10px) var(--ii-space-inline-md, 16px);
		border-bottom: 1px solid var(--ii-border-subtle);
		background: var(--ii-surface-alt);
	}

	.ct-type {
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.ct-title {
		padding: var(--ii-space-stack-sm, 12px) var(--ii-space-inline-md, 16px) 0;
		font-size: var(--ii-text-body, 0.9375rem);
		font-weight: 600;
		color: var(--ii-text-primary);
		line-height: 1.4;
	}

	.ct-meta {
		display: flex;
		gap: var(--ii-space-inline-sm, 8px);
		padding: var(--ii-space-stack-2xs, 4px) var(--ii-space-inline-md, 16px);
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-muted);
	}

	.ct-lang {
		font-weight: 600;
		color: var(--ii-text-secondary);
	}

	.ct-created-by {
		padding: 0 var(--ii-space-inline-md, 16px);
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-muted);
	}

	.ct-approved {
		padding: var(--ii-space-stack-2xs, 4px) var(--ii-space-inline-md, 16px);
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-success);
	}

	.ct-generating {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: var(--ii-space-stack-2xs, 6px) var(--ii-space-inline-md, 16px);
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-info);
	}

	.ct-spinner {
		display: inline-block;
		width: 12px;
		height: 12px;
		border: 2px solid color-mix(in srgb, var(--ii-info) 30%, transparent);
		border-top-color: var(--ii-info);
		border-radius: 50%;
		animation: ct-spin 0.8s linear infinite;
	}

	@keyframes ct-spin {
		to { transform: rotate(360deg); }
	}

	.ct-self-approve-hint {
		cursor: not-allowed;
	}

	.ct-card-actions {
		display: flex;
		gap: var(--ii-space-inline-xs, 6px);
		padding: var(--ii-space-stack-sm, 12px) var(--ii-space-inline-md, 16px);
		margin-top: auto;
		border-top: 1px solid var(--ii-border-subtle);
	}

	/* Spotlight picker */
	.ct-spotlight-picker {
		display: flex;
		flex-direction: column;
		gap: 6px;
		padding: var(--ii-space-stack-xs, 8px) 0;
	}

	.ct-spotlight-label {
		font-size: var(--ii-text-small, 0.8125rem);
		font-weight: 500;
		color: var(--ii-text-secondary);
	}

	.ct-spotlight-select {
		height: var(--ii-space-control-height-sm, 36px);
		padding: 0 var(--ii-space-inline-sm, 10px);
		border: 1px solid var(--ii-border);
		border-radius: var(--ii-radius-sm, 8px);
		background: var(--ii-surface-elevated);
		color: var(--ii-text-primary);
		font-size: var(--ii-text-small, 0.8125rem);
		font-family: var(--ii-font-sans);
	}
</style>
