<!--
  Macro Intelligence — regional scores, regime hierarchy, committee reviews.
-->
<script lang="ts">
	import { DataCard, StatusBadge, PageHeader, EmptyState, Button } from "@netz/ui";
	import type { PageData } from "./$types";

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
</script>

<div class="space-y-6 p-6">
	<PageHeader title="Macro Intelligence">
		{#snippet actions()}
			{#if regime?.global_regime}
				<StatusBadge status={regime.global_regime} />
			{/if}
		{/snippet}
	</PageHeader>

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
		<div class="rounded-lg border border-[var(--netz-border)] bg-white p-5">
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
	<div class="rounded-lg border border-[var(--netz-border)] bg-white p-5">
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
						<StatusBadge status={review.status} />
					</div>
				{/each}
			</div>
		{:else}
			<EmptyState title="No Reviews" message="Macro committee reviews will appear here." />
		{/if}
	</div>
</div>
