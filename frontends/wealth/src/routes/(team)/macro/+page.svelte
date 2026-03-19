<!--
  Macro Intelligence — regional scores, regime hierarchy, committee reviews.
-->
<script lang="ts">
	import { DataCard, StatusBadge, PageHeader, SectionCard, EmptyState, Button, formatDate, formatNumber } from "@netz/ui";
	import { ActionButton, ConfirmDialog } from "@netz/ui";
	import { createClientApiClient } from "$lib/api/client";
	import { invalidateAll } from "$app/navigation";
	import { getContext } from "svelte";
	import { resolveWealthStatus } from "$lib/utils/status-maps";
	import type { PageData } from "./$types";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	import type { MacroScores, RegimeHierarchy, MacroReview } from "$lib/types/api";

	let { data }: { data: PageData } = $props();

	let scores = $derived(data.scores as MacroScores | null);
	let regime = $derived(data.regime as RegimeHierarchy | null);
	let reviews = $derived((data.reviews ?? []) as MacroReview[]);

	// ── Generate + Approve/Reject ──
	let generating = $state(false);
	let processingReviewId = $state<string | null>(null);
	let actionError = $state<string | null>(null);

	async function generateReport() {
		generating = true;
		actionError = null;
		try {
			const api = createClientApiClient(getToken);
			await api.post("/macro/reviews/generate", {});
			await invalidateAll();
		} catch (e) {
			actionError = e instanceof Error ? e.message : "Generation failed";
		} finally {
			generating = false;
		}
	}

	async function approveReview(reviewId: string) {
		processingReviewId = reviewId;
		actionError = null;
		try {
			const api = createClientApiClient(getToken);
			await api.patch(`/macro/reviews/${reviewId}/approve`, {});
			await invalidateAll();
		} catch (e) {
			actionError = e instanceof Error ? e.message : "Approval failed";
		} finally {
			processingReviewId = null;
		}
	}

	let showRejectConfirm = $state(false);
	let rejectTargetId = $state<string | null>(null);

	function confirmRejectReview(reviewId: string) {
		rejectTargetId = reviewId;
		showRejectConfirm = true;
	}

	async function rejectReview() {
		if (!rejectTargetId) return;
		processingReviewId = rejectTargetId;
		showRejectConfirm = false;
		actionError = null;
		try {
			const api = createClientApiClient(getToken);
			await api.patch(`/macro/reviews/${rejectTargetId}/reject`, {});
			await invalidateAll();
		} catch (e) {
			actionError = e instanceof Error ? e.message : "Rejection failed";
		} finally {
			processingReviewId = null;
		}
	}
</script>

<div class="space-y-(--netz-space-section-gap) p-(--netz-space-page-gutter)">
	<PageHeader title="Macro Intelligence">
		{#snippet actions()}
			<div class="flex items-center gap-2">
				<ActionButton
					onclick={generateReport}
					loading={generating}
					loadingText="Generating..."
				>
					Generate Committee Report
				</ActionButton>
				{#if regime?.global_regime}
					<StatusBadge status={regime.global_regime} resolve={resolveWealthStatus} />
				{/if}
			</div>
		{/snippet}
	</PageHeader>

	{#if actionError}
		<div class="rounded-md border border-(--netz-status-error) bg-(--netz-status-error)/10 p-3 text-sm text-(--netz-status-error)">
			{actionError}
			<button class="ml-2 underline" onclick={() => actionError = null}>dismiss</button>
		</div>
	{/if}

	<!-- Regional Scores -->
	{#if scores?.regions}
		<div class="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
			{#each scores.regions as region (region.region)}
				<DataCard
					label={region.region}
					value={formatNumber(region.score, 0, "en-US")}
					trend={region.trend === "improving" ? "up" : region.trend === "deteriorating" ? "down" : "flat"}
				/>
			{/each}
		</div>
	{/if}

	<!-- Regime Hierarchy -->
	{#if regime?.regions}
		<SectionCard title="Regional Regime Classification">
			<div class="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
				{#each regime.regions as r (r.region)}
					<div class="flex items-center justify-between rounded-md bg-(--netz-surface-alt) p-3">
						<span class="text-sm text-(--netz-text-primary)">{r.region}</span>
						<StatusBadge status={r.regime} resolve={resolveWealthStatus} />
					</div>
				{/each}
			</div>
		</SectionCard>
	{/if}

	<!-- Committee Reviews -->
	<SectionCard title="Committee Reviews">
		{#if reviews.length > 0}
			<div class="space-y-3">
				{#each reviews as review (review.id)}
					<div class="flex items-start justify-between rounded-md border border-(--netz-border) p-4">
						<div>
							<p class="text-sm text-(--netz-text-primary)">
								{review.summary ?? "Macro Committee Review"}
							</p>
							<p class="text-xs text-(--netz-text-muted)">
								{formatDate(review.created_at)}
							</p>
						</div>
						<div class="flex items-center gap-2">
							<StatusBadge status={review.status} resolve={resolveWealthStatus} />
							{#if review.status === "pending" || review.status === "draft"}
								<ActionButton
									size="sm"
									onclick={() => approveReview(review.id)}
									loading={processingReviewId === review.id}
									loadingText="..."
								>
									Approve
								</ActionButton>
								<ActionButton
									size="sm"
									variant="destructive"
									onclick={() => confirmRejectReview(review.id)}
									loading={processingReviewId === review.id}
									loadingText="..."
								>
									Reject
								</ActionButton>
							{/if}
						</div>
					</div>
				{/each}
			</div>
		{:else}
			<EmptyState title="No Reviews" message="Macro committee reviews will appear here." />
		{/if}
	</SectionCard>
</div>

<ConfirmDialog
	bind:open={showRejectConfirm}
	title="Reject Committee Review"
	message="This will reject the macro committee review. This action cannot be undone. Continue?"
	confirmLabel="Reject"
	confirmVariant="destructive"
	onConfirm={rejectReview}
	onCancel={() => { showRejectConfirm = false; rejectTargetId = null; }}
/>
