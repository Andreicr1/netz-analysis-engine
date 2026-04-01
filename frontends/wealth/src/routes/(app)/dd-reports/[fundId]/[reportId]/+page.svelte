<!--
  DD Report Reading Workbench — 8-chapter document viewer with approval workflow.
  Layout: chapter nav (left) + content (center) + action bar (top).
  SSE: generation progress via /dd-reports/{reportId}/stream.
  Approval: ConsequenceDialog with mandatory rationale for audit trail.
-->
<script lang="ts">
	import { getContext, onMount, onDestroy } from "svelte";
	import { invalidateAll } from "$app/navigation";
	import {
		PageHeader, StatusBadge, ConsequenceDialog,
		formatDateTime, formatPercent,
		createSSEStream,
	} from "@investintell/ui";
	import type { ConsequenceDialogPayload } from "@investintell/ui";
	import { Button } from "@investintell/ui/components/ui/button";
	import { createClientApiClient } from "$lib/api/client";
	import type { PageData } from "./$types";
	import type { DDReportFull, DDChapter, DDReportStatus, DecisionAnchor, AuditEvent } from "$lib/types/dd-report";
	import { chapterTitle, anchorLabel, anchorColor, confidenceColor } from "$lib/types/dd-report";
	import { renderMarkdown, flattenObject } from "$lib/utils/render-markdown";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let { data }: { data: PageData } = $props();

	let report = $derived(data.report as DDReportFull);
	let fundId = $derived(data.fundId as string);
	let reportId = $derived(data.reportId as string);
	let actorId = $derived(data.actorId as string | null);
	let actorRole = $derived(data.actorRole as string | null);

	// ── Chapter state ─────────────────────────────────────────────────────

	let chapters = $derived(
		(report.chapters ?? []).toSorted((a, b) => a.chapter_order - b.chapter_order) as DDChapter[]
	);
	let activeChapterTag = $state<string | null>(null);
	let activeChapter = $derived(
		chapters.find((c) => c.chapter_tag === activeChapterTag) ?? chapters[0] ?? null
	);

	// Initialize on first render
	$effect(() => {
		if (!activeChapterTag && chapters.length > 0) {
			activeChapterTag = chapters[0]!.chapter_tag;
		}
	});

	// ── Approval logic ────────────────────────────────────────────────────

	const IC_ROLES = ["admin", "super_admin", "investment_team"];
	let canApprove = $derived(
		report.status === "pending_approval" &&
		actorRole !== null &&
		IC_ROLES.includes(actorRole) &&
		actorId !== report.created_by
	);

	let approveDialogOpen = $state(false);
	let rejectDialogOpen = $state(false);

	// Override detection (BL-17)
	let isApproveOverride = $derived(
		report.decision_anchor === "REJECT" || report.decision_anchor === "CONDITIONAL"
	);
	let isRejectOverride = $derived(report.decision_anchor === "APPROVE");

	async function handleApprove(payload: ConsequenceDialogPayload) {
		const api = createClientApiClient(getToken);
		await api.post(`/dd-reports/${reportId}/approve`, { rationale: payload.rationale });
		approveDialogOpen = false;
		await invalidateAll();
	}

	async function handleReject(payload: ConsequenceDialogPayload) {
		const api = createClientApiClient(getToken);
		await api.post(`/dd-reports/${reportId}/reject`, { reason: payload.rationale });
		rejectDialogOpen = false;
		await invalidateAll();
	}

	// ── SSE generation progress ───────────────────────────────────────────

	interface GenerationEvent {
		type: string;
		chapter_tag?: string;
		order?: number;
		status?: string;
		confidence_score?: number;
		decision_anchor?: string;
		error?: string;
	}

	let generationEvents = $state<GenerationEvent[]>([]);
	let sseConnection: ReturnType<typeof createSSEStream<GenerationEvent>> | null = null;

	const apiBase = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000/api/v1";

	function startSSE() {
		if (report.status !== "generating") return;
		sseConnection?.disconnect();

		sseConnection = createSSEStream<GenerationEvent>({
			url: `${apiBase}/dd-reports/${reportId}/stream`,
			getToken,
			onEvent(event) {
				generationEvents = [...generationEvents, event];
				if (event.type === "report_completed" || event.type === "report_failed") {
					invalidateAll();
				}
			},
		});
		sseConnection.connect();
	}

	onMount(() => {
		startSSE();
	});

	onDestroy(() => {
		sseConnection?.disconnect();
	});

	// ── Regenerate ────────────────────────────────────────────────────────

	// ── Fact sheet download ──────────────────────────────────────────────

	let downloading = $state(false);

	let canDownload = $derived(
		["completed", "pending_approval", "approved", "published"].includes(report.status)
	);

	async function downloadFactSheet() {
		downloading = true;
		try {
			const token = await getToken();
			const res = await fetch(`/api/v1/fact-sheets/dd-reports/${reportId}/download?language=pt`, {
				headers: { Authorization: `Bearer ${token}` },
			});
			if (!res.ok) throw new Error(`Download failed: ${res.status}`);
			const blob = await res.blob();
			const url = URL.createObjectURL(blob);
			const a = document.createElement("a");
			a.href = url;
			a.download = `dd_report_${fundId}_pt.pdf`;
			a.click();
			URL.revokeObjectURL(url);
		} catch (e) {
			console.error("Fact sheet download failed:", e);
		} finally {
			downloading = false;
		}
	}

	let regenerating = $state(false);

	async function regenerate() {
		regenerating = true;
		try {
			const api = createClientApiClient(getToken);
			await api.post(`/dd-reports/${reportId}/regenerate`, {});
			generationEvents = [];
			await invalidateAll();
			startSSE();
		} finally {
			regenerating = false;
		}
	}

	// ── Audit trail ──────────────────────────────────────────────────────

	let auditTrailOpen = $state(false);
	let auditEvents = $state<AuditEvent[]>([]);
	let auditLoading = $state(false);

	async function loadAuditTrail() {
		if (auditEvents.length > 0) return;
		auditLoading = true;
		try {
			const api = createClientApiClient(getToken);
			auditEvents = await api.get<AuditEvent[]>(`/dd-reports/${reportId}/audit-trail`);
		} catch {
			auditEvents = [];
		} finally {
			auditLoading = false;
		}
	}

	function handleAuditToggle() {
		auditTrailOpen = !auditTrailOpen;
		if (auditTrailOpen) loadAuditTrail();
	}

	function auditActionLabel(action: string): string {
		switch (action) {
			case "CREATE": return "Created";
			case "UPDATE": return "Updated";
			case "APPROVE": return "Approved";
			case "REJECT": return "Rejected";
			case "REGENERATE": return "Regenerated";
			default: return action;
		}
	}

	// renderMarkdown + flattenObject imported from $lib/utils/render-markdown
