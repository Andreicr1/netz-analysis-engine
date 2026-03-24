<!--
  Portfolios — Profile cards (Conservative, Moderate, Growth) with live KPIs.
-->
<script lang="ts">
	import { goto } from "$app/navigation";
	import { getContext } from "svelte";
	import { PageHeader, StatusBadge, EmptyState, formatPercent } from "@netz/ui";
	import type { RiskStore } from "$lib/stores/risk-store.svelte";
	import type { PageData } from "./$types";
	import type { PortfolioSummary } from "$lib/types/portfolio";

	const riskStore = getContext<RiskStore>("netz:riskStore");

	let { data }: { data: PageData } = $props();
	let profiles = $derived((data.profiles ?? []) as PortfolioSummary[]);

	function fmtPct(v: unknown): string {
		if (v === null || v === undefined) return "—";
		const n = typeof v === "string" ? parseFloat(v) : Number(v);
		if (isNaN(n)) return "—";
		return formatPercent(n);
	}
</script>

<PageHeader title="Portfolios" subtitle="Current positions and realized weights for each risk profile" />

<div class="port-page">
	{#if profiles.length === 0}
		<EmptyState title="No portfolio profiles" message="Profiles are created when model portfolios are activated." />
	{:else}
		<div class="port-grid">
			{#each profiles as p (p.profile)}
				{@const live = riskStore.cvarByProfile[p.profile]}
				<button class="port-card" onclick={() => goto(`/portfolios/${p.profile}`)}>
					<div class="port-card-header">
						<h3 class="port-profile">{p.profile}</h3>
						{#if p.regime ?? live?.regime}
							<StatusBadge status={live?.regime ?? p.regime ?? "—"} />
						{/if}
					</div>

					<div class="port-kpis">
						<div class="port-kpi">
							<span class="port-kpi-label">CVaR 95%</span>
							<span class="port-kpi-value">
								{fmtPct(live?.cvar_current ?? p.cvar_current)}
							</span>
						</div>
						<div class="port-kpi">
							<span class="port-kpi-label">Utilized</span>
							<span class="port-kpi-value">
								{fmtPct(live?.cvar_utilized_pct ?? p.cvar_utilized_pct)}
							</span>
						</div>
						<div class="port-kpi">
							<span class="port-kpi-label">Core</span>
							<span class="port-kpi-value">
								{fmtPct(p.core_weight)}
							</span>
						</div>
						<div class="port-kpi">
							<span class="port-kpi-label">Satellite</span>
							<span class="port-kpi-value">
								{fmtPct(p.satellite_weight)}
							</span>
						</div>
					</div>

					{#if live?.trigger_status ?? p.trigger_status}
						<div class="port-trigger">
							<StatusBadge status={live?.trigger_status ?? p.trigger_status ?? "ok"} />
						</div>
					{/if}
				</button>
			{/each}
		</div>
	{/if}
</div>

<style>
	.port-page {
		padding: var(--netz-space-stack-md, 16px) var(--netz-space-inline-lg, 24px);
	}

	.port-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
		gap: var(--netz-space-stack-md, 16px);
	}

	.port-card {
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

	.port-card:hover {
		border-color: var(--netz-border-accent);
		box-shadow: var(--netz-shadow-2);
	}

	.port-card-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: var(--netz-space-stack-sm, 14px) var(--netz-space-inline-md, 16px);
		border-bottom: 1px solid var(--netz-border-subtle);
	}

	.port-profile {
		font-size: var(--netz-text-h4, 1.125rem);
		font-weight: 700;
		color: var(--netz-text-primary);
		text-transform: capitalize;
	}

	.port-kpis {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 1px;
		background: var(--netz-border-subtle);
	}

	.port-kpi {
		display: flex;
		flex-direction: column;
		gap: 2px;
		padding: var(--netz-space-stack-xs, 10px) var(--netz-space-inline-sm, 12px);
		background: var(--netz-surface-elevated);
	}

	.port-kpi-label {
		font-size: var(--netz-text-label, 0.75rem);
		color: var(--netz-text-muted);
	}

	.port-kpi-value {
		font-size: var(--netz-text-body, 0.9375rem);
		font-weight: 600;
		color: var(--netz-text-primary);
		font-variant-numeric: tabular-nums;
	}

	.port-trigger {
		padding: var(--netz-space-stack-xs, 8px) var(--netz-space-inline-md, 16px);
		border-top: 1px solid var(--netz-border-subtle);
	}
</style>
