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
		PageHeader, StatusBadge, Button, Card, ConsequenceDialog,
		formatDateTime, formatPercent,
		createSSEStream,
	} from "@netz/ui";
	import type { ConsequenceDialogPayload } from "@netz/ui";
	import { createClientApiClient } from "$lib/api/client";
	import type { PageData } from "./$types";
	import type { DDReportFull, DDChapter, DDReportStatus, DecisionAnchor } from "$lib/types/dd-report";
	import { chapterTitle, anchorLabel, anchorColor, confidenceColor } from "$lib/types/dd-report";

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

	function startSSE() {
		if (report.status !== "generating") return;
		sseConnection?.disconnect();

		sseConnection = createSSEStream<GenerationEvent>({
			url: `/dd-reports/${reportId}/stream`,
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

	// ── Markdown rendering (safe subset — no raw HTML) ────────────────────

	function renderMarkdown(md: string | null): string {
		if (!md) return "<p class=\"rw-empty\">Content not yet generated.</p>";
		return md
			.replace(/^### (.+)$/gm, '<h3 class="rw-h3">$1</h3>')
			.replace(/^## (.+)$/gm, '<h2 class="rw-h2">$1</h2>')
			.replace(/^# (.+)$/gm, '<h1 class="rw-h1">$1</h1>')
			.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
			.replace(/\*(.+?)\*/g, "<em>$1</em>")
			.replace(/`(.+?)`/g, '<code class="rw-code">$1</code>')
			.replace(/^- (.+)$/gm, '<li class="rw-li">$1</li>')
			.replace(/(<li[^>]*>.*<\/li>\n?)+/g, '<ul class="rw-ul">$&</ul>')
			.replace(/^(?!<[hul]|<li|<strong|<em|<code)(.+)$/gm, '<p class="rw-p">$1</p>')
			.replace(/\n{2,}/g, "");
	}

	// ── Evidence flattening ───────────────────────────────────────────────

	function flattenObject(obj: Record<string, unknown>, prefix = ""): Array<{ key: string; value: string }> {
		const entries: Array<{ key: string; value: string }> = [];
		for (const [k, v] of Object.entries(obj)) {
			const label = prefix ? `${prefix} › ${k}` : k;
			if (v && typeof v === "object" && !Array.isArray(v)) {
				entries.push(...flattenObject(v as Record<string, unknown>, label));
			} else {
				entries.push({ key: label, value: String(v ?? "—") });
			}
		}
		return entries;
	}
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
		gap: var(--netz-space-inline-sm, 10px);
	}

	.action-confidence {
		font-size: var(--netz-text-body, 0.9375rem);
		font-weight: 700;
		font-variant-numeric: tabular-nums;
	}

	.action-anchor {
		font-size: var(--netz-text-small, 0.8125rem);
		font-weight: 600;
		padding: 2px 8px;
		border-radius: var(--netz-radius-pill, 999px);
		background: color-mix(in srgb, currentColor 10%, transparent);
	}

	/* ── SSE banner ──────────────────────────────────────────────────────── */
	.sse-banner {
		display: flex;
		align-items: center;
		gap: var(--netz-space-inline-sm, 8px);
		padding: var(--netz-space-stack-2xs, 6px) var(--netz-space-inline-md, 16px);
		background: color-mix(in srgb, var(--netz-info) 10%, transparent);
		border-bottom: 1px solid color-mix(in srgb, var(--netz-info) 20%, transparent);
		font-size: var(--netz-text-small, 0.8125rem);
		color: var(--netz-text-primary);
	}

	.sse-dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		background: var(--netz-info);
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
		border-right: 1px solid var(--netz-border-subtle);
		background: var(--netz-surface-elevated);
		padding: var(--netz-space-stack-xs, 8px);
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.chapter-nav-item {
		display: flex;
		align-items: center;
		gap: var(--netz-space-inline-xs, 8px);
		padding: var(--netz-space-stack-2xs, 8px) var(--netz-space-inline-sm, 10px);
		border: none;
		border-radius: var(--netz-radius-sm, 8px);
		background: transparent;
		color: var(--netz-text-secondary);
		font-size: var(--netz-text-small, 0.8125rem);
		font-family: var(--netz-font-sans);
		text-align: left;
		cursor: pointer;
		transition: background-color 120ms ease, color 120ms ease;
	}

	.chapter-nav-item:hover {
		background: var(--netz-surface-alt);
		color: var(--netz-text-primary);
	}

	.chapter-nav-item.active {
		background: color-mix(in srgb, var(--netz-brand-primary) 12%, transparent);
		color: var(--netz-brand-primary);
		font-weight: 600;
	}

	.chapter-order {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 22px;
		height: 22px;
		border-radius: 50%;
		background: var(--netz-surface-alt);
		font-size: var(--netz-text-label, 0.75rem);
		font-weight: 600;
		flex-shrink: 0;
	}

	.chapter-nav-item.active .chapter-order {
		background: var(--netz-brand-primary);
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

	.chapter-critic-dot--accepted { background: var(--netz-success); }
	.chapter-critic-dot--escalated { background: var(--netz-danger); }

	/* Chapter content */
	.chapter-content {
		overflow-y: auto;
		padding: var(--netz-space-stack-md, 20px) var(--netz-space-inline-xl, 32px);
		background: var(--netz-surface);
	}

	.chapter-header {
		margin-bottom: var(--netz-space-stack-md, 20px);
		padding-bottom: var(--netz-space-stack-sm, 12px);
		border-bottom: 1px solid var(--netz-border-subtle);
		display: flex;
		flex-direction: column;
		gap: var(--netz-space-stack-2xs, 4px);
	}

	.chapter-title {
		font-size: var(--netz-text-h3, 1.375rem);
		font-weight: 700;
		color: var(--netz-text-primary);
		line-height: var(--netz-leading-h3, 1.24);
	}

	.chapter-generated {
		font-size: var(--netz-text-label, 0.75rem);
		color: var(--netz-text-muted);
		font-style: italic;
	}

	.chapter-critic {
		font-size: var(--netz-text-label, 0.75rem);
		color: var(--netz-text-secondary);
	}

	.chapter-empty {
		display: flex;
		align-items: center;
		justify-content: center;
		height: 200px;
		color: var(--netz-text-muted);
	}

	/* ── Rendered markdown ───────────────────────────────────────────────── */
	.chapter-body {
		max-width: 720px;
		line-height: var(--netz-leading-body, 1.65);
		color: var(--netz-text-primary);
		font-size: var(--netz-text-body, 0.9375rem);
	}

	.chapter-body :global(.rw-h1) {
		font-size: var(--netz-text-h2, 1.75rem);
		font-weight: 700;
		margin: var(--netz-space-stack-lg, 28px) 0 var(--netz-space-stack-sm, 12px);
		color: var(--netz-text-primary);
	}

	.chapter-body :global(.rw-h2) {
		font-size: var(--netz-text-h3, 1.375rem);
		font-weight: 600;
		margin: var(--netz-space-stack-md, 20px) 0 var(--netz-space-stack-xs, 8px);
		color: var(--netz-text-primary);
	}

	.chapter-body :global(.rw-h3) {
		font-size: var(--netz-text-h4, 1.125rem);
		font-weight: 600;
		margin: var(--netz-space-stack-sm, 16px) 0 var(--netz-space-stack-2xs, 4px);
		color: var(--netz-text-primary);
	}

	.chapter-body :global(.rw-p) {
		margin: 0 0 var(--netz-space-stack-sm, 12px);
	}

	.chapter-body :global(.rw-ul) {
		margin: 0 0 var(--netz-space-stack-sm, 12px);
		padding-left: var(--netz-space-inline-lg, 24px);
	}

	.chapter-body :global(.rw-li) {
		margin: 0 0 var(--netz-space-stack-2xs, 4px);
	}

	.chapter-body :global(.rw-code) {
		font-family: var(--netz-font-mono);
		font-size: var(--netz-text-mono, 0.875rem);
		padding: 1px 5px;
		border-radius: 4px;
		background: var(--netz-surface-alt);
	}

	.chapter-body :global(.rw-empty) {
		color: var(--netz-text-muted);
		font-style: italic;
	}

	/* ── Evidence section ────────────────────────────────────────────────── */
	.evidence-section {
		margin-top: var(--netz-space-stack-lg, 28px);
		border: 1px solid var(--netz-border-subtle);
		border-radius: var(--netz-radius-sm, 8px);
		overflow: hidden;
	}

	.evidence-toggle {
		padding: var(--netz-space-stack-xs, 10px) var(--netz-space-inline-md, 16px);
		font-size: var(--netz-text-small, 0.8125rem);
		font-weight: 600;
		color: var(--netz-text-secondary);
		cursor: pointer;
		background: var(--netz-surface-alt);
		border-bottom: 1px solid var(--netz-border-subtle);
	}

	.evidence-toggle:hover {
		color: var(--netz-text-primary);
	}

	.evidence-content {
		padding: var(--netz-space-stack-sm, 12px) var(--netz-space-inline-md, 16px);
		display: flex;
		flex-direction: column;
		gap: var(--netz-space-stack-md, 16px);
	}

	.evidence-title {
		font-size: var(--netz-text-small, 0.8125rem);
		font-weight: 600;
		color: var(--netz-text-primary);
		margin-bottom: var(--netz-space-stack-2xs, 4px);
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
		gap: var(--netz-space-inline-md, 16px);
		padding: 3px 0;
		font-size: var(--netz-text-label, 0.75rem);
		border-bottom: 1px solid var(--netz-border-subtle);
	}

	.evidence-key {
		color: var(--netz-text-muted);
		flex-shrink: 0;
		max-width: 50%;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.evidence-val {
		color: var(--netz-text-primary);
		font-variant-numeric: tabular-nums;
		text-align: right;
		word-break: break-all;
	}

	/* ── Override warning ────────────────────────────────────────────────── */
	.override-warning {
		padding: var(--netz-space-stack-xs, 8px) var(--netz-space-inline-sm, 12px);
		border-radius: var(--netz-radius-sm, 6px);
		background: color-mix(in srgb, var(--netz-warning) 12%, transparent);
		color: var(--netz-warning);
		font-size: var(--netz-text-small, 0.8125rem);
		font-weight: 500;
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
			border-bottom: 1px solid var(--netz-border-subtle);
			flex-direction: row;
			overflow-x: auto;
			padding: var(--netz-space-stack-2xs, 4px);
		}

		.chapter-nav-item {
			white-space: nowrap;
		}

		.chapter-tag {
			display: none;
		}

		.chapter-content {
			padding: var(--netz-space-stack-sm, 12px) var(--netz-space-inline-md, 16px);
		}
	}
</style>
