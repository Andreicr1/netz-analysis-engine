<!--
  Exposure — Geographic x Sector heatmap with alpha-opacity concentration.
  Pure CSS grid heatmap, no chart library.
-->
<script lang="ts">
	import { PageHeader, EmptyState, formatPercent } from "@netz/ui";
	import { goto } from "$app/navigation";
	import type { PageData } from "./$types";
	import type { ExposureMatrix } from "$lib/types/exposure";

	let { data }: { data: PageData } = $props();

	let geographic = $derived(data.geographic as ExposureMatrix | null);
	let sector = $derived(data.sector as ExposureMatrix | null);
	let portfolioCount = $derived((data.portfolioCount ?? 0) as number);

	let bothEmpty = $derived(
		(!geographic || geographic.rows.length === 0) &&
		(!sector || sector.rows.length === 0)
	);

	let activeDimension = $state<"geographic" | "sector">("geographic");
	let activeMatrix = $derived(activeDimension === "geographic" ? geographic : sector);

	// Compute max value for opacity scaling
	let maxValue = $derived.by(() => {
		if (!activeMatrix) return 0.01;
		let max = 0;
		for (const row of activeMatrix.data) {
			for (const v of row) {
				if (v > max) max = v;
			}
		}
		return max || 0.01;
	});

	function cellOpacity(value: number): number {
		return Math.max(0.08, value / maxValue);
	}

	function cellColor(value: number): string {
		const alpha = cellOpacity(value);
		return `color-mix(in srgb, var(--netz-brand-primary) ${(alpha * 100).toFixed(0)}%, transparent)`;
	}
</script>

