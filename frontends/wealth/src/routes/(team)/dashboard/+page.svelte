<!--
  Wealth Dashboard — Figma frame "Dashboard com portfólios + NAV chart + alertas"
  Layout: RegimeBanner + Header + 3 PortfolioCards + NAV chart (left) + Alerts (right) + Macro chips
  Risk data consumed exclusively from the risk store — no page-local SSE.
-->
<script lang="ts">
	import {
		Badge, StatusBadge, EmptyState, PageHeader,
		RegimeBanner, SectionCard,
		formatDateTime,
	} from "@netz/ui";
	import PortfolioCard from "$lib/components/PortfolioCard.svelte";
	import MacroChips from "$lib/components/MacroChips.svelte";
	import { resolveWealthStatus } from "$lib/utils/status-maps";
	import type { PageData } from "./$types";
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

	// Derived data from server load
	let portfolios = $derived(data.portfolios as PortfolioSummary[] | null);
	let modelPortfolios = $derived(data.modelPortfolios as ModelPortfolio[] | null);

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

<div class="space-y-[var(--netz-space-section-gap)] p-[var(--netz-space-page-gutter)]">
	<!-- Regime Banner (renders nothing when RISK_ON) -->
	<RegimeBanner regime={currentRegime} macroHref="/macro" />

	<!-- Page Header -->
	<PageHeader title="Wealth OS - Dashboard">
		{#snippet actions()}
			{#if currentRegime && currentRegime !== "RISK_ON"}
				<StatusBadge status={currentRegime} resolve={resolveWealthStatus} />
			{/if}
		{/snippet}
	</PageHeader>
	<p class="-mt-3 text-sm text-[var(--netz-text-muted)]">{subtitle}</p>

	<!-- Portfolio Cards -->
	<section>
		{#if cards.length > 0}
			<div class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
				{#each cards as card (card.profile)}
					<a
						href="/portfolios/{card.profile}"
						class="block rounded-[var(--netz-radius-xl)] transition-transform duration-[var(--netz-duration-fast)] hover:-translate-y-0.5"
					>
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

	<!-- Decision Surface — Drift Alerts + Recent Activity -->
	<section class="grid gap-4 lg:grid-cols-5">
		<!-- Drift Alerts (60%) -->
		<SectionCard title="Drift Alerts" class="lg:col-span-3">
			{#snippet actions()}
				{#if riskStore.computedAt}
					<span class="text-xs font-medium uppercase tracking-[0.08em] text-[var(--netz-text-muted)]">
						{formatDateTime(riskStore.computedAt)}
					</span>
				{/if}
			{/snippet}
			{#if riskStore.driftAlerts.dtw_alerts.length > 0 || riskStore.driftAlerts.behavior_change_alerts.length > 0}
				<div class="space-y-3">
					{#each riskStore.driftAlerts.dtw_alerts as alert (alert.instrument_name)}
						<div class="flex items-center justify-between rounded-[var(--netz-radius-lg)] border border-[var(--netz-border-subtle)] bg-[var(--netz-surface-elevated)] p-4 shadow-[var(--netz-shadow-1)]">
							<div class="space-y-0.5">
								<p class="text-sm font-medium text-[var(--netz-text-primary)]">{alert.instrument_name}</p>
								<p class="text-xs text-[var(--netz-text-muted)]">DTW score: {alert.dtw_score}</p>
							</div>
							<div class="flex items-center gap-2">
								<Badge variant="outline">DTW Drift</Badge>
								{#if alert.instrument_id}
									<a
										href="/portfolios/{alert.instrument_id}"
										class="inline-flex h-[var(--netz-space-control-height-sm)] items-center rounded-[var(--netz-radius-md)] border border-[var(--netz-border-subtle)] bg-[var(--netz-surface-elevated)] px-3 text-xs font-medium text-[var(--netz-text-primary)] shadow-[var(--netz-shadow-1)] transition-[background-color,border-color,color] duration-[var(--netz-duration-fast)] hover:border-[var(--netz-border)] hover:bg-[var(--netz-surface-highlight)]"
									>
										Review
									</a>
								{/if}
							</div>
						</div>
					{/each}
					{#each riskStore.driftAlerts.behavior_change_alerts as alert (alert.instrument_name)}
						<div class="flex items-center justify-between rounded-[var(--netz-radius-lg)] border border-[var(--netz-border-subtle)] bg-[var(--netz-surface-elevated)] p-4 shadow-[var(--netz-shadow-1)]">
							<div class="space-y-0.5">
								<p class="text-sm font-medium text-[var(--netz-text-primary)]">{alert.instrument_name}</p>
								<p class="text-xs text-[var(--netz-text-muted)]">
									{alert.anomalous_count} / {alert.total_metrics} metrics anomalous
								</p>
							</div>
							<div class="flex items-center gap-2">
								<Badge variant="destructive">{alert.severity}</Badge>
								{#if alert.instrument_id}
									<a
										href="/portfolios/{alert.instrument_id}"
										class="inline-flex h-[var(--netz-space-control-height-sm)] items-center rounded-[var(--netz-radius-md)] border border-[var(--netz-border-subtle)] bg-[var(--netz-surface-elevated)] px-3 text-xs font-medium text-[var(--netz-text-primary)] shadow-[var(--netz-shadow-1)] transition-[background-color,border-color,color] duration-[var(--netz-duration-fast)] hover:border-[var(--netz-border)] hover:bg-[var(--netz-surface-highlight)]"
									>
										Review
									</a>
								{/if}
							</div>
						</div>
					{/each}
				</div>
			{:else}
				<EmptyState
					title="No active drift alerts"
					message="Risk alerts will appear here when detected by the analysis engine."
				/>
			{/if}
		</SectionCard>

		<!-- Recent Activity (40%) -->
		<SectionCard title="Quick Actions" class="lg:col-span-2">
			<div class="space-y-3">
				<!-- Portfolio links -->
				{#each cards as card (card.profile)}
					<a
						href="/portfolios/{card.profile}"
						class="flex items-center justify-between rounded-[var(--netz-radius-lg)] border border-[var(--netz-border-subtle)] bg-[var(--netz-surface-elevated)] p-4 shadow-[var(--netz-shadow-1)] transition-[background-color,border-color,transform] duration-[var(--netz-duration-fast)] hover:border-[var(--netz-border)] hover:bg-[var(--netz-surface-highlight)]"
					>
						<div class="space-y-0.5">
							<p class="text-sm font-medium text-[var(--netz-text-primary)]">{card.name}</p>
							<p class="text-xs text-[var(--netz-text-muted)]">
								{card.triggerStatus
									? card.triggerStatus === "breach"
										? "CVaR Breached"
										: card.triggerStatus === "warning"
										? "CVaR Warning"
										: "Normal"
									: "Normal"}
							</p>
						</div>
						{#if card.triggerStatus === "breach"}
							<Badge variant="destructive">Action Required</Badge>
						{:else if card.triggerStatus === "warning"}
							<Badge variant="outline">Monitor</Badge>
						{:else}
							<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="text-[var(--netz-text-muted)]"><path d="m9 18 6-6-6-6"/></svg>
						{/if}
					</a>
				{/each}

				<!-- Allocation shortcut -->
				<a
					href="/allocation"
					class="flex items-center justify-between rounded-[var(--netz-radius-lg)] border border-[var(--netz-border-subtle)] bg-[var(--netz-surface-elevated)] p-4 shadow-[var(--netz-shadow-1)] transition-[background-color,border-color,transform] duration-[var(--netz-duration-fast)] hover:border-[var(--netz-border)] hover:bg-[var(--netz-surface-highlight)]"
				>
					<div class="space-y-0.5">
						<p class="text-sm font-medium text-[var(--netz-text-primary)]">Strategic Allocation</p>
						<p class="text-xs text-[var(--netz-text-muted)]">Review and update allocation weights</p>
					</div>
					<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="text-[var(--netz-text-muted)]"><path d="m9 18 6-6-6-6"/></svg>
				</a>
			</div>
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
