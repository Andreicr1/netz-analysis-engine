<!--
  Risk Monitor — Figma frame "CVaR gauges + regime chart + drift" (node 1:7)
  Sections: CVaR utilization bars, Regime area chart, Macro chips, Drift Alerts (DTW + behavior change)
-->
<script lang="ts">
	import {
		StatusBadge, TimeSeriesChart, RegimeChart, PageHeader, EmptyState,
		SectionCard, UtilizationBar, PeriodSelector, MetricCard,
	} from "@netz/ui";
	import type { PageData } from "./$types";

	let { data }: { data: PageData } = $props();

	type CVaRStatus = {
		profile: string;
		calc_date: string | null;
		cvar_current: number | null;
		cvar_limit: number | null;
		cvar_utilized_pct: number | null;
		trigger_status: string | null;
		regime: string | null;
		consecutive_breach_days: number;
	};

	type CVaRPoint = { date: string; cvar: number };
	type MacroIndicators = {
		vix: number | null;
		yield_curve_10y2y: number | null;
		cpi_yoy: number | null;
		fed_funds_rate: number | null;
	};
	type RegimeHistoryPoint = { date: string; regime: string };

	// API data — $state.raw for large immutable datasets
	let cvarByProfile = $state.raw(data.cvarByProfile as Record<string, CVaRStatus>);
	let cvarHistoryByProfile = $state.raw(data.cvarHistoryByProfile as Record<string, CVaRPoint[]>);
	let regime = $state.raw(data.regime as Record<string, string> | null);
	let regimeHistory = $state.raw(data.regimeHistory as RegimeHistoryPoint[] | null);
	let macro = $state.raw(data.macro as MacroIndicators | null);
	let driftAlerts = $state.raw(data.driftAlerts as { dtw_alerts: DtwAlert[]; behavior_change_alerts: BehaviorAlert[] } | null);

	type DtwAlert = { instrument_name: string; dtw_score: number };
	type BehaviorAlert = { instrument_name: string; severity: string; anomalous_count: number; total_metrics: number };

	const profiles = ["conservative", "moderate", "growth"];
	const profileLabels: Record<string, string> = { conservative: "Conservador", moderate: "Moderado", growth: "Growth" };

	// CVaR history series
	const cvarSeries = $derived(
		profiles
			.filter((p) => cvarHistoryByProfile[p])
			.map((p) => ({
				name: profileLabels[p] ?? p,
				data: ((cvarHistoryByProfile[p] ?? []) as CVaRPoint[]).map(
					(point) => [point.date, point.cvar * 100] as [string, number],
				),
			})),
	);

	// Regime bands
	type RegimeType = "RISK_ON" | "RISK_OFF" | "INFLATION" | "CRISIS";
	const regimeBands = $derived.by(() => {
		if (!regimeHistory || regimeHistory.length === 0) return [];
		const bands: { start: string; end: string; type: RegimeType }[] = [];
		let current = regimeHistory[0]!;
		for (let i = 1; i < regimeHistory.length; i++) {
			const point = regimeHistory[i]!;
			if (point.regime !== current.regime) {
				bands.push({ start: current.date, end: point.date, type: current.regime as RegimeType });
				current = point;
			}
		}
		bands.push({ start: current.date, end: regimeHistory.at(-1)!.date, type: current.regime as RegimeType });
		return bands;
	});

	const currentRegime = $derived(regime?.regime ?? null);

	// Period selector for CVaR
	const cvarPeriods = ["1M", "3M", "6M", "12M"];
	let selectedCvarPeriod = $state("12M");

	function fmtPct(v: number | null): string {
		if (v === null) return "—";
		return `${(v * 100).toFixed(1)}%`;
	}
</script>

