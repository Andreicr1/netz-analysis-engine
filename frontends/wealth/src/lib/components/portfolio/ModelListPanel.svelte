<!--
  ModelListPanel — Clickable list of model portfolios in the sidebar.
  Selecting a model updates the global workspace state.
-->
<script lang="ts">
	import { StatusBadge, formatDateTime, EmptyState } from "@investintell/ui";
	import type { ModelPortfolio } from "$lib/types/model-portfolio";
	import { profileColor } from "$lib/types/model-portfolio";
	import { workspace } from "$lib/state/portfolio-workspace.svelte";

	let { portfolios }: { portfolios: ModelPortfolio[] } = $props();
</script>

{#if portfolios.length === 0}
	<div class="p-4">
		<EmptyState title="No model portfolios" message="Create a strategy to begin." />
	</div>
{:else}
	<ul class="model-list">
		{#each portfolios as mp (mp.id)}
			<li>
				<button
					class="model-item"
					class:active={mp.id === workspace.portfolioId}
					onclick={() => workspace.selectPortfolio(mp)}
				>
					<div class="model-item-header">
						<span class="model-profile" style:color={profileColor(mp.profile)}>
							{mp.profile}
						</span>
						<StatusBadge status={mp.status} />
					</div>

					<span class="model-name">{mp.display_name}</span>

					<div class="model-meta">
						{#if mp.fund_selection_schema}
							<span>{mp.fund_selection_schema.funds.length} funds</span>
						{/if}
						{#if mp.benchmark_composite}
							<span>{mp.benchmark_composite}</span>
						{/if}
					</div>

					<span class="model-date">{formatDateTime(mp.created_at)}</span>
				</button>
			</li>
		{/each}
	</ul>
{/if}

<style>
	.model-list {
		list-style: none;
		padding: 0;
		margin: 0;
	}

	.model-item {
		display: flex;
		flex-direction: column;
		gap: 4px;
		width: 100%;
		padding: var(--ii-space-stack-sm, 12px) var(--ii-space-inline-md, 16px);
		border: none;
		border-bottom: 1px solid var(--ii-border-subtle);
		background: transparent;
		text-align: left;
		cursor: pointer;
		font-family: var(--ii-font-sans);
		transition: background 100ms ease;
	}

	.model-item:hover {
		background: var(--ii-surface-alt);
	}

	.model-item.active {
		background: var(--ii-surface-alt);
		border-left: 3px solid var(--ii-primary);
	}

	.model-item-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
	}

	.model-profile {
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.06em;
	}

	.model-name {
		font-size: var(--ii-text-body, 0.9375rem);
		font-weight: 600;
		color: var(--ii-text-primary);
	}

	.model-meta {
		display: flex;
		gap: 8px;
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-muted);
	}

	.model-date {
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-muted);
	}
</style>
