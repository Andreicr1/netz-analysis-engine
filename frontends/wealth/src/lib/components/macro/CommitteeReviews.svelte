<!--
  CommitteeReviews — list + generate + approve/reject with role-gating.
  Spec: WM-S1-05
-->
<script lang="ts">
	import { getContext } from "svelte";
	import { ConsequenceDialog, StatusBadge, formatDate, formatDateTime } from "@netz/ui";
	import { createClientApiClient } from "$lib/api/client";

	interface MacroReview {
		id: string;
		status: string;
		is_emergency: boolean;
		as_of_date: string;
		report_json: Record<string, unknown>;
		approved_by: string | null;
		approved_at: string | null;
		decision_rationale: string | null;
		created_at: string;
		created_by: string | null;
	}

	interface Props {
		initialReviews?: MacroReview[];
		actorRole: string | null;
	}

	let { initialReviews = [], actorRole }: Props = $props();

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let reviews = $derived.by(() => {
		if (_reviewsOverride !== null) return _reviewsOverride;
		return [...initialReviews];
	});
	let _reviewsOverride = $state<MacroReview[] | null>(null);

	function setReviews(next: MacroReview[]) {
		_reviewsOverride = next;
	}
	let loading = $state(false);
	let generating = $state(false);
	let generateError = $state<string | null>(null);
	let actionError = $state<string | null>(null);
	let processingId = $state<string | null>(null);

	let showGenerateDialog = $state(false);
	let showApproveDialog = $state(false);
	let showRejectDialog = $state(false);
	let targetReview = $state<MacroReview | null>(null);

	const IC_ROLES = ["investment_team", "analyst", "portfolio_manager", "director", "admin"];
	const APPROVER_ROLES = ["director", "admin"];
	let canGenerate = $derived(actorRole !== null && IC_ROLES.includes(actorRole));
	let canApprove = $derived(actorRole !== null && APPROVER_ROLES.includes(actorRole));

	async function fetchReviews() {
		loading = true;
		try {
			const api = createClientApiClient(getToken);
			setReviews(await api.get<MacroReview[]>("/macro/reviews", { limit: 20 }));
		} catch {
			setReviews([]);
		} finally {
			loading = false;
		}
	}

	async function handleGenerate() {
		generating = true;
		generateError = null;
		try {
			const api = createClientApiClient(getToken);
			const newReview = await api.post<MacroReview>("/macro/reviews/generate", {});
			setReviews([newReview, ...reviews]);
			showGenerateDialog = false;
		} catch (e) {
			generateError = e instanceof Error ? e.message : "Failed to generate review.";
		} finally {
			generating = false;
		}
	}

	function openApprove(review: MacroReview) {
		targetReview = review;
		actionError = null;
		showApproveDialog = true;
	}

	function openReject(review: MacroReview) {
		targetReview = review;
		actionError = null;
		showRejectDialog = true;
	}

	async function handleApprove(payload: { rationale?: string }) {
		if (!targetReview) return;
		processingId = targetReview.id;
		actionError = null;
		try {
			const api = createClientApiClient(getToken);
			const updated = await api.patch<MacroReview>(
				`/macro/reviews/${targetReview.id}/approve`,
				{ decision_rationale: payload.rationale ?? "" },
			);
			setReviews(reviews.map((r) => (r.id === updated.id ? updated : r)));
			showApproveDialog = false;
		} catch (e) {
			if (e instanceof Error && e.message.includes("409")) {
				actionError = "Review already processed by another user.";
				await fetchReviews();
			} else {
				actionError = e instanceof Error ? e.message : "Failed to approve.";
			}
		} finally {
			processingId = null;
		}
	}

	async function handleReject(payload: { rationale?: string }) {
		if (!targetReview) return;
		processingId = targetReview.id;
		actionError = null;
		try {
			const api = createClientApiClient(getToken);
			const updated = await api.patch<MacroReview>(
				`/macro/reviews/${targetReview.id}/reject`,
				{ decision_rationale: payload.rationale ?? "" },
			);
			setReviews(reviews.map((r) => (r.id === updated.id ? updated : r)));
			showRejectDialog = false;
		} catch (e) {
			if (e instanceof Error && e.message.includes("409")) {
				actionError = "Review already processed by another user.";
				await fetchReviews();
			} else {
				actionError = e instanceof Error ? e.message : "Failed to reject.";
			}
		} finally {
			processingId = null;
		}
	}

	function statusType(s: string): string {
		if (s === "approved") return "success";
		if (s === "rejected") return "danger";
		if (s === "pending") return "warning";
		return "default";
	}

	function reportSummary(review: MacroReview): string {
		const rj = review.report_json;
		if (typeof rj === "object" && rj !== null) {
			const summary = (rj as Record<string, unknown>).executive_summary
				?? (rj as Record<string, unknown>).summary
				?? "";
			if (typeof summary === "string" && summary.length > 0) {
				return summary.length > 200 ? summary.slice(0, 200) + "…" : summary;
			}
		}
		return "Committee review generated.";
	}
</script>

