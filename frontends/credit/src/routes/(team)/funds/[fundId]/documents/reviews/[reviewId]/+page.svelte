<!--
  Review detail — assignments, interactive checklist, decision form,
  assign reviewer, finalize, resubmit, AI analysis trigger.
-->
<script lang="ts">
	import { Card, StatusBadge, Button, Dialog, PageHeader } from "@netz/ui";
	import { resolveCreditStatus } from "$lib/utils/status-maps";
	import { ActionButton, ConfirmDialog, FormField } from "@netz/ui";
	import { ConsequenceDialog, AuditTrailPanel } from "@netz/ui";
	import { createOptimisticMutation } from "@netz/ui";
	import type { AuditTrailEntry } from "@netz/ui";
	import type { PageData } from "./$types";
	import type { ReviewChecklist } from "$lib/types/api";
	import { createClientApiClient } from "$lib/api/client";
	import { invalidateAll } from "$app/navigation";
	import { getContext } from "svelte";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let { data }: { data: PageData } = $props();

	// Typed shape from DocumentReviewOut in packages/ui/src/types/api.d.ts
	interface DocumentReviewOut {
		document_title?: string | null;
		title?: string | null;
		status: string;
		assignments?: Array<{ reviewer_name?: string | null; decision?: string | null }>;
		final_decision?: string | null;
		decided_by?: string | null;
		decided_at?: string | null;
		rationale?: string | null;
		actor_capacity?: string | null;
		submitted_by?: string;
		submitted_at?: string;
	}

	let review = $derived(data.review as DocumentReviewOut);
	let checklist = $derived((data.checklist as ReviewChecklist)?.items ?? []);
	let actionError = $state<string | null>(null);

	// ── Audit Trail — initialize from DocumentReviewOut decision fields ──
	function buildInitialAuditEntries(): AuditTrailEntry[] {
		const entries: AuditTrailEntry[] = [];
		const r = data.review as DocumentReviewOut;

		// Submission event
		if (r?.submitted_at) {
			entries.push({
				actor: r.submitted_by ?? "Submitter",
				timestamp: r.submitted_at,
				action: "Review Submitted",
				scope: `Review: ${String(r.title ?? r.document_title ?? data.reviewId)}`,
				outcome: "Submitted",
				immutable: true,
				status: "success",
			});
		}

		// Decision event (if already decided)
		if (r?.final_decision && r.decided_at) {
			const decisionLabel =
				r.final_decision === "APPROVED"
					? "Review Approved"
					: r.final_decision === "REJECTED"
						? "Review Rejected"
						: r.final_decision === "REVISION_REQUESTED"
							? "Revision Requested"
							: r.final_decision;
			entries.push({
				actor: r.decided_by ?? "Reviewer",
				actorCapacity: r.actor_capacity ?? undefined,
				timestamp: r.decided_at,
				action: decisionLabel,
				scope: `Review: ${String(r.title ?? r.document_title ?? data.reviewId)}`,
				rationale: r.rationale ?? undefined,
				outcome: decisionLabel,
				immutable: true,
				status: "success",
			});
		}

		return entries;
	}

	let auditEntries = $state<AuditTrailEntry[]>(buildInitialAuditEntries());
	// NOTE: No dedicated audit-trail GET endpoint exists for document reviews in the current API spec.
	// When the endpoint becomes available (e.g. GET /funds/{fundId}/document-reviews/{reviewId}/audit),
	// wire it here with the same $effect pattern used in the deal detail page.

	const auditMutation = createOptimisticMutation<AuditTrailEntry[]>({
		getState: () => auditEntries,
		setState: (value) => { auditEntries = value; },
		request: async (optimisticValue, _previousValue) => optimisticValue,
	});

	function appendOptimisticAuditEntry(entry: AuditTrailEntry) {
		const optimistic: AuditTrailEntry = { ...entry, status: "pending" };
		auditMutation.mutate([...auditEntries, optimistic]).catch(() => {});
	}

	function confirmAuditEntry(index: number, confirmed: Partial<AuditTrailEntry>) {
		auditEntries = auditEntries.map((e, i) =>
			i === index ? { ...e, ...confirmed, status: "success", immutable: true } : e,
		);
	}

	// ── Decision Dialog ──
	let showDecisionDialog = $state(false);
	let pendingDecision = $state<"APPROVED" | "REJECTED" | "REVISION_REQUESTED" | null>(null);
	let decisionActorCapacity = $state("");

	function openDecisionDialog(decision: "APPROVED" | "REJECTED" | "REVISION_REQUESTED") {
		pendingDecision = decision;
		decisionActorCapacity = "";
		actionError = null;
		showDecisionDialog = true;
	}

	async function submitDecision(payload: { rationale?: string }) {
		if (!pendingDecision) return;
		if (!decisionActorCapacity.trim()) {
			actionError = "Actor capacity is required before submitting a review decision.";
			throw new Error(actionError);
		}

		const decision = pendingDecision;
		const rationale = payload.rationale ?? "";
		const decisionLabel =
			decision === "APPROVED"
				? "Review Approved"
				: decision === "REJECTED"
					? "Review Rejected"
					: "Revision Requested";
		const pendingIndex = auditEntries.length;

		appendOptimisticAuditEntry({
			actor: "You",
			actorCapacity: decisionActorCapacity || undefined,
			timestamp: new Date().toISOString(),
			action: decisionLabel,
			scope: `Review: ${String(review?.title ?? review?.document_title ?? data.reviewId)}`,
			rationale,
			outcome: "Pending",
		});

		try {
			const api = createClientApiClient(getToken);
			// ReviewDecisionPayload: { decision, rationale, actor_capacity, comments? }
			await api.post(`/funds/${data.fundId}/document-reviews/${data.reviewId}/decide`, {
				decision,
				rationale,
				actor_capacity: decisionActorCapacity,
				comments: rationale || null,
			});
			showDecisionDialog = false;
			confirmAuditEntry(pendingIndex, { outcome: decisionLabel, status: "success", immutable: true });
			await invalidateAll();
		} catch (e) {
			actionError = e instanceof Error ? e.message : "Decision failed";
			auditEntries = auditEntries.filter((_, i) => i !== pendingIndex);
		}
	}

	// ── Assign Reviewer ──
	let showAssign = $state(false);
	let assignEmail = $state("");
	let assigning = $state(false);

	async function assignReviewer() {
		if (!assignEmail.trim()) return;
		assigning = true;
		try {
			const api = createClientApiClient(getToken);
			await api.post(`/funds/${data.fundId}/document-reviews/${data.reviewId}/assign`, {
				reviewer_email: assignEmail.trim(),
			});
			showAssign = false;
			assignEmail = "";
			await invalidateAll();
		} catch (e) {
			actionError = e instanceof Error ? e.message : "Assignment failed";
		} finally {
			assigning = false;
		}
	}

	// ── Finalize ──
	let showFinalize = $state(false);
	let finalizing = $state(false);

	async function finalizeReview() {
		finalizing = true;
		showFinalize = false;
		try {
			const api = createClientApiClient(getToken);
			await api.post(`/funds/${data.fundId}/document-reviews/${data.reviewId}/finalize`, {});
			await invalidateAll();
		} catch (e) {
			actionError = e instanceof Error ? e.message : "Finalization failed";
		} finally {
			finalizing = false;
		}
	}

	// ── Resubmit ──
	let resubmitting = $state(false);

	async function resubmitReview() {
		resubmitting = true;
		try {
			const api = createClientApiClient(getToken);
			await api.post(`/funds/${data.fundId}/document-reviews/${data.reviewId}/resubmit`, {});
			await invalidateAll();
		} catch (e) {
			actionError = e instanceof Error ? e.message : "Resubmission failed";
		} finally {
			resubmitting = false;
		}
	}

	// ── AI Analysis ──
	let analyzing = $state(false);

	async function triggerAIAnalysis() {
		analyzing = true;
		try {
			const api = createClientApiClient(getToken);
			await api.post(`/funds/${data.fundId}/document-reviews/${data.reviewId}/ai-analyze`, {});
			await invalidateAll();
		} catch (e) {
			actionError = e instanceof Error ? e.message : "AI analysis failed";
		} finally {
			analyzing = false;
		}
	}

	// ── Interactive Checklist ──
	let togglingItem = $state<string | null>(null);
	let showUncheckDialog = $state(false);
	let pendingUncheckId = $state<string | null>(null);

	function openUncheckDialog(itemId: string) {
		pendingUncheckId = itemId;
		actionError = null;
		showUncheckDialog = true;
	}

	async function toggleChecklistItem(itemId: string, checked: boolean) {
		if (!checked) {
			// Unchecking requires consequence dialog — gate via openUncheckDialog
			openUncheckDialog(itemId);
			return;
		}
		togglingItem = itemId;
		try {
			const api = createClientApiClient(getToken);
			await api.post(`/funds/${data.fundId}/document-reviews/${data.reviewId}/checklist/${itemId}/check`, {});
			await invalidateAll();
		} catch (e) {
			actionError = e instanceof Error ? e.message : "Failed to toggle checklist item";
		} finally {
			togglingItem = null;
		}
	}

	async function submitUncheck(payload: { rationale?: string }) {
		if (!pendingUncheckId) return;
		const itemId = pendingUncheckId;
		togglingItem = itemId;
		showUncheckDialog = false;
		const rationale = payload.rationale ?? "";
		try {
			const api = createClientApiClient(getToken);
			await api.post(`/funds/${data.fundId}/document-reviews/${data.reviewId}/checklist/${itemId}/uncheck`, {});
			appendOptimisticAuditEntry({
				actor: "You",
				timestamp: new Date().toISOString(),
				action: "Checklist Item Unchecked",
				scope: `Review: ${String(review?.title ?? review?.document_title ?? data.reviewId)}`,
				rationale,
				outcome: "Checklist Reversed",
				status: "warning",
			});
			await invalidateAll();
		} catch (e) {
			actionError = e instanceof Error ? e.message : "Failed to uncheck checklist item";
		} finally {
			togglingItem = null;
			pendingUncheckId = null;
		}
	}

	// Status-based action visibility
	let status = $derived(String(review?.status ?? ""));
	let canDecide = $derived(status === "UNDER_REVIEW");
	let canAssign = $derived(status === "PENDING_ASSIGNMENT");
	let canResubmit = $derived(status === "REVISION_REQUESTED");
	let canFinalize = $derived(status === "APPROVED" || status === "REJECTED");

	// ── Decision dialog meta ──
	let decisionTitle = $derived(
		pendingDecision === "APPROVED"
			? "Approve Document Review"
			: pendingDecision === "REJECTED"
				? "Reject Document Review"
				: "Request Revision",
	);
	let decisionImpact = $derived(
		pendingDecision === "APPROVED"
			? "Approving this review will mark the document as reviewed and approved. The decision and rationale will be recorded in the audit trail."
			: pendingDecision === "REJECTED"
				? "Rejecting this review will mark it as rejected. The decision and rationale will be recorded in the audit trail."
				: "Requesting a revision will return this review to the submitter for corrections. Provide a clear rationale.",
	);
