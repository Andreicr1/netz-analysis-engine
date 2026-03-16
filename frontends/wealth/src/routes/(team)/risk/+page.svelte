<!--
  Risk Monitor — CVaR timelines with limit lines, regime bands, macro indicators.
-->
<script lang="ts">
	import { DataCard, StatusBadge, TimeSeriesChart, RegimeChart, PageHeader, EmptyState } from "@netz/ui";
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

	type CVaRPoint = {
		date: string;
		cvar: number;
	};

	type MacroIndicators = {
		vix: number | null;
		yield_curve_10y2y: number | null;
		cpi_yoy: number | null;
		fed_funds_rate: number | null;
	};

	type RegimeHistoryPoint = {
		date: string;
		regime: string;
	};

	let cvarByProfile = $derived(data.cvarByProfile as Record<string, CVaRStatus>);
	let cvarHistoryByProfile = $derived(data.cvarHistoryByProfile as Record<string, CVaRPoint[]>);
	let regime = $derived(data.regime as Record<string, string> | null);
	let regimeHistory = $derived(data.regimeHistory as RegimeHistoryPoint[] | null);
	let macro = $derived(data.macro as MacroIndicators | null);

	const profiles = ["conservative", "moderate", "growth"];

	// CVaR history chart series — one per profile
	let cvarSeries = $derived(
		profiles
			.filter((p) => cvarHistoryByProfile[p])
			.map((p) => ({
				name: p,
				data: ((cvarHistoryByProfile[p] ?? []) as CVaRPoint[]).map(
					(point) => [point.date, point.cvar * 100] as [string, number],
				),
			})),
	);

	// Regime chart data — transform history into series + regime bands
	type RegimeType = "RISK_ON" | "RISK_OFF" | "INFLATION" | "CRISIS";

	let regimeBands = $derived.by(() => {
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
		bands.push({ start: current.date, end: regimeHistory[regimeHistory.length - 1]!.date, type: current.regime as RegimeType });
		return bands;
	});

	function fmtPct(v: number | null): string {
		if (v === null) return "—";
		return `${(v * 100).toFixed(2)}%`;
	}

	let currentRegime = $derived(regime?.regime ?? null);
</script>

<div class="space-y-6 p-6">
	<PageHeader title="Risk Monitor">
		{#snippet actions()}
			{#if currentRegime}
				<StatusBadge status={currentRegime} />
			{/if}
		{/snippet}
	</PageHeader>

	<!-- CVaR Status Cards -->
	<div class="grid gap-4 md:grid-cols-3">
		{#each profiles as profile (profile)}
			{@const cvar = cvarByProfile[profile] as CVaRStatus | undefined}
			<div class="rounded-lg border border-[var(--netz-border)] bg-white p-4">
				<div class="mb-2 flex items-center justify-between">
					<h3 class="text-sm font-semibold capitalize text-[var(--netz-text-primary)]">{profile}</h3>
					{#if cvar?.trigger_status}
						<StatusBadge status={cvar.trigger_status} />
					{/if}
				</div>
				<div class="grid grid-cols-3 gap-2">
					<div>
						<p class="text-xs text-[var(--netz-text-muted)]">CVaR</p>
						<p class="text-sm font-medium text-[var(--netz-text-primary)]">{fmtPct(cvar?.cvar_current ?? null)}</p>
					</div>
					<div>
						<p class="text-xs text-[var(--netz-text-muted)]">Limit</p>
						<p class="text-sm font-medium text-[var(--netz-text-primary)]">{fmtPct(cvar?.cvar_limit ?? null)}</p>
					</div>
					<div>
						<p class="text-xs text-[var(--netz-text-muted)]">Utilization</p>
						<p class="text-sm font-medium text-[var(--netz-text-primary)]">
							{cvar?.cvar_utilized_pct != null ? `${cvar.cvar_utilized_pct.toFixed(1)}%` : "—"}
						</p>
					</div>
				</div>
				{#if cvar && cvar.consecutive_breach_days > 0}
					<p class="mt-2 text-xs text-[var(--netz-danger,#ef4444)]">
						Breach: {cvar.consecutive_breach_days} consecutive days
					</p>
				{/if}
			</div>
		{/each}
	</div>

	<!-- CVaR Timeline -->
	<div class="rounded-lg border border-[var(--netz-border)] bg-white p-5">
		<h3 class="mb-4 text-sm font-semibold text-[var(--netz-text-primary)]">CVaR Timeline</h3>
		{#if cvarSeries.length > 0}
			<div class="h-80">
				<TimeSeriesChart
					series={cvarSeries}
					yAxisLabel="CVaR (%)"
				/>
			</div>
		{:else}
			<EmptyState title="No CVaR History" message="CVaR timeline will populate after risk calculations run." />
		{/if}
	</div>

	<!-- Regime Timeline -->
	<div class="rounded-lg border border-[var(--netz-border)] bg-white p-5">
		<h3 class="mb-4 text-sm font-semibold text-[var(--netz-text-primary)]">Regime Timeline</h3>
		{#if regimeBands.length > 0}
			<div class="h-48">
				<RegimeChart series={[]} regimes={regimeBands} />
			</div>
		{:else}
			<EmptyState title="No Regime History" message="Regime history will appear once regime detection runs." />
		{/if}
	</div>

	<!-- Macro Indicators -->
	{#if macro}
		<div class="rounded-lg border border-[var(--netz-border)] bg-white p-5">
			<h3 class="mb-4 text-sm font-semibold text-[var(--netz-text-primary)]">Macro Indicators</h3>
			<div class="grid gap-4 md:grid-cols-4">
				<DataCard label="VIX" value={macro.vix !== null ? macro.vix.toFixed(1) : "—"} trend="flat" />
				<DataCard label="Yield Curve (10Y-2Y)" value={macro.yield_curve_10y2y !== null ? `${macro.yield_curve_10y2y.toFixed(2)}%` : "—"} trend="flat" />
				<DataCard label="CPI YoY" value={macro.cpi_yoy !== null ? `${macro.cpi_yoy.toFixed(1)}%` : "—"} trend="flat" />
				<DataCard label="Fed Funds Rate" value={macro.fed_funds_rate !== null ? `${macro.fed_funds_rate.toFixed(2)}%` : "—"} trend="flat" />
			</div>
		</div>
	{/if}
</div>