<section class="reviews-section">
	<div class="reviews-header">
		<h3 class="reviews-title">Committee Reviews</h3>
		{#if canGenerate}
			<button class="reviews-generate-btn" onclick={() => (showGenerateDialog = true)} disabled={generating}>
				{generating ? "Generating…" : "Generate Review"}
			</button>
		{/if}
	</div>

	{#if generateError}
		<div class="reviews-error">{generateError}</div>
	{/if}
	{#if actionError}
		<div class="reviews-error">{actionError}</div>
	{/if}

	{#if loading}
		<div class="reviews-loading">Loading reviews…</div>
	{:else if reviews.length === 0}
		<div class="reviews-empty">No committee reviews yet.</div>
	{:else}
		<div class="reviews-list">
			{#each reviews as review (review.id)}
				<div class="review-card">
					<div class="review-meta">
						<span class="review-date">{formatDate(review.as_of_date)}</span>
						<StatusBadge status={review.status} type={statusType(review.status)} />
						{#if review.is_emergency}
							<span class="review-emergency">EMERGENCY</span>
						{/if}
					</div>
					<p class="review-summary">{reportSummary(review)}</p>
					<div class="review-footer">
						<span class="review-created">Created {formatDateTime(review.created_at)}</span>
						{#if review.decision_rationale}
							<span class="review-rationale" title={review.decision_rationale}>
								Rationale: {review.decision_rationale.length > 80 ? review.decision_rationale.slice(0, 80) + "…" : review.decision_rationale}
							</span>
						{/if}
					</div>
					{#if canApprove && review.status === "pending"}
						<div class="review-actions">
							<button class="action-btn action-btn--approve" onclick={() => openApprove(review)} disabled={processingId === review.id}>
								Approve
							</button>
							<button class="action-btn action-btn--reject" onclick={() => openReject(review)} disabled={processingId === review.id}>
								Reject
							</button>
						</div>
					{/if}
				</div>
			{/each}
		</div>
	{/if}
</section>

<ConsequenceDialog
	bind:open={showGenerateDialog}
	title="Generate Committee Review"
	impactSummary="This will generate a new macro committee review from the latest snapshot data. LLM content generation may take up to 60 seconds."
	confirmLabel="Generate"
	onConfirm={handleGenerate}
/>

<ConsequenceDialog
	bind:open={showApproveDialog}
	title="Approve Review"
	impactSummary="Approve this macro committee review. This action cannot be undone."
	requireRationale
	rationaleLabel="Approval rationale"
	rationalePlaceholder="Record the basis for approval…"
	rationaleMinLength={10}
	confirmLabel="Approve"
	onConfirm={(p) => handleApprove(p)}
/>

<ConsequenceDialog
	bind:open={showRejectDialog}
	title="Reject Review"
	impactSummary="Reject this macro committee review with rationale."
	destructive
	requireRationale
	rationaleLabel="Rejection rationale"
	rationalePlaceholder="Record the reason for rejection…"
	rationaleMinLength={10}
	confirmLabel="Reject"
	onConfirm={(p) => handleReject(p)}
/>

<style>
	.reviews-section {
		border: 1px solid var(--netz-border-subtle);
		border-radius: var(--netz-radius-md, 12px);
		background: var(--netz-surface-elevated);
		overflow: hidden;
	}

	.reviews-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: 8px 16px;
		border-bottom: 1px solid var(--netz-border-subtle);
		background: var(--netz-surface-alt);
	}

	.reviews-title {
		font-size: var(--netz-text-label, 0.75rem);
		font-weight: 600;
		letter-spacing: 0.04em;
		text-transform: uppercase;
		color: var(--netz-text-muted);
		margin: 0;
	}

	.reviews-generate-btn {
		padding: 4px 12px;
		font-size: var(--netz-text-label, 0.75rem);
		font-weight: 600;
		border: 1px solid var(--netz-brand-primary);
		border-radius: var(--netz-radius-sm, 6px);
		background: var(--netz-brand-primary);
		color: white;
		cursor: pointer;
		transition: opacity 150ms ease;
	}

	.reviews-generate-btn:hover {
		opacity: 0.9;
	}

	.reviews-generate-btn:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.reviews-error {
		padding: 8px 16px;
		font-size: var(--netz-text-small, 0.8125rem);
		color: var(--netz-danger);
		background: color-mix(in srgb, var(--netz-danger) 8%, transparent);
	}

	.reviews-loading,
	.reviews-empty {
		padding: 24px;
		text-align: center;
		color: var(--netz-text-muted);
		font-size: var(--netz-text-small, 0.8125rem);
	}

	.reviews-list {
		display: flex;
		flex-direction: column;
	}

	.review-card {
		padding: 12px 16px;
		border-bottom: 1px solid var(--netz-border-subtle);
	}

	.review-card:last-child {
		border-bottom: none;
	}

	.review-meta {
		display: flex;
		align-items: center;
		gap: 8px;
		margin-bottom: 4px;
	}

	.review-date {
		font-size: var(--netz-text-small, 0.8125rem);
		font-weight: 600;
		color: var(--netz-text-primary);
	}

	.review-emergency {
		font-size: 10px;
		font-weight: 700;
		color: var(--netz-danger);
		letter-spacing: 0.06em;
	}

	.review-summary {
		font-size: var(--netz-text-small, 0.8125rem);
		color: var(--netz-text-secondary);
		margin: 4px 0;
		line-height: 1.4;
	}

	.review-footer {
		display: flex;
		gap: 12px;
		font-size: 11px;
		color: var(--netz-text-muted);
		flex-wrap: wrap;
	}

	.review-created {
		white-space: nowrap;
	}

	.review-rationale {
		font-style: italic;
	}

	.review-actions {
		display: flex;
		gap: 8px;
		margin-top: 8px;
	}

	.action-btn {
		padding: 4px 12px;
		font-size: var(--netz-text-label, 0.75rem);
		font-weight: 600;
		border-radius: var(--netz-radius-sm, 6px);
		cursor: pointer;
		border: 1px solid;
		transition: opacity 150ms ease;
	}

	.action-btn:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.action-btn--approve {
		background: var(--netz-success);
		border-color: var(--netz-success);
		color: white;
	}

	.action-btn--reject {
		background: transparent;
		border-color: var(--netz-danger);
		color: var(--netz-danger);
	}

	.action-btn--reject:hover:not(:disabled) {
		background: color-mix(in srgb, var(--netz-danger) 10%, transparent);
	}
</style>