</script>

<div class="px-6">
	<PageHeader
		title={String(review.title ?? review.document_title ?? "Review")}
		breadcrumbs={[
			{ label: "Funds", href: "/funds" },
			{ label: "Documents", href: `/funds/${data.fundId}/documents` },
			{ label: "Reviews", href: `/funds/${data.fundId}/documents/reviews` },
			{ label: String(review.title ?? review.document_title ?? "Review") },
		]}
	>
		{#snippet actions()}
			<div class="flex gap-2">
			{#if canAssign}
				<Button size="sm" variant="outline" onclick={() => showAssign = true}>
					Assign Reviewer
				</Button>
			{/if}
			{#if canDecide}
				<ActionButton size="sm" onclick={triggerAIAnalysis} loading={analyzing} loadingText="Analyzing...">
					AI Analysis
				</ActionButton>
				<Button size="sm" onclick={() => openDecisionDialog("APPROVED")}>
					Approve
				</Button>
				<Button size="sm" variant="destructive" onclick={() => openDecisionDialog("REJECTED")}>
					Reject
				</Button>
				<Button size="sm" variant="outline" onclick={() => openDecisionDialog("REVISION_REQUESTED")}>
					Request Revision
				</Button>
			{/if}
			{#if canResubmit}
				<ActionButton size="sm" onclick={resubmitReview} loading={resubmitting} loadingText="Resubmitting...">
					Resubmit
				</ActionButton>
			{/if}
			{#if canFinalize}
				<ActionButton size="sm" onclick={() => showFinalize = true} loading={finalizing} loadingText="Finalizing...">
					Finalize
				</ActionButton>
			{/if}
		</div>
		{/snippet}
	</PageHeader>

	<div class="mb-4">
		<StatusBadge status={status} type="review" resolve={resolveCreditStatus} />
	</div>

	{#if actionError}
		<div class="mb-4 rounded-md border border-(--netz-status-error) bg-(--netz-status-error)/10 p-3 text-sm text-(--netz-status-error)">
			{actionError}
			<button class="ml-2 underline" onclick={() => actionError = null}>dismiss</button>
		</div>
	{/if}

	<!-- Assignments -->
	<Card class="mb-4 p-4">
		<h3 class="mb-2 text-sm font-medium text-(--netz-text-secondary)">Assignments</h3>
		{#if Array.isArray(review.assignments) && review.assignments.length > 0}
			{#each review.assignments as assignment}
				<div class="flex items-center justify-between py-2">
					<span class="text-sm">{assignment.reviewer_name ?? "Unknown"}</span>
					<StatusBadge status={String(assignment.decision ?? "pending")} type="review" resolve={resolveCreditStatus} />
				</div>
			{/each}
		{:else}
			<p class="text-sm text-(--netz-text-muted)">No assignments yet.</p>
		{/if}
	</Card>

	<!-- Interactive Checklist -->
	<Card class="p-4">
		<h3 class="mb-2 text-sm font-medium text-(--netz-text-secondary)">Checklist</h3>
		{#if checklist.length === 0}
			<p class="text-sm text-(--netz-text-muted)">No checklist items.</p>
		{:else}
			{#each checklist as item, idx}
				<label class="flex items-center gap-2 py-1.5 {togglingItem === String(idx) ? 'opacity-50' : ''}">
					<input
						type="checkbox"
						checked={item.checked === true}
						onchange={() => toggleChecklistItem(String(idx), !item.checked)}
						disabled={togglingItem !== null}
					/>
					<span class="text-sm {item.checked ? 'line-through text-(--netz-text-muted)' : ''}">{item.description ?? ""}</span>
				</label>
			{/each}
		{/if}
	</Card>

	<!-- Audit Trail -->
	<div class="mt-4">
		<AuditTrailPanel
			entries={auditEntries}
			title="Review Decision History"
			description="Durable record of all review decisions, checklist reversals, and governance actions for this document review."
		/>
	</div>
</div>

<!-- Assign Reviewer Dialog -->
<Dialog bind:open={showAssign} title="Assign Reviewer">
	<div class="space-y-4">
		<FormField label="Reviewer Email" required>
			<input
				type="email"
				class="w-full rounded-md border border-(--netz-border) bg-(--netz-surface) px-3 py-2 text-sm text-(--netz-text-primary)"
				bind:value={assignEmail}
				placeholder="reviewer@company.com"
			/>
		</FormField>
		<div class="flex justify-end gap-2">
			<Button variant="outline" onclick={() => showAssign = false}>Cancel</Button>
			<ActionButton onclick={assignReviewer} loading={assigning} loadingText="Assigning..." disabled={!assignEmail.trim()}>
				Assign
			</ActionButton>
		</div>
	</div>
</Dialog>

<!-- Finalize Confirmation -->
<ConfirmDialog
	bind:open={showFinalize}
	title="Finalize Review"
	message="Finalizing will lock this review and its checklist. This cannot be undone. Continue?"
	confirmLabel="Finalize"
	confirmVariant="destructive"
	onConfirm={finalizeReview}
	onCancel={() => showFinalize = false}
/>

<!-- Decision Dialog (ConsequenceDialog) -->
<ConsequenceDialog
	bind:open={showDecisionDialog}
	title={decisionTitle}
	impactSummary={decisionImpact}
	destructive={pendingDecision === "REJECTED"}
	requireRationale={true}
	rationaleLabel="Decision Rationale"
	rationalePlaceholder="Record the compliance or policy basis for this review decision."
	rationaleMinLength={20}
	confirmLabel={
		pendingDecision === "APPROVED"
			? "Approve Review"
			: pendingDecision === "REJECTED"
				? "Reject Review"
				: "Request Revision"
	}
	metadata={[
		{ label: "Document", value: String(review?.title ?? review?.document_title ?? "—"), emphasis: true },
		{ label: "Decision", value: pendingDecision ?? "—" },
	]}
	onConfirm={submitDecision}
	onCancel={() => { showDecisionDialog = false; }}
>
	{#snippet consequenceList()}
		<ul class="list-disc space-y-1 pl-4">
			<li>Review will be marked as <strong>{pendingDecision}</strong></li>
			<li>Decision recorded permanently in audit trail</li>
			{#if pendingDecision === "REVISION_REQUESTED"}
				<li>Review returned to submitter for corrections</li>
			{:else if pendingDecision === "APPROVED"}
				<li>Document will be cleared for use in IC materials</li>
			{:else if pendingDecision === "REJECTED"}
				<li>Document review will be locked and marked rejected</li>
			{/if}
		</ul>
	{/snippet}
	{#snippet children()}
		<div class="space-y-4">
			<FormField label="Actor Capacity" required>
				<input
					type="text"
					class="w-full rounded-md border border-(--netz-border) bg-(--netz-surface) px-3 py-2 text-sm text-(--netz-text-primary) focus:outline-none focus:ring-2 focus:ring-(--netz-brand-secondary)"
					bind:value={decisionActorCapacity}
					placeholder="e.g. Senior Analyst, Compliance Officer"
					aria-required="true"
				/>
			</FormField>
			{#if actionError}
				<p class="text-sm text-(--netz-status-error)">{actionError}</p>
			{/if}
		</div>
	{/snippet}
</ConsequenceDialog>

<!-- Checklist Uncheck Dialog (ConsequenceDialog — gate reversal) -->
<ConsequenceDialog
	bind:open={showUncheckDialog}
	title="Reverse Checklist Item"
	impactSummary="Reverter este item exige justificativa. Unchecking a completed checklist item will mark it as incomplete. This reversal will be recorded in the audit trail."
	destructive={false}
	requireRationale={true}
	rationaleLabel="Reversal Rationale"
	rationalePlaceholder="Record the reason for reversing this completed checklist item."
	rationaleMinLength={20}
	confirmLabel="Reverse Item"
	onConfirm={submitUncheck}
	onCancel={() => { showUncheckDialog = false; pendingUncheckId = null; }}
>
	{#snippet consequenceList()}
		<ul class="list-disc space-y-1 pl-4">
			<li>This will revert the checklist item and require re-review</li>
			<li>Reversal will be recorded in the audit trail</li>
		</ul>
	{/snippet}
</ConsequenceDialog>
