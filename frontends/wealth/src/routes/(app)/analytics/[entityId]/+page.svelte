<!--
  Entity Analytics Vitrine — institutional-grade analytics for any entity (fund or model portfolio).
  7 Panels: Risk Statistics, Drawdown, Up/Down Capture, Rolling Returns, Return Distribution,
  Return Statistics (eVestment I-V), Tail Risk (eVestment VII).
  Fully polymorphic: entity_type is display-only, never branching logic.
-->
<script lang="ts">
	import { getContext } from "svelte";
	import { goto } from "$app/navigation";
	import { page } from "$app/stores";
	import { PageHeader } from "@investintell/ui";
	import type { PageData } from "./$types";
	import type { EntityAnalyticsResponse } from "$lib/types/entity-analytics";
	import type { PeerGroupResult, MonteCarloResult, ActiveShareResult } from "$lib/types/analytics";
	import RiskStatisticsGrid from "$lib/components/analytics/entity/RiskStatisticsGrid.svelte";
	import DrawdownChart from "$lib/components/analytics/entity/DrawdownChart.svelte";
	import CaptureRatiosPanel from "$lib/components/analytics/entity/CaptureRatiosPanel.svelte";
	import RollingReturnsChart from "$lib/components/analytics/entity/RollingReturnsChart.svelte";
	import ReturnDistributionChart from "$lib/components/analytics/entity/ReturnDistributionChart.svelte";
	import ReturnStatisticsPanel from "$lib/components/analytics/entity/ReturnStatisticsPanel.svelte";
	import TailRiskPanel from "$lib/components/analytics/entity/TailRiskPanel.svelte";
	import PeerGroupPanel from "$lib/components/analytics/entity/PeerGroupPanel.svelte";
	import ActiveSharePanel from "$lib/components/analytics/entity/ActiveSharePanel.svelte";
	import MonteCarloPanel from "$lib/components/analytics/entity/MonteCarloPanel.svelte";
	import { createClientApiClient } from "$lib/api/client";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	let { data }: { data: PageData } = $props();

	let analytics = $derived(data.analytics as EntityAnalyticsResponse | null);
	let peerGroup = $derived(data.peerGroup as PeerGroupResult | null);
	let activeShare = $derived(data.activeShare as ActiveShareResult | null);
	let currentWindow = $derived(data.window as string);

	// Monte Carlo is client-side triggered (expensive computation)
	let mcResult: MonteCarloResult | null = $state(null);
	let mcLoading = $state(false);

	async function runMonteCarlo() {
		if (!analytics || mcLoading) return;
		mcLoading = true;
		try {
			const api = createClientApiClient(getToken);
			mcResult = await api.post<MonteCarloResult>("/analytics/monte-carlo", {
				entity_id: analytics.entity_id,
				n_simulations: 10_000,
				statistic: "max_drawdown",
			});
		} catch {
			mcResult = null;
		} finally {
			mcLoading = false;
		}
	}

	const windows = ["3m", "6m", "1y", "3y", "5y"] as const;

	function switchWindow(w: string) {
		const entityId = data.entityId;
		const params = new URLSearchParams({ window: w });
		const bm = $page.url.searchParams.get("benchmark_id");
		if (bm) params.set("benchmark_id", bm);
		goto(`/analytics/${entityId}?${params.toString()}`, { replaceState: true });
	}
</script>

