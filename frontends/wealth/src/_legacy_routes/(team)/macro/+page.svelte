<!--
  Macro Intelligence — regional scores, regime hierarchy, committee reviews.
  Phase 3C: ConsequenceDialog for approve/reject with rationale, audit trail links.
-->
<script lang="ts">
	import { DataCard, StatusBadge, PageHeader, SectionCard, EmptyState, Button, formatDate, formatNumber } from "@netz/ui";
	import { ActionButton, ConsequenceDialog } from "@netz/ui";
	import type { ConsequenceDialogPayload } from "@netz/ui";
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
	let actionError = $state<string | null>(null);

	// ── Data Sources collapsible (Phase 3A) ──
	let dataSourcesOpen = $state(false);

	// ── ConsequenceDialog state ──
	let showApproveDialog = $state(false);
	let showRejectDialog = $state(false);
	let targetReviewId = $state<string | null>(null);
	let targetReviewSummary = $state<string>("Macro Committee Review");

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

	function openApproveDialog(review: MacroReview) {
		targetReviewId = review.id;
		targetReviewSummary = review.summary ?? "Macro Committee Review";
		showApproveDialog = true;
	}

	function openRejectDialog(review: MacroReview) {
		targetReviewId = review.id;
		targetReviewSummary = review.summary ?? "Macro Committee Review";
		showRejectDialog = true;
	}

	async function handleApprove(payload: ConsequenceDialogPayload) {
		if (!targetReviewId) return;
		actionError = null;
		try {
			const api = createClientApiClient(getToken);
			await api.patch(`/macro/reviews/${targetReviewId}/approve`, {
				decision_rationale: payload.rationale ?? "",
			});
			await invalidateAll();
		} catch (e) {
			actionError = e instanceof Error ? e.message : "Approval failed";
		}
	}

	async function handleReject(payload: ConsequenceDialogPayload) {
		if (!targetReviewId) return;
		actionError = null;
		try {
			const api = createClientApiClient(getToken);
			await api.patch(`/macro/reviews/${targetReviewId}/reject`, {
				decision_rationale: payload.rationale ?? "",
			});
			await invalidateAll();
		} catch (e) {
			actionError = e instanceof Error ? e.message : "Rejection failed";
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
						<div class="flex-1">
							<div class="flex items-center gap-2">
								<p class="text-sm font-medium text-(--netz-text-primary)">
									{review.summary ?? "Macro Committee Review"}
								</p>
								<StatusBadge status={review.status} resolve={resolveWealthStatus} />
							</div>
							<div class="mt-1 flex items-center gap-3">
								<p class="text-xs text-(--netz-text-muted)">
									{formatDate(review.created_at)}
								</p>
								<a
									href="/macro/audit?review_id={review.id}"
									class="text-xs text-(--netz-brand-secondary) hover:underline"
								>
									Audit trail
								</a>
							</div>
						</div>
						<div class="ml-4 flex items-center gap-2">
							{#if review.status === "pending" || review.status === "draft"}
								<ActionButton
									size="sm"
									onclick={() => openApproveDialog(review)}
								>
									Approve
								</ActionButton>
								<ActionButton
									size="sm"
									variant="destructive"
									onclick={() => openRejectDialog(review)}
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

	<!-- Data Sources (Phase 3A) — collapsible, lazy-loaded panels -->
	<div class="rounded-lg border border-(--netz-border)">
		<button
			class="flex w-full items-center justify-between p-4 text-left"
			onclick={() => (dataSourcesOpen = !dataSourcesOpen)}
		>
			<h3 class="text-sm font-semibold text-(--netz-text-primary)">Data Sources</h3>
			<span class="text-xs text-(--netz-text-muted)">
				{dataSourcesOpen ? "Collapse" : "Expand"}
			</span>
		</button>

		{#if dataSourcesOpen}
			<div class="space-y-(--netz-space-section-gap) border-t border-(--netz-border) p-4">
				<SectionCard title="BIS Statistics">
					{#await import("./BisPanel.svelte") then { default: BisPanel }}
						<BisPanel />
					{/await}
				</SectionCard>

				<SectionCard title="IMF World Economic Outlook">
					{#await import("./ImfPanel.svelte") then { default: ImfPanel }}
						<ImfPanel />
					{/await}
				</SectionCard>

				<SectionCard title="US Treasury">
					{#await import("./TreasuryPanel.svelte") then { default: TreasuryPanel }}
						<TreasuryPanel />
					{/await}
				</SectionCard>

				<SectionCard title="OFR Hedge Fund Monitor">
					{#await import("./OfrPanel.svelte") then { default: OfrPanel }}
						<OfrPanel />
					{/await}
				</SectionCard>
			</div>
		{/if}
	</div>
</div>

<!-- Approve ConsequenceDialog -->
<ConsequenceDialog
	bind:open={showApproveDialog}
	title="Approve Macro Review"
	impactSummary="This will approve the macro committee review for distribution. The review will become visible to portfolio managers and may influence investment decisions."
	requireRationale={true}
	rationaleLabel="Approval rationale"
	rationalePlaceholder="Provide the basis for approving this macro review (e.g., data accuracy confirmed, aligned with current market view)."
	confirmLabel="Approve review"
	metadata={[
		{ label: "Review", value: targetReviewSummary, emphasis: true },
		{ label: "Action", value: "Approve" },
	]}
	onConfirm={handleApprove}
	onCancel={() => { showApproveDialog = false; targetReviewId = null; }}
/>

<!-- Reject ConsequenceDialog -->
<ConsequenceDialog
	bind:open={showRejectDialog}
	title="Reject Macro Review"
	impactSummary="This will reject the macro committee review. A new review will need to be generated to replace it."
	destructive={true}
	requireRationale={true}
	rationaleLabel="Rejection rationale"
	rationalePlaceholder="Explain why this review is being rejected (e.g., outdated data, misaligned conclusions, factual errors)."
	confirmLabel="Reject review"
	metadata={[
		{ label: "Review", value: targetReviewSummary, emphasis: true },
		{ label: "Action", value: "Reject" },
	]}
	onConfirm={handleReject}
	onCancel={() => { showRejectDialog = false; targetReviewId = null; }}
/>
