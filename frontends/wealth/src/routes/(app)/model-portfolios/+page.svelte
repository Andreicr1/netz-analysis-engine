<!--
  Model Portfolios — Strategy Laboratory.
  Grid view with KPI cards per strategy (Conservative, Moderate, Growth).
-->
<script lang="ts">
	import { goto } from "$app/navigation";
	import { PageHeader, StatusBadge, EmptyState, formatDateTime, formatNumber } from "@netz/ui";
	import type { PageData } from "./$types";
	import type { ModelPortfolio } from "$lib/types/model-portfolio";
	import { profileColor } from "$lib/types/model-portfolio";

	let { data }: { data: PageData } = $props();

	let portfolios = $derived((data.portfolios ?? []) as ModelPortfolio[]);
</script>

<PageHeader title="Model Portfolios" />

<div class="mp-page">
	{#if portfolios.length === 0}
		<EmptyState title="No model portfolios" message="Create a strategy to begin portfolio construction." />
	{:else}
		<div class="mp-grid">
			{#each portfolios as mp (mp.id)}
				<button class="mp-card" onclick={() => goto(`/model-portfolios/${mp.id}`)}>
					<div class="mp-card-header">
						<span class="mp-profile" style:color={profileColor(mp.profile)}>
							{mp.profile}
						</span>
						<StatusBadge status={mp.status} />
					</div>

					<h3 class="mp-name">{mp.display_name}</h3>

					{#if mp.description}
						<p class="mp-desc">{mp.description}</p>
					{/if}

					<div class="mp-kpis">
						<div class="mp-kpi">
							<span class="mp-kpi-label">Inception NAV</span>
							<span class="mp-kpi-value">{formatNumber(mp.inception_nav)}</span>
						</div>
						{#if mp.inception_date}
							<div class="mp-kpi">
								<span class="mp-kpi-label">Inception</span>
								<span class="mp-kpi-value">{mp.inception_date}</span>
							</div>
						{/if}
						{#if mp.benchmark_composite}
							<div class="mp-kpi">
								<span class="mp-kpi-label">Benchmark</span>
								<span class="mp-kpi-value">{mp.benchmark_composite}</span>
							</div>
						{/if}
						{#if mp.fund_selection_schema}
							<div class="mp-kpi">
								<span class="mp-kpi-label">Funds</span>
								<span class="mp-kpi-value">{mp.fund_selection_schema.funds.length}</span>
							</div>
						{/if}
					</div>

					<div class="mp-card-footer">
						<span class="mp-created">{formatDateTime(mp.created_at)}</span>
					</div>
				</button>
			{/each}
		</div>
	{/if}
</div>

<style>
	.mp-page {
		padding: var(--netz-space-stack-md, 16px) var(--netz-space-inline-lg, 24px);
	}

	.mp-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
		gap: var(--netz-space-stack-md, 16px);
	}

	.mp-card {
		display: flex;
		flex-direction: column;
		border: 1px solid var(--netz-border-subtle);
		border-radius: var(--netz-radius-md, 12px);
		background: var(--netz-surface-elevated);
		text-align: left;
		cursor: pointer;
		font-family: var(--netz-font-sans);
		transition: border-color 120ms ease, box-shadow 120ms ease;
		overflow: hidden;
	}

	.mp-card:hover {
		border-color: var(--netz-border-accent);
		box-shadow: var(--netz-shadow-2);
	}

	.mp-card-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: var(--netz-space-stack-sm, 12px) var(--netz-space-inline-md, 16px);
		border-bottom: 1px solid var(--netz-border-subtle);
		background: var(--netz-surface-alt);
	}

	.mp-profile {
		font-size: var(--netz-text-label, 0.75rem);
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.06em;
	}

	.mp-name {
		padding: var(--netz-space-stack-sm, 12px) var(--netz-space-inline-md, 16px) 0;
		font-size: var(--netz-text-h4, 1.125rem);
		font-weight: 700;
		color: var(--netz-text-primary);
	}

	.mp-desc {
		padding: var(--netz-space-stack-2xs, 4px) var(--netz-space-inline-md, 16px) 0;
		font-size: var(--netz-text-small, 0.8125rem);
		color: var(--netz-text-muted);
		line-height: 1.5;
	}

	.mp-kpis {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 1px;
		margin: var(--netz-space-stack-sm, 12px) var(--netz-space-inline-md, 16px) 0;
		border: 1px solid var(--netz-border-subtle);
		border-radius: var(--netz-radius-sm, 8px);
		overflow: hidden;
		background: var(--netz-border-subtle);
	}

	.mp-kpi {
		display: flex;
		flex-direction: column;
		gap: 1px;
		padding: var(--netz-space-stack-2xs, 6px) var(--netz-space-inline-sm, 10px);
		background: var(--netz-surface-elevated);
	}

	.mp-kpi-label {
		font-size: var(--netz-text-label, 0.75rem);
		color: var(--netz-text-muted);
	}

	.mp-kpi-value {
		font-size: var(--netz-text-body, 0.9375rem);
		font-weight: 600;
		color: var(--netz-text-primary);
		font-variant-numeric: tabular-nums;
	}

	.mp-card-footer {
		padding: var(--netz-space-stack-xs, 10px) var(--netz-space-inline-md, 16px);
		margin-top: auto;
	}

	.mp-created {
		font-size: var(--netz-text-label, 0.75rem);
		color: var(--netz-text-muted);
	}
</style>
