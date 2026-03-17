<!--
  Review detail — assignments, checklist, decision form.
-->
<script lang="ts">
	import { Card, StatusBadge, Button } from "@netz/ui";
	import type { PageData } from "./$types";
	import type { ReviewDetail, ReviewChecklist, ReviewAssignment, ChecklistItem } from "$lib/types/api";

	let { data }: { data: PageData } = $props();

	let review = $derived(data.review as ReviewDetail);
	let checklist = $derived((data.checklist as ReviewChecklist)?.items ?? []);
</script>

<div class="p-6">
	<div class="mb-4 flex items-center justify-between">
		<div>
			<h2 class="text-xl font-semibold text-[var(--netz-text-primary)]">
				{review.document_title ?? "Review"}
			</h2>
			<StatusBadge status={String(review.status)} type="review" />
		</div>
		<!-- Review decision buttons — backend endpoints not yet implemented (gap: no POST /reviews/{id}/decision route) -->
		<div class="flex gap-2">
			<Button variant="outline" disabled>Approve</Button>
			<Button variant="outline" disabled>Reject</Button>
			<Button variant="outline" disabled>Request Revision</Button>
		</div>
	</div>

	<!-- Assignments -->
	<Card class="mb-4 p-4">
		<h3 class="mb-2 text-sm font-medium text-[var(--netz-text-secondary)]">Assignments</h3>
		{#if Array.isArray(review.assignments)}
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

	<!-- Checklist -->
	<Card class="p-4">
		<h3 class="mb-2 text-sm font-medium text-[var(--netz-text-secondary)]">Checklist</h3>
		{#if checklist.length === 0}
			<p class="text-sm text-[var(--netz-text-muted)]">No checklist items.</p>
		{:else}
			{#each checklist as item}
				<label class="flex items-center gap-2 py-1.5">
					<input type="checkbox" checked={item.checked === true} disabled />
					<span class="text-sm">{item.description ?? ""}</span>
				</label>
			{/each}
		{/if}
	</Card>
</div>
