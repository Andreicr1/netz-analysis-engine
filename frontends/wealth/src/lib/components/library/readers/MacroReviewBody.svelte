<!--
  MacroReviewBody — standalone reader for a single weekly macro
  committee review.

  Phase 0 of the Wealth Library refactor: extracted from
  routes/(app)/market/reviews/[reviewId]/+page.svelte so the same
  body powers both the legacy route and the future LibraryPreviewPane.

  Contract
  --------
  * Strictly props: only `reviewId`. Token comes from "netz:getToken".
  * Self-contained client fetch via `/macro/reviews` (the existing
    list endpoint — backend route surface is intentionally unchanged
    in this phase, see Phase 0 spec).
  * Optional `region` query-param highlighting still works in the
    legacy route because the host page reads `$page.url` and passes
    nothing — the body computes the highlight from
    `globalThis.location.search` only when running in the browser.
-->
<script lang="ts">
	import { getContext } from "svelte";
	import { formatDate, formatNumber } from "@investintell/ui";
	import { PanelEmptyState, PanelErrorState } from "@investintell/ui/runtime";
	import { createClientApiClient } from "$lib/api/client";
	import { regimeLabel } from "$lib/i18n/quant-labels";
	import type { MacroReview } from "$lib/types/macro";

	let { reviewId }: { reviewId: string } = $props();

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	// ── Self-managed review state ────────────────────────────────────
	let review = $state<MacroReview | null>(null);
	let loading = $state(true);
	let loadError = $state<string | null>(null);

	async function loadReview() {
		loading = true;
		loadError = null;
		try {
			const api = createClientApiClient(getToken);
			const reviews = await api.get<MacroReview[]>("/macro/reviews", {
				limit: 50,
			});
			review = reviews.find((r) => r.id === reviewId) ?? null;
			if (review === null) {
				loadError =
					"This committee review is not in the latest 50 entries. It may have been archived.";
			}
		} catch (err: unknown) {
			loadError =
				err instanceof Error ? err.message : "Failed to load review.";
			review = null;
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		void reviewId;
		void loadReview();
	});

	let report = $derived(
		(review?.report_json ?? {}) as Record<string, unknown>,
	);

	// Region highlight is read from the URL only on the client. The
	// body never touches `$page` so it works inside any host shell.
	let highlightRegion = $state("");
	$effect(() => {
		if (typeof globalThis !== "undefined" && globalThis.location) {
			const params = new URLSearchParams(globalThis.location.search);
			highlightRegion = (params.get("region") ?? "").toUpperCase();
		}
	});

	interface ScoreDelta {
		region: string;
		previous_score: number;
		current_score: number;
		delta: number;
		flagged: boolean;
	}

	let scoreDeltas = $derived(
		(report.score_deltas ?? []) as ScoreDelta[],
	);
	let regime = $derived(
		report.regime as Record<string, unknown> | null,
	);
	let stalenessAlerts = $derived(
		(report.staleness_alerts ?? []) as string[],
	);
	let hasMaterialChanges = $derived(
		report.has_material_changes as boolean | undefined,
	);

	function deltaColor(d: number): string {
		if (d > 5) return "var(--ii-success)";
		if (d < -5) return "var(--ii-danger)";
		return "var(--ii-text-secondary)";
	}

	function regionDisplayName(code: string): string {
		const names: Record<string, string> = {
			US: "United States",
			EUROPE: "Europe",
			ASIA: "Asia Pacific",
			EM: "Emerging Markets",
		};
		return names[code] ?? code;
	}
</script>

