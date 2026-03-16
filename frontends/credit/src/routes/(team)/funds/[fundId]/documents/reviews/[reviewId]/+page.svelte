<!--
  Review detail — assignments, checklist, decision form.
-->
<script lang="ts">
	import { Card, StatusBadge, Button } from "@netz/ui";
	import type { PageData } from "./$types";

	let { data }: { data: PageData } = $props();

	let review = $derived(data.review as Record<string, unknown>);
	let checklist = $derived((data.checklist as Record<string, unknown>)?.items as unknown[] ?? []);
</script>

<div class="p-6">
	<div class="mb-4 flex items-center justify-between">
		<div>
			<h2 class="text-xl font-semibold text-[var(--netz-text-primary)]">
				{review.document_title ?? "Review"}
			</h2>
			<StatusBadge status={String(review.status)} type="review" />
		</div>
		<div class="flex gap-2">
			<Button variant="outline" onclick={() => {}}>Approve</Button>
			<Button variant="outline" onclick={() => {}}>Reject</Button>
			<Button variant="outline" onclick={() => {}}>Request Revision</Button>
		</div>
	</div>

	<!-- Assignments -->
	<Card class="mb-4 p-4">
		<h3 class="mb-2 text-sm font-medium text-[var(--netz-text-secondary)]">Assignments</h3>
		{#if Array.isArray(review.assignments)}
			{#each review.assignments as assignment}
				<div class="flex items-center justify-between py-2">
					<span class="text-sm">{(assignment as Record<string, unknown>).reviewer_name ?? "Unknown"}</span>
					<StatusBadge status={String((assignment as Record<string, unknown>).decision ?? "pending")} type="review" />
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
					<input type="checkbox" checked={(item as Record<string, unknown>).checked === true} disabled />
					<span class="text-sm">{(item as Record<string, unknown>).description ?? ""}</span>
				</label>
			{/each}
		{/if}
	</Card>
</div>
