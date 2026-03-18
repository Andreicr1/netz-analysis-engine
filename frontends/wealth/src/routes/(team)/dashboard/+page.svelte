<!--
  Wealth Dashboard — Figma frame "Dashboard com portfólios + NAV chart + alertas"
  Layout: RegimeBanner + Header + 3 PortfolioCards + NAV chart (left) + Alerts (right) + Macro chips
  Risk data consumed exclusively from the risk store — no page-local SSE.
-->
<script lang="ts">
	import {
		StatusBadge, EmptyState, TimeSeriesChart, PageHeader,
		PeriodSelector, RegimeBanner, SectionCard, AlertFeed,
		formatDateTime,
		type WealthAlert,
	} from "@netz/ui";
	import PortfolioCard from "$lib/components/PortfolioCard.svelte";
	import MacroChips from "$lib/components/MacroChips.svelte";
	import { regimeLabels } from "$lib/constants/regime";
	import { resolveWealthStatus } from "$lib/utils/status-maps";
	import type { PageData } from "./$types";
	import type { RegimeData } from "$lib/types/api";
	import { getContext } from "svelte";
	import type { RiskStore } from "$lib/stores/risk-store.svelte";

	let { data }: { data: PageData } = $props();

	// Risk store — single authoritative source for live risk data
	const riskStore = getContext<RiskStore>("netz:riskStore");

	// Types
	type PortfolioSummary = {
		profile: string;
		snapshot_date: string | null;
		cvar_current: number | null;
		cvar_limit: number | null;
		cvar_utilized_pct: number | null;
		trigger_status: string | null;
		regime: string | null;
		core_weight: number | null;
		satellite_weight: number | null;
	};

	type ModelPortfolio = {
		id: string;
		profile: string;
		display_name: string;
		inception_nav: number;
		status: string;
	};

	type MacroIndicators = {
		vix: number | null;
		vix_date: string | null;
		yield_curve_10y2y: number | null;
		yield_curve_date: string | null;
		cpi_yoy: number | null;
		cpi_date: string | null;
		fed_funds_rate: number | null;
		fed_funds_date: string | null;
	};

	type CVaRStatus = {
		profile: string;
		cvar_current: number | null;
		cvar_limit: number | null;
		cvar_utilized_pct: number | null;
		trigger_status: string | null;
		regime: string | null;
	};

	// Derived data — use $state.raw for API data loaded at page level
	let portfolios = $state.raw(data.portfolios as PortfolioSummary[] | null);
	let modelPortfolios = $state.raw(data.modelPortfolios as ModelPortfolio[] | null);

	// Live risk data from the store — single source of truth
	const liveCvarByProfile = $derived(riskStore.cvarByProfile);
	const liveRegime = $derived(riskStore.regime);
	const liveMacro = $derived(riskStore.macroIndicators as MacroIndicators | null);

	// Portfolio cards — merge page data with live store data
	interface CardData {
		id: string;
		name: string;
		profile: string;
		nav: number | null;
		ytdReturn: number | null;
		cvarCurrent: number | null;
		cvarLimit: number | null;
		cvarUtilization: number | null;
		sharpe: number | null;
		regime: string | null;
		triggerStatus: string | null;
	}

	const cards = $derived.by((): CardData[] => {
		if (!portfolios) return [];
		return portfolios.map((p) => {
			const mp = modelPortfolios?.find((m) => m.profile === p.profile);
			const cvar = liveCvarByProfile[p.profile] as CVaRStatus | undefined;
			return {
				id: mp?.id ?? p.profile,
				name: mp?.display_name ?? p.profile,
				profile: p.profile,
				nav: mp?.inception_nav ?? null,
				ytdReturn: null,
				cvarCurrent: cvar?.cvar_current ?? p.cvar_current,
				cvarLimit: cvar?.cvar_limit ?? p.cvar_limit,
				cvarUtilization: cvar?.cvar_utilized_pct ?? p.cvar_utilized_pct,
				sharpe: null,
				regime: cvar?.regime ?? p.regime,
				triggerStatus: cvar?.trigger_status ?? p.trigger_status,
			};
		});
	});

	// Period selector
	const periods = ["1M", "3M", "YTD", "1Y", "3Y"];
	let selectedPeriod = $state("YTD");

	// Current regime — from live store, fallback to page data
	const currentRegime = $derived(
		liveRegime?.regime ?? portfolios?.[0]?.regime ?? null
	);

	// Freshness subtitle — derived from server computed_at
	const subtitle = $derived(
		riskStore.computedAt
			? `${formatDateTime(riskStore.computedAt)} · Atualizado`
			: "Aguardando dados..."
	);