</script>

<!-- ═══════════════════════════════════════════════════════════════════════ -->
<!-- ACTION BAR                                                             -->
<!-- ═══════════════════════════════════════════════════════════════════════ -->
<PageHeader
	title="DD Report v{report.version}"
	breadcrumbs={[
		{ label: "DD Reports", href: "/dd-reports" },
		{ label: fundId, href: `/dd-reports/${fundId}` },
		{ label: `v${report.version}` },
	]}
>
	{#snippet actions()}
		<div class="action-bar">
			<StatusBadge status={report.status} />

			{#if report.confidence_score !== null}
				<span class="action-confidence" style:color={confidenceColor(report.confidence_score)}>
					{report.confidence_score.toFixed(1)}%
				</span>
			{/if}

			{#if report.decision_anchor}
				<span class="action-anchor" style:color={anchorColor(report.decision_anchor)}>
					{anchorLabel(report.decision_anchor)}
				</span>
			{/if}

			{#if canApprove}
				<Button size="sm" onclick={() => approveDialogOpen = true}>Approve</Button>
				<Button size="sm" variant="destructive" onclick={() => rejectDialogOpen = true}>Reject</Button>
			{/if}

			{#if report.status === "draft" || report.status === "rejected" || report.status === "failed"}
				<Button size="sm" variant="outline" onclick={regenerate} disabled={regenerating}>
					{regenerating ? "Regenerating…" : "Regenerate"}
				</Button>
			{/if}

			{#if canDownload}
				<Button size="sm" variant="outline" onclick={downloadFactSheet} disabled={downloading}>
					{downloading ? "Downloading…" : "Download PDF"}
				</Button>
			{/if}
		</div>
	{/snippet}
</PageHeader>

<!-- ═══════════════════════════════════════════════════════════════════════ -->
<!-- SSE GENERATION PROGRESS                                                -->
<!-- ═══════════════════════════════════════════════════════════════════════ -->
{#if report.status === "generating" || generationEvents.length > 0}
	<div class="sse-banner">
		<span class="sse-dot"></span>
		<span class="sse-text">
			{#if generationEvents.length === 0}
				Generating report…
			{:else}
				{@const last = generationEvents[generationEvents.length - 1]!}
				{#if last.type === "chapter_completed"}
					Chapter {last.order}: {chapterTitle(last.chapter_tag ?? "")} completed
				{:else if last.type === "chapter_started"}
					Generating chapter {last.order}: {chapterTitle(last.chapter_tag ?? "")}…
				{:else if last.type === "critic_started"}
					Critic reviewing chapter {last.order}…
				{:else if last.type === "report_completed"}
					Report generation complete
				{:else if last.type === "report_failed"}
					Generation failed: {last.error ?? "Unknown error"}
				{:else}
					{last.type}
				{/if}
			{/if}
		</span>
	</div>
{/if}

<!-- ═══════════════════════════════════════════════════════════════════════ -->
<!-- READING WORKBENCH: chapter nav + content                               -->
<!-- ═══════════════════════════════════════════════════════════════════════ -->
<div class="workbench">
	<!-- Chapter navigation sidebar -->
	<nav class="chapter-nav" aria-label="Chapters">
		{#each chapters as chapter (chapter.id)}
			<button
				class="chapter-nav-item"
				class:active={activeChapterTag === chapter.chapter_tag}
				onclick={() => activeChapterTag = chapter.chapter_tag}
			>
				<span class="chapter-order">{chapter.chapter_order}</span>
				<span class="chapter-tag">{chapterTitle(chapter.chapter_tag)}</span>
				{#if chapter.critic_status === "escalated"}
					<span class="chapter-critic-dot chapter-critic-dot--escalated" title="Escalated"></span>
				{:else if chapter.critic_status === "accepted"}
					<span class="chapter-critic-dot chapter-critic-dot--accepted" title="Accepted"></span>
				{/if}
			</button>
		{/each}
	</nav>

	<!-- Chapter content -->
	<article class="chapter-content">
		{#if activeChapter}
			<header class="chapter-header">
				<h2 class="chapter-title">{chapterTitle(activeChapter.chapter_tag)}</h2>
				{#if activeChapter.generated_at}
					<span class="chapter-generated">
						AI-generated on {formatDateTime(activeChapter.generated_at)}
					</span>
				{/if}
				{#if activeChapter.critic_status !== "pending"}
					<span class="chapter-critic">
						Critic: {activeChapter.critic_status} ({activeChapter.critic_iterations} iteration{activeChapter.critic_iterations !== 1 ? "s" : ""})
					</span>
				{/if}
			</header>

			<div class="chapter-body">
				{@html renderMarkdown(activeChapter.content_md)}
			</div>

			<!-- Evidence & Quant data (collapsible) -->
			{#if activeChapter.evidence_refs || activeChapter.quant_data}
				<details class="evidence-section">
					<summary class="evidence-toggle">View Sources & Evidence</summary>
					<div class="evidence-content">
						{#if activeChapter.evidence_refs}
							<h4 class="evidence-title">Evidence References</h4>
							<div class="evidence-grid">
								{#each flattenObject(activeChapter.evidence_refs) as entry (entry.key)}
									<div class="evidence-row">
										<span class="evidence-key">{entry.key}</span>
										<span class="evidence-val">{entry.value}</span>
									</div>
								{/each}
							</div>
						{/if}
						{#if activeChapter.quant_data}
							<h4 class="evidence-title">Quantitative Context</h4>
							<div class="evidence-grid">
								{#each flattenObject(activeChapter.quant_data) as entry (entry.key)}
									<div class="evidence-row">
										<span class="evidence-key">{entry.key}</span>
										<span class="evidence-val">{entry.value}</span>
									</div>
								{/each}
							</div>
						{/if}
					</div>
				</details>
			{/if}
		{:else}
			<div class="chapter-empty">
				<p>No chapters available.</p>
			</div>
		{/if}
	</article>
</div>

<!-- ═══════════════════════════════════════════════════════════════════════ -->
<!-- AUDIT TRAIL                                                             -->
<!-- ═══════════════════════════════════════════════════════════════════════ -->
<div class="audit-section">
	<button class="audit-toggle" onclick={handleAuditToggle}>
		<span class="audit-toggle-icon">{auditTrailOpen ? "▾" : "▸"}</span>
		Audit Trail
	</button>

	{#if auditTrailOpen}
		<div class="audit-content">
			{#if auditLoading}
				<p class="audit-loading">Loading audit trail…</p>
			{:else if auditEvents.length === 0}
				<p class="audit-empty">No audit events recorded yet.</p>
			{:else}
				<div class="audit-timeline">
					{#each auditEvents as event (event.id)}
						<div class="audit-event">
							<div class="audit-event-header">
								<span class="audit-action">{auditActionLabel(event.action)}</span>
								{#if event.created_at}
									<span class="audit-date">{formatDateTime(event.created_at)}</span>
								{/if}
							</div>
							{#if event.actor_id}
								<span class="audit-actor">by {event.actor_id}</span>
							{/if}
							{#if event.after}
								<div class="audit-detail">
									{#each Object.entries(event.after) as [key, value] (key)}
										{#if value !== null && value !== undefined}
											<span class="audit-field">
												<span class="audit-field-key">{key}:</span>
												<span class="audit-field-val">{typeof value === "object" ? JSON.stringify(value) : String(value)}</span>
											</span>
										{/if}
									{/each}
								</div>
							{/if}
						</div>
					{/each}
				</div>
			{/if}
		</div>
	{/if}
</div>

<!-- ═══════════════════════════════════════════════════════════════════════ -->
<!-- APPROVAL DIALOGS                                                       -->
<!-- ═══════════════════════════════════════════════════════════════════════ -->
<ConsequenceDialog
	bind:open={approveDialogOpen}
	title="Approve DD Report"
	impactSummary="This report will be marked as approved and available for distribution."
	requireRationale={true}
	rationaleLabel="Approval Rationale"
	rationalePlaceholder={isApproveOverride
		? "This overrides the AI recommendation. Record the investment committee basis for this decision."
		: "Record the investment committee basis for this approval."}
	rationaleMinLength={10}
	confirmLabel="Approve Report"
	metadata={[
		{ label: "AI Recommendation", value: anchorLabel(report.decision_anchor), emphasis: isApproveOverride },
		{ label: "Confidence Score", value: report.confidence_score !== null ? `${report.confidence_score.toFixed(1)}%` : "—" },
	]}
	onConfirm={handleApprove}
>
	{#if isApproveOverride}
		{#snippet consequenceList()}
			<div class="override-warning">
				Override detected — AI recommends "{anchorLabel(report.decision_anchor)}" but you are approving.
			</div>
		{/snippet}
	{/if}
</ConsequenceDialog>

<ConsequenceDialog
	bind:open={rejectDialogOpen}
	title="Reject DD Report"
	impactSummary="This report will be sent back to draft status for regeneration."
	destructive={true}
	requireRationale={true}
	rationaleLabel="Rejection Reason"
	rationalePlaceholder={isRejectOverride
		? "This overrides the AI recommendation. Record the investment committee basis for this rejection."
		: "Describe why this report does not meet committee standards."}
	rationaleMinLength={10}
	confirmLabel="Reject Report"
	metadata={[
		{ label: "AI Recommendation", value: anchorLabel(report.decision_anchor), emphasis: isRejectOverride },
		{ label: "Confidence Score", value: report.confidence_score !== null ? `${report.confidence_score.toFixed(1)}%` : "—" },
	]}
	onConfirm={handleReject}
>
	{#if isRejectOverride}
		{#snippet consequenceList()}
			<div class="override-warning">
				Override detected — AI recommends "{anchorLabel(report.decision_anchor)}" but you are rejecting.
			</div>
		{/snippet}
	{/if}
</ConsequenceDialog>

<style>
	/* ── Action bar ──────────────────────────────────────────────────────── */
	.action-bar {
		display: flex;
		align-items: center;
		gap: var(--ii-space-inline-sm, 10px);
	}

	.action-confidence {
		font-size: var(--ii-text-body, 0.9375rem);
		font-weight: 700;
		font-variant-numeric: tabular-nums;
	}

	.action-anchor {
		font-size: var(--ii-text-small, 0.8125rem);
		font-weight: 600;
		padding: 2px 8px;
		border-radius: var(--ii-radius-pill, 999px);
		background: color-mix(in srgb, currentColor 10%, transparent);
	}

	/* ── SSE banner ──────────────────────────────────────────────────────── */
	.sse-banner {
		display: flex;
		align-items: center;
		gap: var(--ii-space-inline-sm, 8px);
		padding: var(--ii-space-stack-2xs, 6px) var(--ii-space-inline-md, 16px);
		background: color-mix(in srgb, var(--ii-info) 10%, transparent);
		border-bottom: 1px solid color-mix(in srgb, var(--ii-info) 20%, transparent);
		font-size: var(--ii-text-small, 0.8125rem);
		color: var(--ii-text-primary);
	}

	.sse-dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		background: var(--ii-info);
		animation: pulse-dot 1.5s ease infinite;
		flex-shrink: 0;
	}

	@keyframes pulse-dot {
		0%, 100% { opacity: 1; }
		50% { opacity: 0.3; }
	}

	.sse-text {
		flex: 1;
	}

	/* ── Workbench grid ──────────────────────────────────────────────────── */
	.workbench {
		display: grid;
		grid-template-columns: 220px 1fr;
		height: calc(100vh - 120px);
		overflow: hidden;
	}

	/* Chapter nav */
	.chapter-nav {
		overflow-y: auto;
		border-right: 1px solid var(--ii-border-subtle);
		background: var(--ii-surface-elevated);
		padding: var(--ii-space-stack-xs, 8px);
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.chapter-nav-item {
		display: flex;
		align-items: center;
		gap: var(--ii-space-inline-xs, 8px);
		padding: var(--ii-space-stack-2xs, 8px) var(--ii-space-inline-sm, 10px);
		border: none;
		border-radius: var(--ii-radius-sm, 8px);
		background: transparent;
		color: var(--ii-text-secondary);
		font-size: var(--ii-text-small, 0.8125rem);
		font-family: var(--ii-font-sans);
		text-align: left;
		cursor: pointer;
		transition: background-color 120ms ease, color 120ms ease;
	}

	.chapter-nav-item:hover {
		background: var(--ii-surface-alt);
		color: var(--ii-text-primary);
	}

	.chapter-nav-item.active {
		background: color-mix(in srgb, var(--ii-brand-primary) 12%, transparent);
		color: var(--ii-brand-primary);
		font-weight: 600;
	}

	.chapter-order {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 22px;
		height: 22px;
		border-radius: 50%;
		background: var(--ii-surface-alt);
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 600;
		flex-shrink: 0;
	}

	.chapter-nav-item.active .chapter-order {
		background: var(--ii-brand-primary);
		color: #fff;
	}

	.chapter-tag {
		flex: 1;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.chapter-critic-dot {
		width: 6px;
		height: 6px;
		border-radius: 50%;
		flex-shrink: 0;
	}

	.chapter-critic-dot--accepted { background: var(--ii-success); }
	.chapter-critic-dot--escalated { background: var(--ii-danger); }

	/* Chapter content */
	.chapter-content {
		overflow-y: auto;
		padding: var(--ii-space-stack-md, 20px) var(--ii-space-inline-xl, 32px);
		background: var(--ii-surface);
	}

	.chapter-header {
		margin-bottom: var(--ii-space-stack-md, 20px);
		padding-bottom: var(--ii-space-stack-sm, 12px);
		border-bottom: 1px solid var(--ii-border-subtle);
		display: flex;
		flex-direction: column;
		gap: var(--ii-space-stack-2xs, 4px);
	}

	.chapter-title {
		font-size: var(--ii-text-h3, 1.375rem);
		font-weight: 700;
		color: var(--ii-text-primary);
		line-height: var(--ii-leading-h3, 1.24);
	}

	.chapter-generated {
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-muted);
		font-style: italic;
	}

	.chapter-critic {
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-secondary);
	}

	.chapter-empty {
		display: flex;
		align-items: center;
		justify-content: center;
		height: 200px;
		color: var(--ii-text-muted);
	}

	/* ── Rendered markdown ───────────────────────────────────────────────── */
	.chapter-body {
		max-width: 720px;
		line-height: var(--ii-leading-body, 1.65);
		color: var(--ii-text-primary);
		font-size: var(--ii-text-body, 0.9375rem);
	}

	.chapter-body :global(.rw-h1) {
		font-size: var(--ii-text-h2, 1.75rem);
		font-weight: 700;
		margin: var(--ii-space-stack-lg, 28px) 0 var(--ii-space-stack-sm, 12px);
		color: var(--ii-text-primary);
	}

	.chapter-body :global(.rw-h2) {
		font-size: var(--ii-text-h3, 1.375rem);
		font-weight: 600;
		margin: var(--ii-space-stack-md, 20px) 0 var(--ii-space-stack-xs, 8px);
		color: var(--ii-text-primary);
	}

	.chapter-body :global(.rw-h3) {
		font-size: var(--ii-text-h4, 1.125rem);
		font-weight: 600;
		margin: var(--ii-space-stack-sm, 16px) 0 var(--ii-space-stack-2xs, 4px);
		color: var(--ii-text-primary);
	}

	.chapter-body :global(.rw-p) {
		margin: 0 0 var(--ii-space-stack-sm, 12px);
	}

	.chapter-body :global(.rw-ul) {
		margin: 0 0 var(--ii-space-stack-sm, 12px);
		padding-left: var(--ii-space-inline-lg, 24px);
	}

	.chapter-body :global(.rw-li) {
		margin: 0 0 var(--ii-space-stack-2xs, 4px);
	}

	.chapter-body :global(.rw-code) {
		font-family: var(--ii-font-mono);
		font-size: var(--ii-text-mono, 0.875rem);
		padding: 1px 5px;
		border-radius: 4px;
		background: var(--ii-surface-alt);
	}

	.chapter-body :global(.rw-empty) {
		color: var(--ii-text-muted);
		font-style: italic;
	}

	/* ── Evidence section ────────────────────────────────────────────────── */
	.evidence-section {
		margin-top: var(--ii-space-stack-lg, 28px);
		border: 1px solid var(--ii-border-subtle);
		border-radius: var(--ii-radius-sm, 8px);
		overflow: hidden;
	}

	.evidence-toggle {
		padding: var(--ii-space-stack-xs, 10px) var(--ii-space-inline-md, 16px);
		font-size: var(--ii-text-small, 0.8125rem);
		font-weight: 600;
		color: var(--ii-text-secondary);
		cursor: pointer;
		background: var(--ii-surface-alt);
		border-bottom: 1px solid var(--ii-border-subtle);
	}

	.evidence-toggle:hover {
		color: var(--ii-text-primary);
	}

	.evidence-content {
		padding: var(--ii-space-stack-sm, 12px) var(--ii-space-inline-md, 16px);
		display: flex;
		flex-direction: column;
		gap: var(--ii-space-stack-md, 16px);
	}

	.evidence-title {
		font-size: var(--ii-text-small, 0.8125rem);
		font-weight: 600;
		color: var(--ii-text-primary);
		margin-bottom: var(--ii-space-stack-2xs, 4px);
	}

	.evidence-grid {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.evidence-row {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
		gap: var(--ii-space-inline-md, 16px);
		padding: 3px 0;
		font-size: var(--ii-text-label, 0.75rem);
		border-bottom: 1px solid var(--ii-border-subtle);
	}

	.evidence-key {
		color: var(--ii-text-muted);
		flex-shrink: 0;
		max-width: 50%;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.evidence-val {
		color: var(--ii-text-primary);
		font-variant-numeric: tabular-nums;
		text-align: right;
		word-break: break-all;
	}

	/* ── Override warning ────────────────────────────────────────────────── */
	.override-warning {
		padding: var(--ii-space-stack-xs, 8px) var(--ii-space-inline-sm, 12px);
		border-radius: var(--ii-radius-sm, 6px);
		background: color-mix(in srgb, var(--ii-warning) 12%, transparent);
		color: var(--ii-warning);
		font-size: var(--ii-text-small, 0.8125rem);
		font-weight: 500;
	}

	/* ── Audit trail ────────────────────────────────────────────────────── */
	.audit-section {
		border-top: 1px solid var(--ii-border-subtle);
	}

	.audit-toggle {
		display: flex;
		align-items: center;
		gap: var(--ii-space-inline-xs, 6px);
		width: 100%;
		padding: var(--ii-space-stack-xs, 10px) var(--ii-space-inline-md, 16px);
		border: none;
		background: var(--ii-surface-elevated);
		color: var(--ii-text-secondary);
		font-size: var(--ii-text-small, 0.8125rem);
		font-weight: 600;
		font-family: var(--ii-font-sans);
		cursor: pointer;
		text-align: left;
	}

	.audit-toggle:hover {
		color: var(--ii-text-primary);
		background: var(--ii-surface-alt);
	}

	.audit-toggle-icon {
		font-size: 10px;
		width: 14px;
		text-align: center;
	}

	.audit-content {
		padding: var(--ii-space-stack-sm, 12px) var(--ii-space-inline-md, 16px);
	}

	.audit-loading, .audit-empty {
		font-size: var(--ii-text-small, 0.8125rem);
		color: var(--ii-text-muted);
	}

	.audit-timeline {
		display: flex;
		flex-direction: column;
		gap: var(--ii-space-stack-xs, 8px);
	}

	.audit-event {
		padding: var(--ii-space-stack-xs, 8px) var(--ii-space-inline-sm, 12px);
		border-left: 3px solid var(--ii-border-accent);
		background: var(--ii-surface-alt);
		border-radius: 0 var(--ii-radius-sm, 6px) var(--ii-radius-sm, 6px) 0;
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.audit-event-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
	}

	.audit-action {
		font-size: var(--ii-text-small, 0.8125rem);
		font-weight: 600;
		color: var(--ii-text-primary);
	}

	.audit-date {
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-muted);
		font-variant-numeric: tabular-nums;
	}

	.audit-actor {
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-secondary);
	}

	.audit-detail {
		display: flex;
		flex-wrap: wrap;
		gap: var(--ii-space-inline-xs, 6px);
		margin-top: 4px;
	}

	.audit-field {
		font-size: var(--ii-text-label, 0.75rem);
		display: inline-flex;
		gap: 3px;
	}

	.audit-field-key {
		color: var(--ii-text-muted);
	}

	.audit-field-val {
		color: var(--ii-text-secondary);
		font-variant-numeric: tabular-nums;
	}

	/* ── Responsive ──────────────────────────────────────────────────────── */
	@media (max-width: 768px) {
		.workbench {
			grid-template-columns: 1fr;
			grid-template-rows: auto 1fr;
			height: auto;
		}

		.chapter-nav {
			border-right: none;
			border-bottom: 1px solid var(--ii-border-subtle);
			flex-direction: row;
			overflow-x: auto;
			padding: var(--ii-space-stack-2xs, 4px);
		}

		.chapter-nav-item {
			white-space: nowrap;
		}

		.chapter-tag {
			display: none;
		}

		.chapter-content {
			padding: var(--ii-space-stack-sm, 12px) var(--ii-space-inline-md, 16px);
		}
	}
</style>
