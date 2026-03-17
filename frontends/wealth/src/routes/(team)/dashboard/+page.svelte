<!--
  Wealth Dashboard — three-tier layout:
  Tier 1 (Command): 3 PortfolioCards with CVaR gauges + regime chips
  Tier 2 (Analytical): Consolidated NAV TimeSeriesChart with period selector
  Tier 3 (Macro): VIX, yield curve, regime indicator + live risk alerts
-->
<script lang="ts">
	import { DataCard, StatusBadge, EmptyState, TimeSeriesChart, PageHeader } from "@netz/ui";
	import PortfolioCard from "$lib/components/PortfolioCard.svelte";
	import type { PageData } from "./$types";

	let { data }: { data: PageData } = $props();

	// Extract typed values
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

	let portfolios = $derived(data.portfolios as PortfolioSummary[] | null);
	let modelPortfolios = $derived(data.modelPortfolios as ModelPortfolio[] | null);
	let macro = $derived(data.macro as MacroIndicators | null);
	import type { RegimeData } from "$lib/types/api";
	let regime = $derived(data.regime as RegimeData | null);
	let cvarByProfile = $derived(data.cvarByProfile as Record<string, CVaRStatus>);

	// Build portfolio cards — merge portfolio summary with model portfolio display names
	interface CardData {
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

	let cards = $derived.by((): CardData[] => {
		if (!portfolios) return [];
		return portfolios.map((p) => {
			const mp = modelPortfolios?.find((m) => m.profile === p.profile);
			const cvar = cvarByProfile[p.profile] as CVaRStatus | undefined;
			return {
				name: mp?.display_name ?? p.profile,
				profile: p.profile,
				nav: mp?.inception_nav ?? null,
				ytdReturn: null, // Computed from track-record in future
				cvarCurrent: cvar?.cvar_current ?? p.cvar_current,
				cvarLimit: cvar?.cvar_limit ?? p.cvar_limit,
				cvarUtilization: cvar?.cvar_utilized_pct ?? p.cvar_utilized_pct,
				sharpe: null, // Computed from track-record in future
				regime: cvar?.regime ?? p.regime,
				triggerStatus: cvar?.trigger_status ?? p.trigger_status,
			};
		});
	});

	// Period selector for consolidated chart
	type Period = "1M" | "3M" | "YTD" | "1Y" | "3Y";
	let selectedPeriod = $state<Period>("YTD");
	const periods: Period[] = ["1M", "3M", "YTD", "1Y", "3Y"];

	// SSE risk alerts
	type RiskAlert = {
		type: string;
		profile: string;
		message: string;
		timestamp: string;
	};

	let riskAlerts = $state<RiskAlert[]>([]);

	import { regimeLabels, regimeColors } from "$lib/constants/regime";

	// Current regime from API
	let currentRegime = $derived(
		regime?.regime ??
		portfolios?.[0]?.regime ??
		null
	);
</script>

<div class="space-y-6 p-6">
	<!-- Page Header -->
	<PageHeader title="Dashboard" />

	<!-- Tier 1: Portfolio Cards -->
	<section>
		<h2 class="mb-4 text-lg font-semibold text-[var(--netz-text-primary)]">Model Portfolios</h2>
		{#if cards.length > 0}
			<div class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
				{#each cards as card (card.profile)}
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
				{/each}
			</div>
		{:else}
			<EmptyState
				title="No Model Portfolios"
				message="Model portfolios will appear here once created."
			/>
		{/if}
	</section>

	<!-- Tier 2: Consolidated NAV Chart -->
	<section>
		<div class="rounded-lg border border-[var(--netz-border)] bg-[var(--netz-surface-elevated)] p-5">
			<div class="mb-4 flex items-center justify-between">
				<h2 class="text-lg font-semibold text-[var(--netz-text-primary)]">Consolidated Performance</h2>
				<div class="flex gap-1">
					{#each periods as period (period)}
						<button
							class="rounded-md px-3 py-1.5 text-xs font-medium transition-colors {selectedPeriod === period
								? 'bg-[var(--netz-brand-primary)] text-white'
								: 'text-[var(--netz-text-secondary)] hover:bg-[var(--netz-surface-alt)]'}"
							onclick={() => selectedPeriod = period}
						>
							{period}
						</button>
					{/each}
				</div>
			</div>
			<div class="h-80">
				<TimeSeriesChart
					series={[]}
					yAxisLabel="NAV"
					empty={true}
					emptyMessage="Track-record data not yet available"
				/>
			</div>
			<p class="mt-2 text-center text-xs text-[var(--netz-text-muted)]">
				Chart data will populate once track-record history is available.
			</p>
		</div>
	</section>

	<!-- Tier 3: Macro Summary + Risk Alerts -->
	<section>
		<div class="grid gap-4 lg:grid-cols-2">
			<!-- Macro Indicators -->
			<div class="rounded-lg border border-[var(--netz-border)] bg-[var(--netz-surface-elevated)] p-5">
				<div class="mb-4 flex items-center justify-between">
					<h3 class="text-sm font-semibold text-[var(--netz-text-primary)]">Macro Summary</h3>
					{#if currentRegime}
						<StatusBadge status={currentRegime} />
					{/if}
				</div>
				{#if macro}
					<div class="grid grid-cols-2 gap-3">
						<DataCard
							label="VIX"
							value={macro.vix !== null ? macro.vix.toFixed(1) : "—"}
							trend="flat"
						/>
						<DataCard
							label="Yield Curve (10Y-2Y)"
							value={macro.yield_curve_10y2y !== null ? `${macro.yield_curve_10y2y.toFixed(2)}%` : "—"}
							trend="flat"
						/>
						<DataCard
							label="CPI YoY"
							value={macro.cpi_yoy !== null ? `${macro.cpi_yoy.toFixed(1)}%` : "—"}
							trend="flat"
						/>
						<DataCard
							label="Fed Funds Rate"
							value={macro.fed_funds_rate !== null ? `${macro.fed_funds_rate.toFixed(2)}%` : "—"}
							trend="flat"
						/>
					</div>
				{:else}
					<EmptyState title="No Macro Data" message="FRED macro data will appear here once available." />
				{/if}
			</div>

			<!-- Risk Alerts (SSE) -->
			<div class="rounded-lg border border-[var(--netz-border)] bg-[var(--netz-surface-elevated)] p-5">
				<h3 class="mb-4 text-sm font-semibold text-[var(--netz-text-primary)]">Risk Alerts</h3>
				{#if riskAlerts.length > 0}
					<div class="space-y-2">
						{#each riskAlerts.slice(0, 10) as alert (alert.timestamp)}
							<div class="flex items-start gap-2 rounded-md bg-[var(--netz-surface-alt)] p-3 text-sm">
								<StatusBadge status={alert.type} />
								<div>
									<p class="font-medium text-[var(--netz-text-primary)]">{alert.message}</p>
									<p class="text-xs text-[var(--netz-text-muted)]">
										{alert.profile} · {new Date(alert.timestamp).toLocaleTimeString()}
									</p>
								</div>
							</div>
						{/each}
					</div>
				{:else}
					<EmptyState
						title="No Active Alerts"
						message="Real-time risk alerts will appear here when the SSE stream is connected."
					/>
				{/if}
			</div>
		</div>
	</section>
</div>
