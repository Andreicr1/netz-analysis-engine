<!--
  CommitteeReviews — list + generate + expand report + approve/reject with role-gating.
  Spec: WM-S1-05
-->
<script lang="ts">
	import { getContext } from "svelte";
	import { goto } from "$app/navigation";
	import { ConsequenceDialog, StatusBadge, formatDate, formatDateTime, formatNumber } from "@investintell/ui";
	import { createClientApiClient } from "$lib/api/client";

	interface ScoreDelta {
		region: string;
		previous_score: number;
		current_score: number;
		delta: number;
		flagged: boolean;
	}

	interface GlobalIndicatorsDelta {
		usd_strength?: number;
		energy_stress?: number;
		commodity_stress?: number;
		geopolitical_risk_score?: number;
	}

	interface ReportJson {
		type?: string;
		as_of_date?: string;
		regime?: {
			global?: string;
			regional?: Record<string, string>;
			composition_reasons?: Record<string, string>;
		};
		score_deltas?: ScoreDelta[];
		regime_transitions?: Record<string, unknown>;
		staleness_alerts?: string[];
		global_indicators_delta?: GlobalIndicatorsDelta;
		has_material_changes?: boolean;
		[key: string]: unknown;
	}

	interface MacroReview {
		id: string;
		status: string;
		is_emergency: boolean;
		as_of_date: string;
		report_json: ReportJson;
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

	// Expandable detail
	let expandedId = $state<string | null>(null);
	function toggleExpand(id: string) {
		expandedId = expandedId === id ? null : id;
	}

	const IC_ROLES = ["investment_team", "analyst", "portfolio_manager", "director", "admin", "super_admin"];
	const APPROVER_ROLES = ["director", "admin", "super_admin"];
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
			// Auto-expand the new review
			expandedId = newReview.id;
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
			justApprovedId = updated.id;
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

	// ── PDF download ─────────────────────────────────────────────────
	let downloadingId = $state<string | null>(null);

	async function downloadReviewPdf(reviewId: string, asOfDate: string) {
		downloadingId = reviewId;
		try {
			const api = createClientApiClient(getToken);
			const blob = await api.getBlob(`/macro/reviews/${reviewId}/download`);
			const url = URL.createObjectURL(blob);
			const a = document.createElement("a");
			a.href = url;
			a.download = `macro-review-${asOfDate}.pdf`;
			a.click();
			URL.revokeObjectURL(url);
		} catch (e) {
			actionError = e instanceof Error ? e.message : "Download failed";
		} finally {
			downloadingId = null;
		}
	}

	// ── Post-approval outlook CTA ────────────────────────────────────
	let justApprovedId = $state<string | null>(null);
	let generatingOutlook = $state(false);
	let outlookError = $state<string | null>(null);

	async function generateOutlook() {
		generatingOutlook = true;
		outlookError = null;
		try {
			const api = createClientApiClient(getToken);
			const result = await api.post<{ id: string; job_id: string }>(
				"/content/outlooks",
				{},
			);
			goto(`/content/${result.id}`);
		} catch (e) {
			outlookError = e instanceof Error ? e.message : "Failed to generate outlook";
		} finally {
			generatingOutlook = false;
		}
	}

	function statusType(s: string): string {
		if (s === "approved") return "success";
		if (s === "rejected") return "danger";
		if (s === "pending") return "warning";
		return "default";
	}

	function regimeLabel(regime: string | undefined): string {
		if (!regime) return "—";
		return regime.replace(/_/g, " ");
	}

	function regimeColorVar(regime: string | undefined): string {
		if (!regime) return "var(--ii-text-muted)";
		if (regime === "CRISIS") return "var(--ii-danger)";
		if (regime === "RISK_OFF") return "var(--ii-warning)";
		return "var(--ii-success)";
	}

	function deltaSign(d: number): string {
		if (d > 0) return "+";
		return "";
	}

	function deltaColor(d: number, flagged: boolean): string {
		if (flagged) return "var(--ii-danger)";
		if (Math.abs(d) >= 3) return "var(--ii-warning)";
		return "var(--ii-text-secondary)";
	}

	function reportHeadline(rj: ReportJson): string {
		const regime = rj.regime?.global ?? "Unknown";
		const materialTag = rj.has_material_changes ? "Material changes detected" : "No material changes";
		const deltas = rj.score_deltas ?? [];
		const flagged = deltas.filter((d) => d.flagged);
		if (flagged.length > 0) {
			const regions = flagged.map((d) => d.region).join(", ");
			return `${regimeLabel(regime)} — ${materialTag}. Flagged: ${regions}`;
		}
		return `${regimeLabel(regime)} — ${materialTag}`;
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
				{@const rj = (review.report_json ?? {}) as ReportJson}
				{@const expanded = expandedId === review.id}
				<div class="review-card" class:review-card--expanded={expanded}>
					<!-- Header row — clickable to expand -->
					<button class="review-header-btn" onclick={() => toggleExpand(review.id)} type="button">
						<div class="review-meta">
							<span class="review-date">{formatDate(review.as_of_date)}</span>
							<StatusBadge status={review.status} type={statusType(review.status)} />
							{#if review.is_emergency || rj.type === "emergency"}
								<span class="review-emergency">EMERGENCY</span>
							{/if}
							<span class="review-expand-icon">{expanded ? "▾" : "▸"}</span>
						</div>
						<p class="review-headline">{reportHeadline(rj)}</p>
					</button>

					<!-- Expanded report detail -->
					{#if expanded}
						<div class="report-detail">
							<!-- Global Regime -->
							{#if rj.regime}
								<div class="report-block">
									<h4 class="report-block-title">Regime Assessment</h4>
									<div class="regime-global">
										<span class="regime-label">Global</span>
										<span class="regime-value" style:color={regimeColorVar(rj.regime.global)}>
											{regimeLabel(rj.regime.global)}
										</span>
									</div>
									{#if rj.regime.regional}
										<div class="regime-grid">
											{#each Object.entries(rj.regime.regional) as [region, regime]}
												<div class="regime-cell">
													<span class="regime-region">{region}</span>
													<span class="regime-value" style:color={regimeColorVar(regime)}>
														{regimeLabel(regime)}
													</span>
												</div>
											{/each}
										</div>
									{/if}
									{#if rj.regime.composition_reasons?.decision}
										<p class="regime-reason">{rj.regime.composition_reasons.decision}</p>
									{/if}
								</div>
							{/if}

							<!-- Regional Score Deltas -->
							{#if rj.score_deltas && rj.score_deltas.length > 0}
								<div class="report-block">
									<h4 class="report-block-title">Regional Score Changes</h4>
									<table class="delta-table">
										<thead>
											<tr>
												<th>Region</th>
												<th>Previous</th>
												<th>Current</th>
												<th>Delta</th>
											</tr>
										</thead>
										<tbody>
											{#each rj.score_deltas as d}
												<tr>
													<td class="delta-region">{d.region}</td>
													<td class="delta-num">{formatNumber(d.previous_score, 1)}</td>
													<td class="delta-num">{formatNumber(d.current_score, 1)}</td>
													<td class="delta-num" style:color={deltaColor(d.delta, d.flagged)}>
														{deltaSign(d.delta)}{formatNumber(d.delta, 2)}
														{#if d.flagged}<span class="delta-flag">!</span>{/if}
													</td>
												</tr>
											{/each}
										</tbody>
									</table>
								</div>
							{/if}

							<!-- Global Indicators Delta -->
							{#if rj.global_indicators_delta}
								<div class="report-block">
									<h4 class="report-block-title">Global Indicators</h4>
									<div class="indicators-grid">
										{#each Object.entries(rj.global_indicators_delta) as [key, val]}
											<div class="indicator-cell">
												<span class="indicator-label">{key.replace(/_/g, " ")}</span>
												<span class="indicator-value">
													{typeof val === "number" ? formatNumber(val, 2) : "—"}
												</span>
											</div>
										{/each}
									</div>
								</div>
							{/if}

							<!-- Staleness Alerts -->
							{#if rj.staleness_alerts && rj.staleness_alerts.length > 0}
								<div class="report-block">
									<h4 class="report-block-title">Stale Series ({rj.staleness_alerts.length})</h4>
									<p class="staleness-list">{rj.staleness_alerts.join(", ")}</p>
								</div>
							{/if}

							<!-- Regime Transitions -->
							{#if rj.regime_transitions && Object.keys(rj.regime_transitions).length > 0}
								<div class="report-block">
									<h4 class="report-block-title">Regime Transitions</h4>
									{#each Object.entries(rj.regime_transitions) as [region, change]}
										<p class="transition-item">
											<strong>{region}:</strong> {JSON.stringify(change)}
										</p>
									{/each}
								</div>
							{/if}
						</div>
					{/if}

					<!-- Footer + actions -->
					<div class="review-footer">
						<span class="review-created">Created {formatDateTime(review.created_at)}</span>
						{#if review.approved_by}
							<span class="review-approved-by">
								{review.status === "approved" ? "Approved" : "Rejected"} by {review.approved_by}
							</span>
						{/if}
						{#if review.decision_rationale}
							<span class="review-rationale" title={review.decision_rationale}>
								Rationale: {review.decision_rationale.length > 80 ? review.decision_rationale.slice(0, 80) + "…" : review.decision_rationale}
							</span>
						{/if}
					</div>
					<div class="review-actions">
						{#if canApprove && review.status === "pending"}
							<button class="action-btn action-btn--approve" onclick={() => openApprove(review)} disabled={processingId === review.id}>
								Approve
							</button>
							<button class="action-btn action-btn--reject" onclick={() => openReject(review)} disabled={processingId === review.id}>
								Reject
							</button>
						{/if}
						{#if review.status === "pending" || review.status === "approved"}
							<button
								class="action-btn action-btn--download"
								onclick={() => downloadReviewPdf(review.id, review.as_of_date)}
								disabled={downloadingId === review.id}
							>
								{downloadingId === review.id ? "Downloading\u2026" : "Download PDF"}
							</button>
						{/if}
					</div>
					{#if justApprovedId === review.id}
						<div class="outlook-cta">
							<p class="outlook-cta-text">Review approved. Generate the Investment Outlook for the committee?</p>
							<button
								class="action-btn action-btn--outlook"
								onclick={generateOutlook}
								disabled={generatingOutlook}
							>
								{generatingOutlook ? "Generating\u2026" : "Generate Investment Outlook"}
							</button>
							{#if outlookError}
								<p class="outlook-cta-error">{outlookError}</p>
							{/if}
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
		border: 1px solid var(--ii-border-subtle);
		border-radius: var(--ii-radius-md, 12px);
		background: var(--ii-surface-elevated);
		overflow: hidden;
	}

	.reviews-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: 8px 16px;
		border-bottom: 1px solid var(--ii-border-subtle);
		background: var(--ii-surface-alt);
	}

	.reviews-title {
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 600;
		letter-spacing: 0.04em;
		text-transform: uppercase;
		color: var(--ii-text-muted);
		margin: 0;
	}

	.reviews-generate-btn {
		padding: 4px 12px;
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 600;
		border: 1px solid var(--ii-brand-primary);
		border-radius: var(--ii-radius-sm, 6px);
		background: var(--ii-brand-primary);
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
		font-size: var(--ii-text-small, 0.8125rem);
		color: var(--ii-danger);
		background: color-mix(in srgb, var(--ii-danger) 8%, transparent);
	}

	.reviews-loading,
	.reviews-empty {
		padding: 24px;
		text-align: center;
		color: var(--ii-text-muted);
		font-size: var(--ii-text-small, 0.8125rem);
	}

	.reviews-list {
		display: flex;
		flex-direction: column;
	}

	.review-card {
		border-bottom: 1px solid var(--ii-border-subtle);
	}

	.review-card:last-child {
		border-bottom: none;
	}

	.review-card--expanded {
		background: color-mix(in srgb, var(--ii-brand-primary) 2%, transparent);
	}

	/* Clickable header */
	.review-header-btn {
		display: block;
		width: 100%;
		padding: 12px 16px 4px;
		text-align: left;
		background: none;
		border: none;
		cursor: pointer;
		font-family: var(--ii-font-sans);
	}

	.review-meta {
		display: flex;
		align-items: center;
		gap: 8px;
		margin-bottom: 4px;
	}

	.review-date {
		font-size: var(--ii-text-small, 0.8125rem);
		font-weight: 600;
		color: var(--ii-text-primary);
	}

	.review-emergency {
		font-size: 10px;
		font-weight: 700;
		color: var(--ii-danger);
		letter-spacing: 0.06em;
	}

	.review-expand-icon {
		margin-left: auto;
		font-size: 12px;
		color: var(--ii-text-muted);
	}

	.review-headline {
		font-size: var(--ii-text-small, 0.8125rem);
		color: var(--ii-text-secondary);
		margin: 0 0 4px;
		line-height: 1.4;
	}

	/* Expanded report */
	.report-detail {
		padding: 8px 16px 12px;
		display: flex;
		flex-direction: column;
		gap: 12px;
	}

	.report-block {
		border: 1px solid var(--ii-border-subtle);
		border-radius: var(--ii-radius-sm, 8px);
		overflow: hidden;
	}

	.report-block-title {
		padding: 5px 10px;
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 600;
		letter-spacing: 0.03em;
		text-transform: uppercase;
		color: var(--ii-text-muted);
		background: var(--ii-surface-alt);
		border-bottom: 1px solid var(--ii-border-subtle);
		margin: 0;
	}

	/* Regime */
	.regime-global {
		display: flex;
		justify-content: space-between;
		padding: 8px 10px;
		border-bottom: 1px solid var(--ii-border-subtle);
	}

	.regime-label {
		font-size: var(--ii-text-small, 0.8125rem);
		font-weight: 500;
		color: var(--ii-text-primary);
	}

	.regime-value {
		font-size: var(--ii-text-small, 0.8125rem);
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.03em;
	}

	.regime-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(100px, 1fr));
		gap: 0;
	}

	.regime-cell {
		display: flex;
		justify-content: space-between;
		padding: 5px 10px;
		border-bottom: 1px solid var(--ii-border-subtle);
		font-size: var(--ii-text-small, 0.8125rem);
	}

	.regime-region {
		color: var(--ii-text-muted);
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 500;
	}

	.regime-reason {
		padding: 6px 10px;
		font-size: 11px;
		color: var(--ii-text-muted);
		font-style: italic;
		margin: 0;
	}

	/* Score deltas table */
	.delta-table {
		width: 100%;
		border-collapse: collapse;
		font-size: var(--ii-text-small, 0.8125rem);
	}

	.delta-table th {
		padding: 4px 10px;
		text-align: left;
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 600;
		color: var(--ii-text-muted);
		background: var(--ii-surface-alt);
		border-bottom: 1px solid var(--ii-border-subtle);
	}

	.delta-table td {
		padding: 5px 10px;
		border-bottom: 1px solid var(--ii-border-subtle);
	}

	.delta-region {
		font-weight: 500;
		color: var(--ii-text-primary);
	}

	.delta-num {
		font-variant-numeric: tabular-nums;
		text-align: right;
	}

	.delta-flag {
		font-weight: 700;
		color: var(--ii-danger);
		margin-left: 4px;
	}

	/* Indicators */
	.indicators-grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 0;
	}

	.indicator-cell {
		display: flex;
		justify-content: space-between;
		padding: 5px 10px;
		border-bottom: 1px solid var(--ii-border-subtle);
		font-size: var(--ii-text-small, 0.8125rem);
	}

	.indicator-label {
		color: var(--ii-text-muted);
		font-size: var(--ii-text-label, 0.75rem);
		text-transform: capitalize;
	}

	.indicator-value {
		font-weight: 500;
		color: var(--ii-text-primary);
		font-variant-numeric: tabular-nums;
	}

	/* Staleness */
	.staleness-list {
		padding: 6px 10px;
		font-size: 11px;
		color: var(--ii-text-muted);
		margin: 0;
		line-height: 1.5;
		word-break: break-all;
	}

	/* Transitions */
	.transition-item {
		padding: 4px 10px;
		font-size: var(--ii-text-small, 0.8125rem);
		color: var(--ii-text-secondary);
		margin: 0;
	}

	/* Footer */
	.review-footer {
		display: flex;
		gap: 12px;
		font-size: 11px;
		color: var(--ii-text-muted);
		flex-wrap: wrap;
		padding: 4px 16px 8px;
	}

	.review-created {
		white-space: nowrap;
	}

	.review-approved-by {
		white-space: nowrap;
	}

	.review-rationale {
		font-style: italic;
	}

	.review-actions {
		display: flex;
		gap: 8px;
		padding: 0 16px 12px;
	}

	.action-btn {
		padding: 4px 12px;
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 600;
		border-radius: var(--ii-radius-sm, 6px);
		cursor: pointer;
		border: 1px solid;
		transition: opacity 150ms ease;
	}

	.action-btn:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.action-btn--approve {
		background: var(--ii-success);
		border-color: var(--ii-success);
		color: white;
	}

	.action-btn--reject {
		background: transparent;
		border-color: var(--ii-danger);
		color: var(--ii-danger);
	}

	.action-btn--reject:hover:not(:disabled) {
		background: color-mix(in srgb, var(--ii-danger) 10%, transparent);
	}

	.action-btn--download {
		background: transparent;
		border-color: var(--ii-border);
		color: var(--ii-text-secondary);
	}

	.action-btn--download:hover:not(:disabled) {
		background: var(--ii-surface-alt);
		color: var(--ii-text-primary);
	}

	/* Outlook CTA */
	.outlook-cta {
		padding: 12px 16px;
		background: color-mix(in srgb, var(--ii-brand-primary) 6%, transparent);
		border-top: 1px solid var(--ii-border-subtle);
		display: flex;
		align-items: center;
		gap: 12px;
		flex-wrap: wrap;
	}

	.outlook-cta-text {
		font-size: var(--ii-text-small, 0.8125rem);
		color: var(--ii-text-secondary);
		margin: 0;
	}

	.action-btn--outlook {
		background: var(--ii-brand-primary);
		border-color: var(--ii-brand-primary);
		color: white;
	}

	.action-btn--outlook:hover:not(:disabled) {
		opacity: 0.9;
	}

	.outlook-cta-error {
		font-size: var(--ii-text-small, 0.8125rem);
		color: var(--ii-danger);
		margin: 0;
	}
</style>