{#if !analytics}
	<PageHeader title="Entity Analytics" />
	<div class="ea-empty">
		<p>No analytics data available. Verify the entity has sufficient NAV history.</p>
	</div>
{:else}
	<PageHeader title={analytics.entity_name}>
		{#snippet actions()}
			<div class="ea-controls">
				<span class="ea-entity-badge">{analytics.entity_type === "model_portfolio" ? "Model Portfolio" : "Fund"}</span>
				<div class="ea-window-toggle">
					{#each windows as w (w)}
						<button
							class="ea-win-btn"
							class:ea-win-btn--active={currentWindow === w}
							onclick={() => switchWindow(w)}
						>
							{w.toUpperCase()}
						</button>
					{/each}
				</div>
			</div>
		{/snippet}
	</PageHeader>

	<RiskStatisticsGrid stats={analytics.risk_statistics} asOfDate={analytics.as_of_date} />
	<DrawdownChart drawdown={analytics.drawdown} />
	<CaptureRatiosPanel capture={analytics.capture} />
	<RollingReturnsChart rollingReturns={analytics.rolling_returns} />
	<ReturnDistributionChart distribution={analytics.distribution} />

	{#if analytics.return_statistics}
		<ReturnStatisticsPanel stats={analytics.return_statistics} />
	{/if}

	{#if analytics.tail_risk}
		<TailRiskPanel tailRisk={analytics.tail_risk} />
	{/if}

	{#if peerGroup}
		<PeerGroupPanel {peerGroup} />
	{/if}

	<ActiveSharePanel data={activeShare} benchmarkId={$page.url.searchParams.get('benchmark_id')} />

	<!-- Monte Carlo: client-triggered (expensive) -->
	{#if mcResult}
		<MonteCarloPanel mc={mcResult} />
	{:else}
		<section class="ea-panel mc-trigger">
			<h2 class="ea-panel-title">Monte Carlo Simulation</h2>
			<p class="ea-panel-sub">Block bootstrap simulation (10,000 paths)</p>
			<button class="mc-run-btn" onclick={runMonteCarlo} disabled={mcLoading}>
				{mcLoading ? "Running..." : "Run Simulation"}
			</button>
		</section>
	{/if}
{/if}

<style>
	.ea-empty {
		display: flex;
		align-items: center;
		justify-content: center;
		min-height: 300px;
		color: var(--ii-text-muted);
		font-size: 0.875rem;
	}

	.ea-controls {
		display: flex;
		align-items: center;
		gap: 12px;
	}

	.ea-entity-badge {
		font-size: 0.7rem;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--ii-brand-primary);
		background: color-mix(in srgb, var(--ii-brand-primary) 12%, transparent);
		padding: 3px 10px;
		border-radius: 6px;
	}

	.ea-window-toggle {
		display: flex;
		gap: 2px;
		background: var(--ii-surface-alt);
		border-radius: 8px;
		padding: 2px;
	}

	.ea-win-btn {
		font-size: 0.75rem;
		font-weight: 600;
		padding: 4px 12px;
		border: none;
		border-radius: 6px;
		background: transparent;
		color: var(--ii-text-secondary);
		cursor: pointer;
		transition: all 0.15s ease;
	}

	.ea-win-btn:hover {
		color: var(--ii-text-primary);
		background: color-mix(in srgb, var(--ii-border) 40%, transparent);
	}

	.ea-win-btn--active {
		background: var(--ii-surface-elevated);
		color: var(--ii-brand-primary);
		box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
	}

	.ea-panel {
		background: var(--ii-surface-elevated);
		border: 1px solid var(--ii-border);
		border-radius: 12px;
		padding: clamp(16px, 1rem + 0.5vw, 28px);
		margin-bottom: 16px;
	}

	.ea-panel-title {
		font-size: 0.9rem;
		font-weight: 700;
		color: var(--ii-text-primary);
		margin: 0 0 4px;
	}

	.ea-panel-sub {
		font-size: 0.75rem;
		color: var(--ii-text-muted);
		margin: 0 0 16px;
	}

	.mc-trigger {
		text-align: center;
	}

	.mc-run-btn {
		font-size: 0.8rem;
		font-weight: 600;
		padding: 8px 24px;
		border: 1px solid var(--ii-brand-primary);
		border-radius: 8px;
		background: color-mix(in srgb, var(--ii-brand-primary) 10%, transparent);
		color: var(--ii-brand-primary);
		cursor: pointer;
		transition: all 0.15s ease;
	}

	.mc-run-btn:hover:not(:disabled) {
		background: color-mix(in srgb, var(--ii-brand-primary) 20%, transparent);
	}

	.mc-run-btn:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
</style>
