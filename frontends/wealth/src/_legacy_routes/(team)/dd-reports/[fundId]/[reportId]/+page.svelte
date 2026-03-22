<!--
  DD Report detail — chapter navigation sidebar + content display.
  Download PDF, regenerate with confirmation. Approval bar for IC members.
  BL-09: Evidence Pack Inspector (Sheet slide-in per chapter).
  BL-10: AI Content Markers (provenance caption with generation date).
  BL-13: SLA-aware generation banner.
  BL-14: Retry on regeneration failure.
  BL-15: Confidence score visualization with color bands.
  BL-17: Override audit narrative — AI recommendation in approval dialog.
-->
<script lang="ts">
	import { Card, Button, EmptyState, cn, StatusBadge, Sheet } from "@netz/ui";
	import { ActionButton, ConfirmDialog, ConsequenceDialog } from "@netz/ui";
	import type { ConsequenceDialogMetadataItem } from "@netz/ui";
	import { formatDate, formatPercent } from "@netz/ui";
	import { createClientApiClient } from "$lib/api/client";
	import { invalidateAll } from "$app/navigation";
	import { getContext } from "svelte";
	import type { PageData } from "./$types";
	import { resolveWealthStatus } from "$lib/utils/status-maps";
	import type { DDReportChapter } from "$lib/types/api";
	import DOMPurify from "dompurify";

	/** Render Markdown as safe HTML — converts basic Markdown then sanitizes with DOMPurify. */
	function renderSafeMarkdown(md: string): string {
		// Convert basic Markdown to HTML (headers, bold, italic, lists, code blocks)
		let html = md
			.replace(/^### (.+)$/gm, "<h3>$1</h3>")
			.replace(/^## (.+)$/gm, "<h2>$1</h2>")
			.replace(/^# (.+)$/gm, "<h1>$1</h1>")
			.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
			.replace(/\*(.+?)\*/g, "<em>$1</em>")
			.replace(/`(.+?)`/g, "<code>$1</code>")
			.replace(/^- (.+)$/gm, "<li>$1</li>")
			.replace(/(<li>.*<\/li>\n?)+/g, (match) => `<ul>${match}</ul>`)
			.replace(/\n\n/g, "</p><p>")
			.replace(/\n/g, "<br/>");
		html = `<p>${html}</p>`;
		// Sanitize with DOMPurify — strips scripts/handlers/javascript:
		if (typeof window !== "undefined") {
			html = DOMPurify.sanitize(html);
		}
		return html;
	}

	/**
	 * Convert a chapter_tag like "management_quality" to "Management Quality".
	 * Splits on underscores, capitalises each word.
	 */
	function formatChapterTitle(tag: string): string {
		return tag
			.split("_")
			.map((word) => word.charAt(0).toUpperCase() + word.slice(1))
			.join(" ");
	}

	/**
	 * Return a flat array of [key, displayValue] pairs from a nested object,
	 * suitable for rendering in the Evidence Inspector sheet.
	 */
	function flattenRecord(
		obj: Record<string, unknown>,
		prefix = "",
	): { key: string; value: string }[] {
		const entries: { key: string; value: string }[] = [];
		for (const [k, v] of Object.entries(obj)) {
			const label = prefix ? `${prefix} › ${k}` : k;
			if (v !== null && typeof v === "object" && !Array.isArray(v)) {
				entries.push(...flattenRecord(v as Record<string, unknown>, label));
			} else if (Array.isArray(v)) {
				entries.push({ key: label, value: v.join(", ") });
			} else {
				entries.push({ key: label, value: String(v ?? "—") });
			}
		}
		return entries;
	}

	const IC_ROLES = new Set(["admin", "super_admin", "investment_team"]);

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let { data }: { data: PageData } = $props();

	let report = $derived(data.report as Record<string, unknown>);
	let chapters = $derived((report?.chapters ?? []) as DDReportChapter[]);
	let reportStatus = $derived((report?.status ?? "draft") as string);
	let createdBy = $derived((report?.created_by ?? null) as string | null);
	let rejectionReason = $derived((report?.rejection_reason ?? null) as string | null);

	// BL-15: Confidence score and decision anchor
	let confidenceScore = $derived(report?.confidence_score as number | null ?? null);
	let decisionAnchor = $derived((report?.decision_anchor ?? null) as string | null);

	let activeChapter = $state(0);
	let downloading = $state(false);
	let showRegenConfirm = $state(false);
	let regenerating = $state(false);
	let approving = $state(false);
	let showApproveDialog = $state(false);
	let showRejectDialog = $state(false);
	let rejecting = $state(false);
	let actionError = $state<string | null>(null);

	// BL-13: SLA-aware regeneration timer
	let regenElapsed = $state(0);
	let regenInterval: ReturnType<typeof setInterval> | null = null;

	function startRegenTimer() {
		stopRegenTimer();
		regenElapsed = 0;
		const start = Date.now();
		regenInterval = setInterval(() => {
			regenElapsed = Math.floor((Date.now() - start) / 1000);
		}, 1000);
	}
	function stopRegenTimer() {
		if (regenInterval) { clearInterval(regenInterval); regenInterval = null; }
	}
	let regenSlaExceeded = $derived(regenElapsed > 180);

	// BL-15: Confidence color bands
	function confidenceColor(score: number | null): string {
		if (score === null) return "var(--netz-text-muted)";
		if (score >= 80) return "var(--netz-success)";
		if (score >= 60) return "var(--netz-info)";
		return "var(--netz-warning)";
	}
	function confidenceLabel(score: number | null): string {
		if (score === null) return "—";
		if (score >= 80) return "High";
		if (score >= 60) return "Moderate";
		return "Low";
	}
	function anchorLabel(anchor: string | null): string {
		if (!anchor) return "—";
		switch (anchor) {
			case "APPROVE": return "Approve";
			case "CONDITIONAL": return "Conditional";
			case "REJECT": return "Reject";
			default: return anchor;
		}
	}
	function anchorColor(anchor: string | null): string {
		switch (anchor) {
			case "APPROVE": return "var(--netz-success)";
			case "CONDITIONAL": return "var(--netz-warning)";
			case "REJECT": return "var(--netz-danger)";
			default: return "var(--netz-text-muted)";
		}
	}

	// BL-17: Override detection
	let isApproveOverride = $derived(
		decisionAnchor === "REJECT" || decisionAnchor === "CONDITIONAL"
	);
	let isRejectOverride = $derived(
		decisionAnchor === "APPROVE"
	);

	// BL-17: Metadata for ConsequenceDialog showing AI recommendation
	let approveMetadata = $derived<ConsequenceDialogMetadataItem[]>(
		decisionAnchor
			? [
				{ label: "AI Recommendation", value: anchorLabel(decisionAnchor), emphasis: true },
				{ label: "Confidence Score", value: confidenceScore !== null ? `${confidenceScore}%` : "—" },
			]
			: [],
	);
	let rejectMetadata = $derived<ConsequenceDialogMetadataItem[]>(
		decisionAnchor
			? [
				{ label: "AI Recommendation", value: anchorLabel(decisionAnchor), emphasis: true },
				{ label: "Confidence Score", value: confidenceScore !== null ? `${confidenceScore}%` : "—" },
			]
			: [],
	);

	// BL-09: Evidence Inspector sheet state
	let showEvidenceSheet = $state(false);
	let evidenceChapter = $state<DDReportChapter | null>(null);

	let canApprove = $derived(
		reportStatus === "pending_approval" &&
		IC_ROLES.has(data.actorRole) &&
		data.actorId !== createdBy
	);

	let canReject = $derived(
		reportStatus === "pending_approval" &&
		IC_ROLES.has(data.actorRole)
	);

	// BL-09: derived evidence data for the currently-open sheet
	let evidenceEntries = $derived(
		evidenceChapter?.evidence_refs
			? flattenRecord(evidenceChapter.evidence_refs)
			: []
	);
	let quantEntries = $derived(
		evidenceChapter?.quant_data
			? flattenRecord(evidenceChapter.quant_data)
			: []
	);
	let hasEvidenceData = $derived(evidenceEntries.length > 0 || quantEntries.length > 0);

	function openEvidenceSheet(chapter: DDReportChapter) {
		evidenceChapter = chapter;
		showEvidenceSheet = true;
	}

	async function downloadPDF() {
		downloading = true;
		try {
			const api = createClientApiClient(getToken);
			const blob = await api.getBlob(`/fact-sheets/dd-reports/${data.reportId}/download`);
			const url = URL.createObjectURL(blob);
			const a = document.createElement("a");
			a.href = url;
			a.download = `dd-report-${data.reportId}.pdf`;
			a.click();
			URL.revokeObjectURL(url);
		} catch (e) {
			actionError = e instanceof Error ? e.message : "Download failed";
		} finally {
			downloading = false;
		}
	}

	async function regenerate() {
		regenerating = true;
		showRegenConfirm = false;
		actionError = null;
		startRegenTimer();
		try {
			const api = createClientApiClient(getToken);
			await api.post(`/dd-reports/${data.reportId}/regenerate`, {});
			await invalidateAll();
		} catch (e) {
			actionError = e instanceof Error ? e.message : "Regeneration failed";
		} finally {
			regenerating = false;
			stopRegenTimer();
		}
	}

	async function approveReport(payload: { rationale?: string }) {
		approving = true;
		actionError = null;
		try {
			const api = createClientApiClient(getToken);
			await api.post(`/dd-reports/${data.reportId}/approve`, {
				rationale: payload.rationale,
			});
			showApproveDialog = false;
			await invalidateAll();
		} catch (e) {
			actionError = e instanceof Error ? e.message : "Approval failed";
		} finally {
			approving = false;
		}
	}

	async function rejectReport(payload: { rationale?: string }) {
		rejecting = true;
		actionError = null;
		try {
			const api = createClientApiClient(getToken);
			await api.post(`/dd-reports/${data.reportId}/reject`, {
				reason: payload.rationale,
			});
			showRejectDialog = false;
			await invalidateAll();
		} catch (e) {
			actionError = e instanceof Error ? e.message : "Rejection failed";
		} finally {
			rejecting = false;
		}
	}
</script>

<div class="flex h-full flex-col">
	<!-- Approval bar -->
	{#if reportStatus === "pending_approval" || reportStatus === "approved" || rejectionReason}
		<div class={cn(
			"flex items-center justify-between border-b px-6 py-3",
			reportStatus === "pending_approval" && "border-(--netz-warning)/30 bg-(--netz-warning)/5",
			reportStatus === "approved" && "border-(--netz-success)/30 bg-(--netz-success)/5",
			reportStatus === "draft" && rejectionReason && "border-(--netz-status-error)/30 bg-(--netz-status-error)/5",
		)}>
			<div class="flex items-center gap-3">
				<StatusBadge status={reportStatus} type="default" resolve={resolveWealthStatus} />
				{#if reportStatus === "pending_approval"}
					<span class="text-sm text-(--netz-text-secondary)">This report is awaiting IC approval before investor distribution.</span>
				{:else if reportStatus === "approved"}
					<span class="text-sm text-(--netz-text-secondary)">Approved for investor distribution.</span>
				{/if}
				{#if rejectionReason && reportStatus === "draft"}
					<span class="text-sm text-(--netz-status-error)">Rejected: {rejectionReason}</span>
				{/if}
			</div>
			{#if reportStatus === "pending_approval"}
				<div class="flex gap-2">
					{#if canApprove}
						<Button size="sm" onclick={() => showApproveDialog = true} disabled={approving}>
							Approve
						</Button>
					{/if}
					{#if canReject}
						<Button size="sm" variant="outline" onclick={() => showRejectDialog = true}>
							Reject
						</Button>
					{/if}
					{#if !canApprove && !canReject}
						<span class="text-xs text-(--netz-text-muted)">IC role required to review</span>
					{/if}
					{#if IC_ROLES.has(data.actorRole) && data.actorId === createdBy}
						<span class="text-xs text-(--netz-text-muted)">You cannot approve your own report</span>
					{/if}
				</div>
			{/if}
		</div>
	{/if}

	<!-- BL-15: Confidence score and decision anchor visualization -->
	{#if confidenceScore !== null || decisionAnchor}
		<div class="flex items-center gap-6 border-b border-(--netz-border) px-6 py-3 bg-(--netz-surface-panel)">
			{#if confidenceScore !== null}
				<div class="flex items-center gap-2">
					<span class="text-xs font-medium uppercase tracking-wide text-(--netz-text-muted)">Confidence</span>
					<div class="flex items-center gap-2">
						<div class="h-2 w-24 overflow-hidden rounded-full bg-(--netz-surface-inset)">
							<div
								class="h-full rounded-full transition-[width] duration-300"
								style="width: {Math.min(100, confidenceScore)}%; background-color: {confidenceColor(confidenceScore)};"
							></div>
						</div>
						<span
							class="text-sm font-semibold tabular-nums"
							style="color: {confidenceColor(confidenceScore)};"
						>
							{formatPercent(confidenceScore / 100, 0)}
						</span>
						<span
							class="rounded-full px-2 py-0.5 text-xs font-medium"
							style="background-color: color-mix(in srgb, {confidenceColor(confidenceScore)} 14%, var(--netz-surface)); color: {confidenceColor(confidenceScore)};"
						>
							{confidenceLabel(confidenceScore)}
						</span>
					</div>
				</div>
			{/if}
			{#if decisionAnchor}
				<div class="flex items-center gap-2">
					<span class="text-xs font-medium uppercase tracking-wide text-(--netz-text-muted)">AI Recommendation</span>
					<span
						class="rounded-full px-2.5 py-0.5 text-xs font-semibold"
						style="background-color: color-mix(in srgb, {anchorColor(decisionAnchor)} 14%, var(--netz-surface)); color: {anchorColor(decisionAnchor)};"
					>
						{anchorLabel(decisionAnchor)}
					</span>
				</div>
			{/if}
		</div>
	{/if}

	<!-- BL-13: SLA-aware regeneration banner -->
	{#if regenerating}
		<div class="flex items-center gap-3 border-b border-(--netz-info)/30 bg-(--netz-info)/5 px-6 py-3">
			<svg class="h-4 w-4 animate-spin text-(--netz-info)" viewBox="0 0 24 24" fill="none" aria-hidden="true">
				<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
				<path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
			</svg>
			<span class="text-sm text-(--netz-text-secondary)">
				Regenerating report chapters…
				{#if regenElapsed > 0}
					<span class="text-(--netz-text-muted)">({Math.floor(regenElapsed / 60)}m {regenElapsed % 60}s)</span>
				{/if}
			</span>
			{#if regenSlaExceeded}
				<span class="ml-2 rounded-full px-2 py-0.5 text-xs font-medium" style="background-color: color-mix(in srgb, var(--netz-warning) 14%, var(--netz-surface)); color: var(--netz-warning);">
					Taking longer than expected
				</span>
			{/if}
		</div>
	{/if}

	<!-- BL-13: "generating" status banner (async generation in progress) -->
	{#if reportStatus === "generating" && !regenerating}
		<div class="flex items-center gap-3 border-b border-(--netz-info)/30 bg-(--netz-info)/5 px-6 py-3">
			<svg class="h-4 w-4 animate-spin text-(--netz-info)" viewBox="0 0 24 24" fill="none" aria-hidden="true">
				<circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4" />
				<path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
			</svg>
			<span class="text-sm text-(--netz-text-secondary)">Report generation in progress. Chapters will appear once complete.</span>
			<Button size="sm" variant="ghost" onclick={() => invalidateAll()}>Refresh</Button>
		</div>
	{/if}

	<div class="flex flex-1">
		<!-- Chapter sidebar -->
		<aside class="w-64 shrink-0 border-r border-(--netz-border) bg-(--netz-surface-panel) p-4">
			<h3 class="mb-3 text-sm font-semibold text-(--netz-text-secondary)">Chapters</h3>
			{#if chapters.length === 0}
				<p class="text-xs text-(--netz-text-muted)">No chapters yet.</p>
			{:else}
				<nav class="space-y-1">
					{#each chapters as chapter, i (chapter.id)}
						<button
							class={cn(
								"w-full rounded-md px-3 py-2 text-left text-xs transition-colors",
								activeChapter === i
									? "bg-(--netz-brand-primary)/10 text-(--netz-brand-primary) font-medium"
									: "text-(--netz-text-secondary) hover:bg-(--netz-surface-highlight)"
							)}
							onclick={() => activeChapter = i}
						>
							{chapter.chapter_order}. {formatChapterTitle(chapter.chapter_tag)}
						</button>
					{/each}
				</nav>
			{/if}

			<div class="mt-6 space-y-2">
				<ActionButton
					onclick={downloadPDF}
					loading={downloading}
					loadingText="Downloading..."
					class="w-full"
					size="sm"
				>
					Download PDF
				</ActionButton>
				<ActionButton
					variant="outline"
					onclick={() => showRegenConfirm = true}
					loading={regenerating}
					loadingText="..."
					class="w-full"
					size="sm"
				>
					Regenerate
				</ActionButton>
			</div>
		</aside>

		<!-- Chapter content -->
		<main class="flex-1 overflow-y-auto p-6">
			{#if actionError}
				<div class="mb-4 flex items-center justify-between rounded-md border border-(--netz-status-error) bg-(--netz-status-error)/10 p-3 text-sm text-(--netz-status-error)">
					<span>{actionError}</span>
					<Button size="sm" variant="outline" onclick={() => { actionError = null; regenerate(); }}>
						Retry
					</Button>
				</div>
			{/if}

			{#if chapters.length === 0}
				<EmptyState title="No Chapters" description="Report chapters will appear here after generation." />
			{:else if chapters[activeChapter]}
				{@const chapter = chapters[activeChapter]!}
				<div>
					<!-- Chapter header row -->
					<div class="mb-2 flex items-start justify-between gap-4">
						<h2 class="text-xl font-semibold text-(--netz-text-primary)">
							{chapter.chapter_order}. {formatChapterTitle(chapter.chapter_tag)}
						</h2>
						<!-- BL-09: View Sources button -->
						<button
							class="shrink-0 text-xs font-medium text-(--netz-brand-primary) underline underline-offset-2 hover:text-(--netz-brand-primary)/80 transition-colors"
							onclick={() => openEvidenceSheet(chapter)}
						>
							View Sources
						</button>
					</div>

					<!-- BL-10: AI Content Marker — provenance caption -->
					{#if chapter.generated_at}
						<p
							class="mb-4"
							style="font-size: var(--netz-text-caption, 0.75rem); color: var(--netz-info); line-height: 1.4;"
						>
							AI-generated on {formatDate(chapter.generated_at)}
						</p>
					{/if}

					<Card class="prose prose-sm max-w-none p-6 text-(--netz-text-primary)">
						<!-- Sanitized Markdown rendering — strips scripts/handlers/javascript: -->
						{#if chapter.content_md}
							<div>{@html renderSafeMarkdown(chapter.content_md)}</div>
						{:else}
							<p class="text-(--netz-text-muted) italic">No content available for this chapter.</p>
						{/if}
					</Card>
				</div>
			{/if}
		</main>
	</div>
</div>

<!-- BL-09: Evidence Pack Inspector Sheet -->
<Sheet bind:open={showEvidenceSheet} side="right">
	{#if evidenceChapter}
		<div class="space-y-5">
			<!-- Sheet header -->
			<div>
				<h3 class="text-base font-semibold text-(--netz-text-primary)">
					Evidence Pack
				</h3>
				<p class="mt-1 text-sm text-(--netz-text-secondary)">
					{formatChapterTitle(evidenceChapter.chapter_tag)}
				</p>
			</div>

			<!-- Critic status summary -->
			<div class="rounded-md border border-(--netz-border-subtle) bg-(--netz-surface-raised) px-4 py-3 text-sm">
				<div class="flex items-center justify-between">
					<span class="text-(--netz-text-secondary)">Critic status</span>
					<span class="font-medium text-(--netz-text-primary) capitalize">{evidenceChapter.critic_status}</span>
				</div>
				<div class="mt-1 flex items-center justify-between">
					<span class="text-(--netz-text-secondary)">Critic iterations</span>
					<span class="font-medium text-(--netz-text-primary)">{evidenceChapter.critic_iterations}</span>
				</div>
			</div>

			{#if hasEvidenceData}
				<!-- Evidence references -->
				{#if evidenceEntries.length > 0}
					<div>
						<h4 class="mb-2 text-xs font-semibold uppercase tracking-wide text-(--netz-text-muted)">
							Evidence References
						</h4>
						<ul class="space-y-2">
							{#each evidenceEntries as entry (entry.key)}
								<li class="rounded-md border border-(--netz-border-subtle) bg-(--netz-surface-base) px-3 py-2">
									<p class="text-xs text-(--netz-text-muted) break-all">{entry.key}</p>
									<p class="mt-0.5 text-sm text-(--netz-text-primary) break-words">{entry.value}</p>
								</li>
							{/each}
						</ul>
					</div>
				{/if}

				<!-- Quant data context -->
				{#if quantEntries.length > 0}
					<div>
						<h4 class="mb-2 text-xs font-semibold uppercase tracking-wide text-(--netz-text-muted)">
							Quantitative Context
						</h4>
						<ul class="space-y-2">
							{#each quantEntries as entry (entry.key)}
								<li class="rounded-md border border-(--netz-border-subtle) bg-(--netz-surface-base) px-3 py-2">
									<p class="text-xs text-(--netz-text-muted) break-all">{entry.key}</p>
									<p class="mt-0.5 text-sm text-(--netz-text-primary) break-words">{entry.value}</p>
								</li>
							{/each}
						</ul>
					</div>
				{/if}
			{:else}
				<!-- Empty state -->
				<div class="rounded-md border border-(--netz-border-subtle) bg-(--netz-surface-raised) px-4 py-6 text-center">
					<p class="text-sm text-(--netz-text-muted)">No evidence sources recorded for this chapter.</p>
				</div>
			{/if}
		</div>
	{/if}
</Sheet>

<ConfirmDialog
	bind:open={showRegenConfirm}
	title="Regenerate Report"
	message="This will regenerate all chapters. Continue?"
	confirmLabel="Regenerate"
	confirmVariant="default"
	onConfirm={regenerate}
	onCancel={() => showRegenConfirm = false}
/>

<!-- Approve DD Report (BL-17: includes AI recommendation metadata + override warning) -->
<ConsequenceDialog
	bind:open={showApproveDialog}
	title="Approve DD Report"
	impactSummary="This report will become visible to investors upon approval."
	confirmLabel="Approve for Distribution"
	requireRationale={true}
	rationaleMinLength={10}
	rationalePlaceholder={isApproveOverride
		? "This overrides the AI recommendation. Explain the basis for approval despite the AI assessment..."
		: "Explain why this report is ready for investor distribution..."}
	metadata={approveMetadata}
	onConfirm={approveReport}
	onCancel={() => showApproveDialog = false}
>
	{#snippet consequenceList()}
		<ul class="list-disc space-y-1 pl-4 text-sm text-(--netz-text-secondary)">
			<li>Report will be published to investor portal</li>
			<li>Approval decision is recorded in audit trail</li>
			<li>This action cannot be undone without admin intervention</li>
		</ul>
	{/snippet}
	{#snippet footer({ canConfirm, submitting })}
		{#if isApproveOverride}
			<div
				class="flex items-start gap-3 rounded-lg border px-4 py-3"
				style="border-color: var(--netz-warning); background-color: color-mix(in srgb, var(--netz-warning) 8%, var(--netz-surface));"
			>
				<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--netz-warning)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="mt-0.5 shrink-0" aria-hidden="true">
					<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/>
					<path d="M12 9v4"/><path d="M12 17h.01"/>
				</svg>
				<div>
					<p class="text-sm font-semibold" style="color: var(--netz-warning);">Override detected</p>
					<p class="mt-0.5 text-sm text-(--netz-text-secondary)">
						The AI recommended <strong>{anchorLabel(decisionAnchor)}</strong> but you are approving.
						Your rationale will be flagged as an override in the audit trail.
					</p>
				</div>
			</div>
		{/if}
	{/snippet}
</ConsequenceDialog>

<!-- Reject DD Report (BL-17: includes AI recommendation metadata + override warning) -->
<ConsequenceDialog
	bind:open={showRejectDialog}
	title="Reject DD Report"
	impactSummary="This report will return to draft status."
	destructive={true}
	confirmLabel="Confirm Rejection"
	requireRationale={true}
	rationaleMinLength={10}
	rationalePlaceholder={isRejectOverride
		? "This overrides the AI recommendation. Explain the basis for rejection despite the AI assessment..."
		: "Explain what needs to be revised..."}
	metadata={rejectMetadata}
	onConfirm={rejectReport}
	onCancel={() => showRejectDialog = false}
>
	{#snippet consequenceList()}
		<ul class="list-disc space-y-1 pl-4 text-sm text-(--netz-text-secondary)">
			<li>Report returns to draft status</li>
			<li>Author will be notified of rejection</li>
			<li>Investor distribution is blocked until re-approval</li>
		</ul>
	{/snippet}
	{#snippet footer({ canConfirm, submitting })}
		{#if isRejectOverride}
			<div
				class="flex items-start gap-3 rounded-lg border px-4 py-3"
				style="border-color: var(--netz-warning); background-color: color-mix(in srgb, var(--netz-warning) 8%, var(--netz-surface));"
			>
				<svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--netz-warning)" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="mt-0.5 shrink-0" aria-hidden="true">
					<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/>
					<path d="M12 9v4"/><path d="M12 17h.01"/>
				</svg>
				<div>
					<p class="text-sm font-semibold" style="color: var(--netz-warning);">Override detected</p>
					<p class="mt-0.5 text-sm text-(--netz-text-secondary)">
						The AI recommended <strong>{anchorLabel(decisionAnchor)}</strong> but you are rejecting.
						Your rationale will be flagged as an override in the audit trail.
					</p>
				</div>
			</div>
		{/if}
	{/snippet}
</ConsequenceDialog>