{#if loading && review === null}
	<PanelEmptyState
		title="Loading committee review"
		message="Fetching the review from the server..."
	/>
{:else if loadError}
	<PanelErrorState
		title="Unable to load committee review"
		message={loadError}
		onRetry={loadReview}
	/>
{:else if review === null}
	<PanelEmptyState
		title="Review unavailable"
		message="This committee review is not available."
	/>
{:else}
	<div class="review-page">
		<h1 class="review-title">
			Macro Committee Review
			<span class="review-date">{formatDate(review.as_of_date)}</span>
		</h1>

		{#if review.is_emergency}
			<span class="review-badge review-badge--emergency">Emergency</span>
		{/if}
		<span class="review-badge review-badge--{review.status}">
			{review.status.replace(/_/g, " ")}
		</span>

		{#if hasMaterialChanges}
			<p class="review-material">Material changes detected in this period.</p>
		{/if}

		{#if scoreDeltas.length > 0}
			<section class="review-section">
				<h2 class="review-section-title">Regional Score Changes</h2>
				<div class="delta-grid">
					{#each scoreDeltas as sd (sd.region)}
						<div
							class="delta-card"
							class:delta-card--highlight={sd.region === highlightRegion}
						>
							<span class="delta-region">{regionDisplayName(sd.region)}</span>
							<div class="delta-scores">
								<span class="delta-prev">{formatNumber(sd.previous_score, 0)}</span>
								<span class="delta-arrow">&rarr;</span>
								<span
									class="delta-curr"
									style:color={deltaColor(sd.delta)}
								>
									{formatNumber(sd.current_score, 0)}
								</span>
							</div>
							<span class="delta-change" style:color={deltaColor(sd.delta)}>
								{sd.delta > 0 ? "+" : ""}{formatNumber(sd.delta, 1)}
							</span>
							{#if sd.flagged}
								<span class="delta-flag">Flagged</span>
							{/if}
						</div>
					{/each}
				</div>
			</section>
		{/if}

		{#if regime}
			<section class="review-section">
				<h2 class="review-section-title">Market Regime</h2>
				{#if regime.global}
					<p class="regime-global">
						Global: <strong>{regimeLabel(String(regime.global))}</strong>
					</p>
				{/if}
				{#if regime.regional}
					<div class="regime-grid">
						{#each Object.entries(regime.regional as Record<string, string>) as [region, regimeVal] (region)}
							<div class="regime-item">
								<span class="regime-label">{regionDisplayName(region)}</span>
								<span class="regime-value">{regimeLabel(regimeVal)}</span>
							</div>
						{/each}
					</div>
				{/if}
			</section>
		{/if}

		{#if stalenessAlerts.length > 0}
			<section class="review-section">
				<h2 class="review-section-title">Staleness Alerts</h2>
				<ul class="alert-list">
					{#each stalenessAlerts as alert (alert)}
						<li>{alert}</li>
					{/each}
				</ul>
			</section>
		{/if}

		{#if review.decision_rationale}
			<section class="review-section">
				<h2 class="review-section-title">Decision</h2>
				<p class="review-rationale">{review.decision_rationale}</p>
				{#if review.approved_by}
					<p class="review-meta">
						Approved by {review.approved_by} on
						{review.approved_at ? formatDate(review.approved_at) : "—"}
					</p>
				{/if}
			</section>
		{/if}
	</div>
{/if}

<style>
	.review-page {
		max-width: 900px;
		margin: 0 auto;
		padding: 24px;
	}

	.review-title {
		font-size: 24px;
		font-weight: 800;
		color: var(--ii-text-primary);
		margin: 0 0 8px;
	}

	.review-date {
		font-size: 14px;
		font-weight: 500;
		color: var(--ii-text-muted);
		margin-left: 12px;
	}

	.review-badge {
		display: inline-block;
		padding: 2px 10px;
		border-radius: 999px;
		font-size: 11px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.5px;
		margin-right: 8px;
		margin-bottom: 16px;
		background: var(--ii-surface-alt);
		color: var(--ii-text-secondary);
	}

	.review-badge--published {
		background: color-mix(in srgb, var(--ii-success) 18%, transparent);
		color: var(--ii-success);
	}

	.review-badge--approved {
		background: color-mix(in srgb, var(--ii-brand-primary) 18%, transparent);
		color: var(--ii-brand-primary);
	}

	.review-badge--rejected,
	.review-badge--emergency {
		background: color-mix(in srgb, var(--ii-danger) 18%, transparent);
		color: var(--ii-danger);
	}

	.review-material {
		font-size: 13px;
		color: var(--ii-warning);
		font-weight: 600;
		margin-bottom: 16px;
	}

	.review-section {
		margin-top: 24px;
		padding-top: 20px;
		border-top: 1px solid var(--ii-border-subtle);
	}

	.review-section-title {
		font-size: 11px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 1px;
		color: var(--ii-text-muted);
		margin: 0 0 12px;
	}

	.delta-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
		gap: 12px;
	}

	.delta-card {
		padding: 14px;
		border: 1px solid var(--ii-border-subtle);
		border-radius: 10px;
		background: var(--ii-surface);
	}

	.delta-card--highlight {
		border-color: var(--ii-brand-primary);
		box-shadow: 0 0 0 2px color-mix(in srgb, var(--ii-brand-primary) 15%, transparent);
	}

	.delta-region {
		font-size: 14px;
		font-weight: 700;
		color: var(--ii-text-primary);
		display: block;
		margin-bottom: 8px;
	}

	.delta-scores {
		display: flex;
		align-items: center;
		gap: 8px;
		font-size: 20px;
		font-weight: 800;
	}

	.delta-prev { color: var(--ii-text-muted); }
	.delta-arrow { color: var(--ii-text-muted); font-size: 14px; }

	.delta-change {
		display: block;
		font-size: 13px;
		font-weight: 600;
		margin-top: 4px;
	}

	.delta-flag {
		display: inline-block;
		margin-top: 6px;
		padding: 1px 8px;
		border-radius: 999px;
		font-size: 10px;
		font-weight: 700;
		background: color-mix(in srgb, var(--ii-danger) 18%, transparent);
		color: var(--ii-danger);
		text-transform: uppercase;
	}

	.regime-global {
		font-size: 14px;
		color: var(--ii-text-primary);
		margin-bottom: 12px;
	}

	.regime-grid {
		display: flex;
		gap: 16px;
		flex-wrap: wrap;
	}

	.regime-item {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.regime-label {
		font-size: 11px;
		color: var(--ii-text-muted);
		font-weight: 600;
		text-transform: uppercase;
	}

	.regime-value {
		font-size: 13px;
		font-weight: 700;
		color: var(--ii-text-primary);
	}

	.alert-list {
		margin: 0;
		padding-left: 18px;
		font-size: 13px;
		color: var(--ii-text-secondary);
	}

	.alert-list li { margin-bottom: 4px; }

	.review-rationale {
		font-size: 14px;
		color: var(--ii-text-primary);
		line-height: 1.6;
	}

	.review-meta {
		font-size: 12px;
		color: var(--ii-text-muted);
		margin-top: 8px;
	}
</style>