<div class="space-y-6 p-6">
	<PageHeader title="Risk Monitor">
		{#snippet actions()}
			{#if currentRegime}
				<StatusBadge status={currentRegime} />
			{/if}
		{/snippet}
	</PageHeader>

	<!-- CVaR 95% — Utilização por Portfólio -->
	<SectionCard title="CVaR 95% — Utilização por Portfólio" subtitle="Rolling 12M · Limite configurado por perfil de risco">
		{#snippet actions()}
			<PeriodSelector periods={cvarPeriods} selected={selectedCvarPeriod} onSelect={(p) => selectedCvarPeriod = p} />
		{/snippet}

		<div class="space-y-4">
			{#each profiles as profile (profile)}
				{@const cvar = cvarByProfile[profile] as CVaRStatus | undefined}
				<div class="flex items-center gap-4">
					<span class="w-28 shrink-0 text-sm font-medium capitalize text-[var(--netz-text-primary)]">{profileLabels[profile] ?? profile}</span>
					<div class="flex-1">
						<UtilizationBar
							current={cvar?.cvar_utilized_pct ?? 0}
							limit={100}
							showValues={false}
						/>
					</div>
					<span class="w-32 shrink-0 text-right text-sm font-mono text-[var(--netz-text-secondary)]">
						{fmtPct(cvar?.cvar_current ?? null)} / {fmtPct(cvar?.cvar_limit ?? null)}
					</span>
				</div>
			{/each}
		</div>
	</SectionCard>

	<!-- Regime de Mercado + Drift Alerts side-by-side -->
	<div class="grid gap-4 lg:grid-cols-5">
		<!-- Regime Chart (60%) -->
		<SectionCard title="Regime de Mercado — FRED Indicators" class="lg:col-span-3">
			{#if regimeBands.length > 0}
				<div class="h-64">
					<RegimeChart series={[]} regimes={regimeBands} />
				</div>
			{:else}
				<EmptyState title="Sem histórico de regime" message="Histórico de regimes aparecerá após a detecção de regime executar." />
			{/if}
		</SectionCard>

		<!-- Drift Alerts (40%) -->
		<SectionCard title="Drift Alerts" class="lg:col-span-2">
			<!-- DTW vs Benchmark -->
			<h4 class="mb-2 text-xs font-semibold uppercase tracking-wider text-[var(--netz-text-muted)]">DTW vs Benchmark</h4>
			{#if driftAlerts?.dtw_alerts && driftAlerts.dtw_alerts.length > 0}
				<div class="mb-4 space-y-1">
					{#each driftAlerts.dtw_alerts as alert (alert.instrument_name)}
						<div class="flex items-center justify-between rounded-md bg-[var(--netz-surface-inset)] px-3 py-2 text-sm">
							<span class="text-[var(--netz-text-primary)]">{alert.instrument_name}</span>
							<span class="font-mono" style:color={alert.dtw_score > 0.6 ? "var(--netz-danger)" : alert.dtw_score > 0.4 ? "var(--netz-warning)" : "var(--netz-success)"}>{alert.dtw_score.toFixed(3)}</span>
						</div>
					{/each}
				</div>
				<p class="text-xs text-[var(--netz-text-muted)]">Threshold: 0.60 · Acima é drift significativo vs benchmark</p>
			{:else}
				<p class="mb-4 text-sm text-[var(--netz-text-muted)]">Sem alertas de DTW drift.</p>
			{/if}

			<!-- Behavior Change -->
			<h4 class="mb-2 mt-4 text-xs font-semibold uppercase tracking-wider text-[var(--netz-text-muted)]">Behavior Change</h4>
			{#if driftAlerts?.behavior_change_alerts && driftAlerts.behavior_change_alerts.length > 0}
				<div class="space-y-1">
					{#each driftAlerts.behavior_change_alerts as alert (alert.instrument_name)}
						<div class="flex items-center justify-between rounded-md bg-[var(--netz-surface-inset)] px-3 py-2 text-sm">
							<span class="text-[var(--netz-text-primary)]">{alert.instrument_name}</span>
							<span class="text-xs text-[var(--netz-text-muted)]">{alert.anomalous_count}/{alert.total_metrics} metrics</span>
						</div>
					{/each}
				</div>
			{:else}
				<EmptyState title="" message="Behavior change detection disponível quando strategy_drift_scanner estiver ativo." />
			{/if}
		</SectionCard>
	</div>

	<!-- Macro Indicator Chips -->
	{#if macro}
		<SectionCard title="Macro Indicators">
			<div class="flex flex-wrap gap-3">
				<div class="rounded-lg border border-[var(--netz-border)] bg-[var(--netz-surface-inset)] px-4 py-3">
					<p class="text-xs text-[var(--netz-text-muted)]">VIX</p>
					<p class="text-lg font-semibold" style:color={macro.vix !== null && macro.vix > 25 ? "var(--netz-danger)" : "var(--netz-success)"}>{macro.vix?.toFixed(1) ?? "—"}</p>
				</div>
				<div class="rounded-lg border border-[var(--netz-border)] bg-[var(--netz-surface-inset)] px-4 py-3">
					<p class="text-xs text-[var(--netz-text-muted)]">Yield Curve</p>
					<p class="text-lg font-semibold" style:color={macro.yield_curve_10y2y !== null && macro.yield_curve_10y2y < 0 ? "var(--netz-danger)" : "var(--netz-text-primary)"}>{macro.yield_curve_10y2y !== null ? `${macro.yield_curve_10y2y.toFixed(2)}%` : "—"}</p>
				</div>
				<div class="rounded-lg border border-[var(--netz-border)] bg-[var(--netz-surface-inset)] px-4 py-3">
					<p class="text-xs text-[var(--netz-text-muted)]">CPI YoY</p>
					<p class="text-lg font-semibold text-[var(--netz-text-primary)]">{macro.cpi_yoy?.toFixed(1) ?? "—"}%</p>
				</div>
				<div class="rounded-lg border border-[var(--netz-border)] bg-[var(--netz-surface-inset)] px-4 py-3">
					<p class="text-xs text-[var(--netz-text-muted)]">Fed Funds</p>
					<p class="text-lg font-semibold text-[var(--netz-text-primary)]">{macro.fed_funds_rate?.toFixed(2) ?? "—"}%</p>
				</div>
			</div>
		</SectionCard>
	{/if}
</div>
