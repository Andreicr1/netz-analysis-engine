<!--
  Macro Review Detail — renders a single committee review's report_json.
  Region param (from query string) scrolls to the relevant section.
-->
<script lang="ts">
	import { page } from "$app/stores";
	import { formatDate, formatNumber } from "@investintell/ui";
	import type { PageData } from "./$types";
	import type { MacroReview } from "$lib/types/macro";

	let { data }: { data: PageData } = $props();
	let review = $derived(data.review as MacroReview);
	let report = $derived(review.report_json as Record<string, unknown>);

	let highlightRegion = $derived(($page.url.searchParams.get("region") ?? "").toUpperCase());

	interface ScoreDelta {
		region: string;
		previous_score: number;
		current_score: number;
		delta: number;
		flagged: boolean;
	}

	let scoreDeltas = $derived((report.score_deltas ?? []) as ScoreDelta[]);
	let regime = $derived(report.regime as Record<string, unknown> | null);
	let stalenessAlerts = $derived((report.staleness_alerts ?? []) as string[]);
	let hasMaterialChanges = $derived(report.has_material_changes as boolean | undefined);

	function deltaColor(d: number): string {
		if (d > 5) return "var(--ii-success, #16a34a)";
		if (d < -5) return "var(--ii-danger, #dc2626)";
		return "var(--ii-text-secondary)";
	}

	function regionDisplayName(code: string): string {
		const names: Record<string, string> = { US: "United States", EUROPE: "Europe", ASIA: "Asia Pacific", EM: "Emerging Markets" };
		return names[code] ?? code;
	}
</script>

<div class="review-page">
	<div class="review-topbar">
		<a href="/macro" class="review-back">&larr; Macro Intelligence</a>
	</div>

	<h1 class="review-title">
		Macro Committee Review
		<span class="review-date">{formatDate(review.as_of_date)}</span>
	</h1>

	{#if review.is_emergency}
		<span class="review-badge review-badge--emergency">Emergency</span>
	{/if}
	<span class="review-badge review-badge--{review.status}">{review.status.replace(/_/g, " ")}</span>

	{#if hasMaterialChanges}
		<p class="review-material">Material changes detected in this period.</p>
	{/if}

	<!-- Score Deltas -->
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
							<span class="delta-curr" style:color={deltaColor(sd.delta)}>
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

	<!-- Regime -->
	{#if regime}
		<section class="review-section">
			<h2 class="review-section-title">Regime</h2>
			{#if regime.global}
				<p class="regime-global">Global: <strong>{String(regime.global).replace(/_/g, " ").toUpperCase()}</strong></p>
			{/if}
			{#if regime.regional}
				<div class="regime-grid">
					{#each Object.entries(regime.regional as Record<string, string>) as [region, regimeVal] (region)}
						<div class="regime-item">
							<span class="regime-label">{regionDisplayName(region)}</span>
							<span class="regime-value">{String(regimeVal).replace(/_/g, " ").toUpperCase()}</span>
						</div>
					{/each}
				</div>
			{/if}
		</section>
	{/if}

	<!-- Staleness Alerts -->
	{#if stalenessAlerts.length > 0}
		<section class="review-section">
			<h2 class="review-section-title">Staleness Alerts</h2>
			<ul class="alert-list">
				{#each stalenessAlerts as alert}
					<li>{alert}</li>
				{/each}
			</ul>
		</section>
	{/if}

	<!-- Approval -->
	{#if review.decision_rationale}
		<section class="review-section">
			<h2 class="review-section-title">Decision</h2>
			<p class="review-rationale">{review.decision_rationale}</p>
			{#if review.approved_by}
				<p class="review-meta">Approved by {review.approved_by} on {review.approved_at ? formatDate(review.approved_at) : "—"}</p>
			{/if}
		</section>
	{/if}
</div>

<style>
	.review-page {
		max-width: 900px;
		margin: 0 auto;
		padding: 24px;
	}

	.review-topbar {
		margin-bottom: 16px;
	}

	.review-back {
		font-size: 13px;
		color: var(--ii-brand-primary, #1447e6);
		text-decoration: none;
	}
	.review-back:hover { text-decoration: underline; }

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
	}
	.review-badge--draft { background: #f3f4f6; color: #6b7280; }
	.review-badge--published { background: #dcfce7; color: #166534; }
	.review-badge--approved { background: #dbeafe; color: #1e40af; }
	.review-badge--rejected { background: #fee2e2; color: #991b1b; }
	.review-badge--emergency { background: #fee2e2; color: #991b1b; }

	.review-material {
		font-size: 13px;
		color: var(--ii-warning, #d97706);
		font-weight: 600;
		margin-bottom: 16px;
	}

	.review-section {
		margin-top: 24px;
		padding-top: 20px;
		border-top: 1px solid var(--ii-border-subtle, #e5e7eb);
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
		border: 1px solid var(--ii-border-subtle, #e5e7eb);
		border-radius: 10px;
		background: var(--ii-surface, #fff);
	}
	.delta-card--highlight {
		border-color: var(--ii-brand-primary, #1447e6);
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
		background: #fee2e2;
		color: #991b1b;
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