</script>

<div class="space-y-6 p-6">
	<!-- Regime Banner (renders nothing when RISK_ON) -->
	<RegimeBanner regime={currentRegime} macroHref="/macro" />

	<!-- Page Header -->
	<div class="flex items-center justify-between">
		<div>
			<h1 class="text-2xl font-bold text-[var(--netz-text-primary)]">Wealth OS — Dashboard</h1>
			<p class="mt-1 text-sm text-[var(--netz-text-muted)]">{subtitle}</p>
		</div>
		{#if currentRegime && currentRegime !== "RISK_ON"}
			<StatusBadge status={currentRegime} resolve={resolveWealthStatus} />
		{/if}
	</div>

	<!-- Portfolio Cards -->
	<section>
		{#if cards.length > 0}
			<div class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
				{#each cards as card (card.profile)}
					<a href="/model-portfolios?portfolio={card.id}" class="block transition-transform hover:scale-[1.01]">
						<PortfolioCard
							name={card.name}
							profile={card.profile}
							nav={card.nav}
							ytdReturn={card.ytdReturn}
							cvarCurrent={card.cvarCurrent}
							cvarLimit={card.cvarLimit}
							cvarUtilization={card.cvarUtilization}
							sharpe={card.sharpe}
							regime={card.regime}
							triggerStatus={card.triggerStatus}
						/>
					</a>
				{/each}
			</div>
		{:else}
			<EmptyState title="No Model Portfolios" message="Model portfolios will appear here once created." />
		{/if}
	</section>

	<!-- NAV Chart + Alerts — side by side -->
	<section class="grid gap-4 lg:grid-cols-5">
		<!-- NAV Chart (60%) -->
		<SectionCard title="NAV — Portfólios Consolidados" class="lg:col-span-3">
			{#snippet actions()}
				<PeriodSelector {periods} selected={selectedPeriod} onSelect={(p) => selectedPeriod = p} />
			{/snippet}
			<div class="h-80">
				<TimeSeriesChart
					series={[]}
					yAxisLabel="NAV"
					empty={true}
					emptyMessage="Track-record data not yet available"
					ariaLabel="Consolidated NAV chart"
				/>
			</div>
		</SectionCard>

		<!-- Alertas Ativos (40%) -->
		<SectionCard title="Alertas Ativos" class="lg:col-span-2">
			{#if riskStore.driftAlerts.dtw_alerts.length > 0 || riskStore.driftAlerts.behavior_change_alerts.length > 0}
				<div class="space-y-2 text-sm text-[var(--netz-text-secondary)]">
					{#each riskStore.driftAlerts.dtw_alerts as alert (alert.instrument_name)}
						<div class="rounded border border-[var(--netz-border)] p-2">
							<span class="font-medium">{alert.instrument_name}</span>
							<span class="ml-2 text-[var(--netz-text-muted)]">DTW: {alert.dtw_score}</span>
						</div>
					{/each}
					{#each riskStore.driftAlerts.behavior_change_alerts as alert (alert.instrument_name)}
						<div class="rounded border border-[var(--netz-border)] p-2">
							<span class="font-medium">{alert.instrument_name}</span>
							<span class="ml-2 text-[var(--netz-text-muted)]">{alert.severity}</span>
						</div>
					{/each}
				</div>
			{:else}
				<EmptyState
					title="Sem alertas ativos"
					message="Alertas de risco aparecerão aqui quando detectados pelo motor de análise."
				/>
			{/if}
		</SectionCard>
	</section>

	<!-- Macro Indicator Chips -->
	<section>
		<SectionCard title="Macro Summary">
			{#snippet actions()}
				{#if currentRegime}
					<StatusBadge status={currentRegime} resolve={resolveWealthStatus} />
				{/if}
			{/snippet}
			{#if liveMacro}
				<MacroChips macro={liveMacro} />
			{:else}
				<EmptyState title="No Macro Data" message="FRED macro data will appear here once available." />
			{/if}
		</SectionCard>
	</section>
</div>
