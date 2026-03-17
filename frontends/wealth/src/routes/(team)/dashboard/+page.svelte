<!--
  Wealth Dashboard — Figma frame "Dashboard com portfólios + NAV chart + alertas"
  Layout: RegimeBanner + Header + 3 PortfolioCards + NAV chart (left) + Alerts (right) + Macro chips
-->
<script lang="ts">
	import {
		StatusBadge, EmptyState, TimeSeriesChart, PageHeader,
		PeriodSelector, RegimeBanner, SectionCard, AlertFeed,
		type WealthAlert,
	} from "@netz/ui";
	import PortfolioCard from "$lib/components/PortfolioCard.svelte";
	import { regimeLabels } from "$lib/constants/regime";
	import type { PageData } from "./$types";
	import type { RegimeData } from "$lib/types/api";

	let { data }: { data: PageData } = $props();

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

	// Derived data — use $state.raw for API data
	let portfolios = $state.raw(data.portfolios as PortfolioSummary[] | null);
	let modelPortfolios = $state.raw(data.modelPortfolios as ModelPortfolio[] | null);
	let macro = $state.raw(data.macro as MacroIndicators | null);
	let regime = $state.raw(data.regime as RegimeData | null);
	let cvarByProfile = $state.raw(data.cvarByProfile as Record<string, CVaRStatus>);

	// Portfolio cards
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
			const cvar = cvarByProfile[p.profile] as CVaRStatus | undefined;
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

	// Risk alerts — capped at 50 entries
	let riskAlerts = $state<WealthAlert[]>([]);

	// Current regime
	const currentRegime = $derived(
		regime?.regime ?? portfolios?.[0]?.regime ?? null
	);

	// Format date for subtitle
	const today = new Date();
	const subtitle = $derived(
		`${today.toLocaleDateString("pt-BR", { day: "2-digit", month: "short", year: "numeric" })} · Atualizado às ${today.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })}`
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
			<StatusBadge status={currentRegime} />
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
				/>
			</div>
		</SectionCard>

		<!-- Alertas Ativos (40%) -->
		<SectionCard title="Alertas Ativos" class="lg:col-span-2">
			{#if riskAlerts.length > 0}
				<AlertFeed alerts={riskAlerts} maxItems={50} />
			{:else}
				<EmptyState
					title="Sem alertas ativos"
					message="Alertas de risco em tempo real aparecerão aqui quando o stream SSE estiver conectado."
				/>
			{/if}
		</SectionCard>
	</section>

	<!-- Macro Indicator Chips -->
	<section>
		<SectionCard title="Macro Summary">
			{#snippet actions()}
				{#if currentRegime}
					<StatusBadge status={currentRegime} />
				{/if}
			{/snippet}
			{#if macro}
				<div class="flex flex-wrap gap-3">
					<div class="rounded-lg border border-[var(--netz-border)] bg-[var(--netz-surface-inset)] px-4 py-3">
						<p class="text-xs text-[var(--netz-text-muted)]">VIX</p>
						<p class="text-lg font-semibold text-[var(--netz-text-primary)]">{macro.vix?.toFixed(1) ?? "—"}</p>
					</div>
					<div class="rounded-lg border border-[var(--netz-border)] bg-[var(--netz-surface-inset)] px-4 py-3">
						<p class="text-xs text-[var(--netz-text-muted)]">Yield Curve</p>
						<p class="text-lg font-semibold" style:color={macro.yield_curve_10y2y !== null && macro.yield_curve_10y2y < 0 ? "var(--netz-danger)" : "var(--netz-text-primary)"}>{macro.yield_curve_10y2y !== null ? `${macro.yield_curve_10y2y.toFixed(2)}%` : "—"}</p>
					</div>
					<div class="rounded-lg border border-[var(--netz-border)] bg-[var(--netz-surface-inset)] px-4 py-3">
						<p class="text-xs text-[var(--netz-text-muted)]">CPI YoY</p>
						<p class="text-lg font-semibold text-[var(--netz-text-primary)]">{macro.cpi_yoy !== null ? `${macro.cpi_yoy.toFixed(1)}%` : "—"}</p>
					</div>
					<div class="rounded-lg border border-[var(--netz-border)] bg-[var(--netz-surface-inset)] px-4 py-3">
						<p class="text-xs text-[var(--netz-text-muted)]">Fed Funds</p>
						<p class="text-lg font-semibold text-[var(--netz-text-primary)]">{macro.fed_funds_rate !== null ? `${macro.fed_funds_rate.toFixed(2)}%` : "—"}</p>
					</div>
				</div>
			{:else}
				<EmptyState title="No Macro Data" message="FRED macro data will appear here once available." />
			{/if}
		</SectionCard>
	</section>
</div>
