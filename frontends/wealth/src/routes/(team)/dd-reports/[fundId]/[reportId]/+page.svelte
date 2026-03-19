<!--
  DD Report detail — chapter navigation sidebar + content display.
  Download PDF, regenerate with confirmation. Approval bar for IC members.
-->
<script lang="ts">
	import { Card, Button, EmptyState, cn, StatusBadge } from "@netz/ui";
	import { ActionButton, ConfirmDialog, ConsequenceDialog } from "@netz/ui";
	import { createClientApiClient } from "$lib/api/client";
	import { invalidateAll } from "$app/navigation";
	import { getContext } from "svelte";
	import type { PageData } from "./$types";
	import { resolveWealthStatus } from "$lib/utils/status-maps";
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

	const IC_ROLES = new Set(["admin", "super_admin", "investment_team"]);

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let { data }: { data: PageData } = $props();

	type Chapter = {
		chapter_number: number;
		title: string;
		content: string;
		status: string;
	};

	let report = $derived(data.report as Record<string, unknown>);
	let chapters = $derived((report?.chapters ?? []) as Chapter[]);
	let reportStatus = $derived((report?.status ?? "draft") as string);
	let createdBy = $derived((report?.created_by ?? null) as string | null);
	let rejectionReason = $derived((report?.rejection_reason ?? null) as string | null);
	let activeChapter = $state(0);
	let downloading = $state(false);
	let showRegenConfirm = $state(false);
	let regenerating = $state(false);
	let approving = $state(false);
	let showApproveDialog = $state(false);
	let showRejectDialog = $state(false);
	let rejecting = $state(false);
	let actionError = $state<string | null>(null);

	let canApprove = $derived(
		reportStatus === "pending_approval" &&
		IC_ROLES.has(data.actorRole) &&
		data.actorId !== createdBy
	);

	let canReject = $derived(
		reportStatus === "pending_approval" &&
		IC_ROLES.has(data.actorRole)
	);

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
		try {
			const api = createClientApiClient(getToken);
			await api.post(`/dd-reports/${data.reportId}/regenerate`, {});
			await invalidateAll();
		} catch (e) {
			actionError = e instanceof Error ? e.message : "Regeneration failed";
		} finally {
			regenerating = false;
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

	<div class="flex flex-1">
		<!-- Chapter sidebar -->
		<aside class="w-64 shrink-0 border-r border-(--netz-border) bg-(--netz-surface-panel) p-4">
			<h3 class="mb-3 text-sm font-semibold text-(--netz-text-secondary)">Chapters</h3>
			{#if chapters.length === 0}
				<p class="text-xs text-(--netz-text-muted)">No chapters yet.</p>
			{:else}
				<nav class="space-y-1">
					{#each chapters as chapter, i (chapter.chapter_number)}
						<button
							class={cn(
								"w-full rounded-md px-3 py-2 text-left text-xs transition-colors",
								activeChapter === i
									? "bg-(--netz-brand-primary)/10 text-(--netz-brand-primary) font-medium"
									: "text-(--netz-text-secondary) hover:bg-(--netz-surface-highlight)"
							)}
							onclick={() => activeChapter = i}
						>
							{chapter.chapter_number}. {chapter.title}
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
				<div class="mb-4 rounded-md border border-(--netz-status-error) bg-(--netz-status-error)/10 p-3 text-sm text-(--netz-status-error)">
					{actionError}
				</div>
			{/if}

			{#if chapters.length === 0}
				<EmptyState title="No Chapters" description="Report chapters will appear here after generation." />
			{:else if chapters[activeChapter]}
				<div>
					<h2 class="mb-4 text-xl font-semibold text-(--netz-text-primary)">
						{chapters[activeChapter]!.chapter_number}. {chapters[activeChapter]!.title}
					</h2>
					<Card class="prose prose-sm max-w-none p-6 text-(--netz-text-primary)">
						<!-- Sanitized Markdown rendering — strips scripts/handlers/javascript: -->
						<div>{@html renderSafeMarkdown(chapters[activeChapter]!.content)}</div>
					</Card>
				</div>
			{/if}
		</main>
	</div>
</div>

<ConfirmDialog
	bind:open={showRegenConfirm}
	title="Regenerate Report"
	message="This will regenerate all chapters. Continue?"
	confirmLabel="Regenerate"
	confirmVariant="default"
	onConfirm={regenerate}
	onCancel={() => showRegenConfirm = false}
/>

<!-- Approve DD Report -->
<ConsequenceDialog
	bind:open={showApproveDialog}
	title="Approve DD Report"
	impactSummary="This report will become visible to investors upon approval."
	confirmLabel="Approve for Distribution"
	requireRationale={true}
	rationaleMinLength={10}
	rationalePlaceholder="Explain why this report is ready for investor distribution..."
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
</ConsequenceDialog>

<!-- Reject DD Report -->
<ConsequenceDialog
	bind:open={showRejectDialog}
	title="Reject DD Report"
	impactSummary="This report will return to draft status."
	destructive={true}
	confirmLabel="Confirm Rejection"
	requireRationale={true}
	rationaleMinLength={10}
	rationalePlaceholder="Explain what needs to be revised..."
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
</ConsequenceDialog>
