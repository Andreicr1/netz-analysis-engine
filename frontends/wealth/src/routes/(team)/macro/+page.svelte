<!--
  Macro Intelligence — regional scores, regime hierarchy, committee reviews.
-->
<script lang="ts">
	import { DataCard, StatusBadge, PageHeader, EmptyState, Button } from "@netz/ui";
	import { ActionButton, ConfirmDialog } from "@netz/ui";
	import { createClientApiClient } from "$lib/api/client";
	import { invalidateAll } from "$app/navigation";
	import { getContext } from "svelte";
	import type { PageData } from "./$types";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let { data }: { data: PageData } = $props();

	type MacroScores = {
		regions: { region: string; score: number; trend: string }[];
		global_indicators: Record<string, number>;
	};

	type RegimeHierarchy = {
		global_regime: string;
		regions: { region: string; regime: string }[];
	};

	type MacroReview = {
		id: string;
		status: string;
		created_at: string;
		summary: string | null;
	};

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

<div class="space-y-6 p-6">
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
					<StatusBadge status={regime.global_regime} />
				{/if}
			</div>
		{/snippet}
	</PageHeader>

	{#if actionError}
		<div class="rounded-md border border-[var(--netz-status-error)] bg-[var(--netz-status-error)]/10 p-3 text-sm text-[var(--netz-status-error)]">
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
					value={region.score.toFixed(0)}
					trend={region.trend === "improving" ? "up" : region.trend === "deteriorating" ? "down" : "flat"}
				/>
			{/each}
		</div>
	{/if}

	<!-- Regime Hierarchy -->
	{#if regime?.regions}
		<div class="rounded-lg border border-[var(--netz-border)] bg-[var(--netz-surface-elevated)] p-5">
			<h3 class="mb-4 text-sm font-semibold text-[var(--netz-text-primary)]">Regional Regime Classification</h3>
			<div class="grid gap-3 md:grid-cols-2 lg:grid-cols-4">
				{#each regime.regions as r (r.region)}
					<div class="flex items-center justify-between rounded-md bg-[var(--netz-surface-alt)] p-3">
						<span class="text-sm text-[var(--netz-text-primary)]">{r.region}</span>
						<StatusBadge status={r.regime} />
					</div>
				{/each}
			</div>
		</div>
	{/if}

	<!-- Committee Reviews -->
	<div class="rounded-lg border border-[var(--netz-border)] bg-[var(--netz-surface-elevated)] p-5">
		<h3 class="mb-4 text-sm font-semibold text-[var(--netz-text-primary)]">Committee Reviews</h3>
		{#if reviews.length > 0}
			<div class="space-y-3">
				{#each reviews as review (review.id)}
					<div class="flex items-start justify-between rounded-md border border-[var(--netz-border)] p-4">
						<div>
							<p class="text-sm text-[var(--netz-text-primary)]">
								{review.summary ?? "Macro Committee Review"}
							</p>
							<p class="text-xs text-[var(--netz-text-muted)]">
								{new Date(review.created_at).toLocaleDateString()}
							</p>
						</div>
						<div class="flex items-center gap-2">
							<StatusBadge status={review.status} />
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
	</div>
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