<PageHeader title="Exposure">
	{#snippet actions()}
		<div class="exp-toggle">
			<button
				class="exp-toggle-btn"
				class:exp-toggle-btn--active={activeDimension === "geographic"}
				onclick={() => activeDimension = "geographic"}
			>Geographic</button>
			<button
				class="exp-toggle-btn"
				class:exp-toggle-btn--active={activeDimension === "sector"}
				onclick={() => activeDimension = "sector"}
			>Sector</button>
		</div>
	{/snippet}
</PageHeader>

<div class="exp-page">
	{#if bothEmpty}
		{#if portfolioCount === 0}
			<EmptyState
				title="No portfolios configured"
				description="Configure a Model Portfolio before viewing exposure."
				actionLabel="Go to Model Portfolios"
				onAction={() => goto("/model-portfolios")}
			/>
		{:else}
			<EmptyState
				title="No positions allocated"
				description="Portfolios exist but have no calculated positions yet. Exposure will appear after the next engine cycle."
			/>
		{/if}
	{:else if activeMatrix && activeMatrix.rows.length > 0 && activeMatrix.columns.length > 0}
		<div class="heatmap" style:--cols={activeMatrix.columns.length + 1}>
			<!-- Header row: empty corner + column labels -->
			<div class="hm-corner"></div>
			{#each activeMatrix.columns as col (col)}
				<div class="hm-col-label">{col}</div>
			{/each}

			<!-- Data rows -->
			{#each activeMatrix.rows as row, ri (row)}
				<div class="hm-row-label">{row}</div>
				{#each activeMatrix.columns as col, ci (col)}
					{@const value = activeMatrix.data[ri]?.[ci] ?? 0}
					<div
						class="hm-cell"
						style:background={cellColor(value)}
						title="{row} / {col}: {(value * 100).toFixed(1)}%"
					>
						{#if value > 0.005}
							<span class="hm-cell-value">{(value * 100).toFixed(1)}</span>
						{/if}
					</div>
				{/each}
			{/each}
		</div>

		<!-- Legend -->
		<div class="hm-legend">
			<span class="hm-legend-label">Low</span>
			<div class="hm-legend-bar">
				{#each Array(10) as _, i (i)}
					<div class="hm-legend-step" style:opacity={(i + 1) / 10}></div>
				{/each}
			</div>
			<span class="hm-legend-label">High</span>
		</div>
	{:else}
		<div class="exp-empty">No exposure data available for {activeDimension} dimension.</div>
	{/if}
</div>

<style>
	.exp-page {
		padding: var(--netz-space-stack-md, 16px) var(--netz-space-inline-lg, 24px);
	}

	.exp-toggle {
		display: flex;
		border: 1px solid var(--netz-border);
		border-radius: var(--netz-radius-sm, 8px);
		overflow: hidden;
	}

	.exp-toggle-btn {
		padding: 4px 14px;
		border: none;
		border-right: 1px solid var(--netz-border);
		background: transparent;
		color: var(--netz-text-secondary);
		font-size: var(--netz-text-small, 0.8125rem);
		font-weight: 600;
		font-family: var(--netz-font-sans);
		cursor: pointer;
		transition: background-color 120ms ease, color 120ms ease;
	}

	.exp-toggle-btn:last-child { border-right: none; }
	.exp-toggle-btn:hover { background: var(--netz-surface-alt); }

	.exp-toggle-btn--active {
		background: color-mix(in srgb, var(--netz-brand-primary) 12%, transparent);
		color: var(--netz-brand-primary);
	}

	/* ── Heatmap grid ────────────────────────────────────────────────────── */
	.heatmap {
		display: grid;
		grid-template-columns: 140px repeat(var(--cols, 5), 1fr);
		gap: 2px;
		border: 1px solid var(--netz-border-subtle);
		border-radius: var(--netz-radius-md, 12px);
		overflow: hidden;
		background: var(--netz-border-subtle);
	}

	.hm-corner {
		background: var(--netz-surface-alt);
		padding: var(--netz-space-stack-2xs, 8px);
	}

	.hm-col-label {
		background: var(--netz-surface-alt);
		padding: var(--netz-space-stack-2xs, 8px) var(--netz-space-inline-xs, 6px);
		font-size: var(--netz-text-label, 0.75rem);
		font-weight: 600;
		color: var(--netz-text-muted);
		text-align: center;
		text-transform: uppercase;
		letter-spacing: 0.02em;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.hm-row-label {
		background: var(--netz-surface-alt);
		padding: var(--netz-space-stack-2xs, 8px) var(--netz-space-inline-sm, 12px);
		font-size: var(--netz-text-small, 0.8125rem);
		font-weight: 500;
		color: var(--netz-text-primary);
		display: flex;
		align-items: center;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.hm-cell {
		display: flex;
		align-items: center;
		justify-content: center;
		min-height: 44px;
		background: var(--netz-surface-elevated);
		transition: background-color 200ms ease;
	}

	.hm-cell-value {
		font-size: var(--netz-text-label, 0.75rem);
		font-weight: 600;
		color: var(--netz-text-primary);
		font-variant-numeric: tabular-nums;
	}

	/* Legend */
	.hm-legend {
		display: flex;
		align-items: center;
		gap: var(--netz-space-inline-sm, 8px);
		margin-top: var(--netz-space-stack-md, 16px);
		justify-content: center;
	}

	.hm-legend-label {
		font-size: var(--netz-text-label, 0.75rem);
		color: var(--netz-text-muted);
	}

	.hm-legend-bar {
		display: flex;
		gap: 1px;
		border-radius: 3px;
		overflow: hidden;
	}

	.hm-legend-step {
		width: 20px;
		height: 12px;
		background: var(--netz-brand-primary);
	}

	.exp-empty {
		padding: var(--netz-space-stack-xl, 48px);
		text-align: center;
		color: var(--netz-text-muted);
		font-size: var(--netz-text-body, 0.9375rem);
	}

	@media (max-width: 768px) {
		.heatmap {
			grid-template-columns: 100px repeat(var(--cols, 5), 1fr);
		}
	}
</style>
