<!--
  ScoreBreakdownPopover — click on a fund score to see the 6 component breakdown.
  Lazy-fetches GET /instruments/{id}/risk-metrics on first click.
-->
<script lang="ts">
	import { formatNumber } from "@investintell/ui";
	import { createClientApiClient } from "$lib/api/client";
	import { getContext } from "svelte";

	interface Props {
		instrumentId: string;
		score: number;
	}

	let { instrumentId, score }: Props = $props();

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let open = $state(false);
	let loading = $state(false);
	let error = $state<string | null>(null);
	let components = $state<Record<string, number> | null>(null);

	const COMPONENT_CONFIG: Record<string, { label: string; weight: number }> = {
		return_consistency: { label: "Return Consistency", weight: 0.20 },
		risk_adjusted_return: { label: "Risk-Adjusted Return", weight: 0.25 },
		drawdown_control: { label: "Drawdown Control", weight: 0.20 },
		information_ratio: { label: "Information Ratio", weight: 0.15 },
		flows_momentum: { label: "Flows Momentum", weight: 0.10 },
		fee_efficiency: { label: "Fee Efficiency", weight: 0.10 },
	};

	async function fetchComponents() {
		if (components) return;
		loading = true;
		error = null;
		try {
			const api = createClientApiClient(getToken);
			const data = await api.get<{ score_components?: Record<string, number> }>(
				`/instruments/${instrumentId}/risk-metrics`,
			);
			components = data.score_components ?? null;
			if (!components) error = "No score components available";
		} catch (e) {
			error = e instanceof Error ? e.message : "Failed to load";
		} finally {
			loading = false;
		}
	}

	function handleClick(event: MouseEvent) {
		event.stopPropagation();
		open = !open;
		if (open && !components && !loading) fetchComponents();
	}

	function handleClickOutside(event: MouseEvent) {
		if (open) {
			open = false;
		}
	}

	function maxComponentScore(): number {
		if (!components) return 100;
		return Math.max(...Object.values(components), 1);
	}
</script>

<svelte:window onclick={handleClickOutside} />

<span class="sb-trigger" role="button" tabindex="0" onclick={handleClick} onkeydown={(e) => e.key === 'Enter' && handleClick(e as unknown as MouseEvent)} title="Click to see score breakdown">
	{score.toFixed(1)}
</span>

{#if open}
	<!-- svelte-ignore a11y_click_events_have_key_events -->
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="sb-popover" onclick={(e) => e.stopPropagation()}>
		<div class="sb-header">
			<span class="sb-title">Score Breakdown</span>
			<span class="sb-total">{score.toFixed(1)}</span>
		</div>

		{#if loading}
			<div class="sb-loading">Loading...</div>
		{:else if error}
			<div class="sb-error">{error}</div>
		{:else if components}
			<div class="sb-table">
				{#each Object.entries(COMPONENT_CONFIG) as [key, cfg] (key)}
					{@const val = components[key] ?? 0}
					{@const weighted = val * cfg.weight}
					<div class="sb-row">
						<span class="sb-component-name">{cfg.label}</span>
						<span class="sb-component-weight">{(cfg.weight * 100).toFixed(0)}%</span>
						<div class="sb-bar-track">
							<div
								class="sb-bar-fill"
								style:width="{Math.min((val / maxComponentScore()) * 100, 100)}%"
							></div>
						</div>
						<span class="sb-component-score">{formatNumber(val, 1)}</span>
						<span class="sb-component-weighted">{formatNumber(weighted, 1)}</span>
					</div>
				{/each}
			</div>
		{/if}
	</div>
{/if}

<style>
	.sb-trigger {
		cursor: pointer;
		text-decoration: underline;
		text-decoration-style: dotted;
		text-underline-offset: 3px;
		text-decoration-color: var(--ii-text-muted);
		position: relative;
	}

	.sb-trigger:hover {
		color: var(--ii-brand);
	}

	.sb-popover {
		position: absolute;
		z-index: 50;
		right: 0;
		top: 100%;
		margin-top: 4px;
		min-width: 340px;
		background: var(--ii-surface);
		border: 1px solid var(--ii-border);
		border-radius: 8px;
		box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12);
		padding: 12px;
	}

	.sb-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: 8px;
		padding-bottom: 8px;
		border-bottom: 1px solid var(--ii-border-subtle);
	}

	.sb-title {
		font-size: var(--ii-text-small, 0.8125rem);
		font-weight: 600;
		color: var(--ii-text-primary);
	}

	.sb-total {
		font-size: var(--ii-text-body, 0.875rem);
		font-weight: 700;
		color: var(--ii-brand);
		font-variant-numeric: tabular-nums;
	}

	.sb-loading, .sb-error {
		padding: 12px 0;
		text-align: center;
		font-size: var(--ii-text-small, 0.8125rem);
		color: var(--ii-text-muted);
	}

	.sb-error { color: var(--ii-danger); }

	.sb-table {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}

	.sb-row {
		display: grid;
		grid-template-columns: 1fr 28px 60px 32px 32px;
		align-items: center;
		gap: 6px;
		font-size: 11px;
		font-variant-numeric: tabular-nums;
	}

	.sb-component-name {
		color: var(--ii-text-secondary);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.sb-component-weight {
		color: var(--ii-text-muted);
		text-align: right;
		font-size: 10px;
	}

	.sb-bar-track {
		height: 6px;
		background: var(--ii-surface-alt);
		border-radius: 3px;
		overflow: hidden;
	}

	.sb-bar-fill {
		height: 100%;
		background: var(--ii-brand);
		border-radius: 3px;
		transition: width 0.2s ease;
	}

	.sb-component-score {
		text-align: right;
		color: var(--ii-text-primary);
		font-weight: 500;
	}

	.sb-component-weighted {
		text-align: right;
		color: var(--ii-text-muted);
	}
</style>
