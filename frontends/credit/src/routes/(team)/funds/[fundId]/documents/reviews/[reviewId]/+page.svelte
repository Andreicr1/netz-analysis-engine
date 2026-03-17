<!--
  Review detail — assignments, interactive checklist, decision form,
  assign reviewer, finalize, resubmit, AI analysis trigger.
-->
<script lang="ts">
	import { Card, StatusBadge, Button, Dialog } from "@netz/ui";
	import { ActionButton, ConfirmDialog, FormField } from "@netz/ui";
	import type { PageData } from "./$types";
	import type { ReviewDetail, ReviewChecklist } from "$lib/types/api";
	import { createClientApiClient } from "$lib/api/client";
	import { invalidateAll } from "$app/navigation";
	import { getContext } from "svelte";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let { data }: { data: PageData } = $props();

	let review = $derived(data.review as ReviewDetail);
	let checklist = $derived((data.checklist as ReviewChecklist)?.items ?? []);
	let loading = $state(false);
	let actionError = $state<string | null>(null);

	// ── Decision ──
	async function submitDecision(decision: "APPROVED" | "REJECTED" | "REVISION_REQUESTED") {
		loading = true;
		actionError = null;
		try {
			const api = createClientApiClient(getToken);
			await api.post(`/funds/${data.fundId}/document-reviews/${data.reviewId}/decide`, {
				decision,
				comments: null,
			});
			await invalidateAll();
		} catch (e) {
			actionError = e instanceof Error ? e.message : "Decision failed";
		} finally {
			loading = false;
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

	async function toggleChecklistItem(itemId: string, checked: boolean) {
		togglingItem = itemId;
		try {
			const api = createClientApiClient(getToken);
			const endpoint = checked ? "check" : "uncheck";
			await api.post(`/funds/${data.fundId}/document-reviews/${data.reviewId}/checklist/${itemId}/${endpoint}`, {});
			await invalidateAll();
		} catch (e) {
			actionError = e instanceof Error ? e.message : "Failed to toggle checklist item";
		} finally {
			togglingItem = null;
		}
	}

	// Status-based action visibility
	let status = $derived(String(review?.status ?? ""));
	let canDecide = $derived(status === "UNDER_REVIEW");
	let canAssign = $derived(status === "PENDING_ASSIGNMENT");
	let canResubmit = $derived(status === "REVISION_REQUESTED");
	let canFinalize = $derived(status === "APPROVED" || status === "REJECTED");
</script>

<div class="p-6">
	<div class="mb-4 flex items-center justify-between">
		<div>
			<h2 class="text-xl font-semibold text-[var(--netz-text-primary)]">
				{review.document_title ?? "Review"}
			</h2>
			<StatusBadge status={status} type="review" />
		</div>
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
				<Button size="sm" onclick={() => submitDecision("APPROVED")} disabled={loading}>
					Approve
				</Button>
				<Button size="sm" variant="destructive" onclick={() => submitDecision("REJECTED")} disabled={loading}>
					Reject
				</Button>
				<Button size="sm" variant="outline" onclick={() => submitDecision("REVISION_REQUESTED")} disabled={loading}>
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
	</div>

	{#if actionError}
		<div class="mb-4 rounded-md border border-[var(--netz-status-error)] bg-[var(--netz-status-error)]/10 p-3 text-sm text-[var(--netz-status-error)]">
			{actionError}
			<button class="ml-2 underline" onclick={() => actionError = null}>dismiss</button>
		</div>
	{/if}

	<!-- Assignments -->
	<Card class="mb-4 p-4">
		<h3 class="mb-2 text-sm font-medium text-[var(--netz-text-secondary)]">Assignments</h3>
		{#if Array.isArray(review.assignments) && review.assignments.length > 0}
			{#each review.assignments as assignment}
				<div class="flex items-center justify-between py-2">
					<span class="text-sm">{assignment.reviewer_name ?? "Unknown"}</span>
					<StatusBadge status={String(assignment.decision ?? "pending")} type="review" />
				</div>
			{/each}
		{:else}
			<p class="text-sm text-[var(--netz-text-muted)]">No assignments yet.</p>
		{/if}
	</Card>

	<!-- Interactive Checklist -->
	<Card class="p-4">
		<h3 class="mb-2 text-sm font-medium text-[var(--netz-text-secondary)]">Checklist</h3>
		{#if checklist.length === 0}
			<p class="text-sm text-[var(--netz-text-muted)]">No checklist items.</p>
		{:else}
			{#each checklist as item, idx}
				<label class="flex items-center gap-2 py-1.5 {togglingItem === String(idx) ? 'opacity-50' : ''}">
					<input
						type="checkbox"
						checked={item.checked === true}
						onchange={() => toggleChecklistItem(String(idx), !item.checked)}
						disabled={togglingItem !== null}
					/>
					<span class="text-sm {item.checked ? 'line-through text-[var(--netz-text-muted)]' : ''}">{item.description ?? ""}</span>
				</label>
			{/each}
		{/if}
	</Card>
</div>

<!-- Assign Reviewer Dialog -->
<Dialog bind:open={showAssign} title="Assign Reviewer">
	<div class="space-y-4">
		<FormField label="Reviewer Email" required>
			<input
				type="email"
				class="w-full rounded-md border border-[var(--netz-border)] bg-[var(--netz-bg-secondary)] px-3 py-2 text-sm text-[var(--netz-text-primary)]"
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
