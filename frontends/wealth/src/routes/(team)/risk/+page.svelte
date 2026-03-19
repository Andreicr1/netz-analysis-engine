<!--
  Risk Monitor — Figma frame "CVaR gauges + regime chart + drift" (node 1:7)
  Sections: CVaR utilization bars, Regime area chart, Macro chips, Drift Alerts (DTW + behavior change)
-->
<script lang="ts">
	import {
		Badge,
		StatusBadge,
		RegimeBanner,
		RegimeChart,
		PageHeader,
		EmptyState,
		SectionCard,
		UtilizationBar,
		PeriodSelector,
		ContextPanel,
		MetricCard,
		formatNumber,
		formatPercent,
	} from "@netz/ui";
	import { ActionButton, ConfirmDialog } from "@netz/ui";
	import MacroChips from "$lib/components/MacroChips.svelte";
	import { createClientApiClient } from "$lib/api/client";
	import { invalidateAll } from "$app/navigation";
	import { getContext } from "svelte";
	import { resolveWealthStatus } from "$lib/utils/status-maps";
	import type { PageData } from "./$types";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

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

	// API data — derived from server load
	let cvarByProfile = $derived(data.cvarByProfile as Record<string, CVaRStatus>);
	let cvarHistoryByProfile = $derived(data.cvarHistoryByProfile as Record<string, CVaRPoint[]>);
	let regime = $derived(data.regime as Record<string, string> | null);
	let regimeHistory = $derived(data.regimeHistory as RegimeHistoryPoint[] | null);
	let macro = $derived(data.macro as MacroIndicators | null);
	let driftAlerts = $derived(data.driftAlerts as { dtw_alerts: DtwAlert[]; behavior_change_alerts: BehaviorAlert[] } | null);

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
	const macroSignals = $derived.by(() => {
		const signals: { label: string; value: string }[] = [];
		if (macro?.vix != null) signals.push({ label: "VIX", value: formatNumber(macro.vix, 1, "en-US") });
		if (macro?.yield_curve_10y2y != null) signals.push({ label: "Curve", value: `${formatNumber(macro.yield_curve_10y2y, 2, "en-US")}%` });
		return signals;
	});
	const driftAlertCount = $derived((driftAlerts?.dtw_alerts.length ?? 0) + (driftAlerts?.behavior_change_alerts.length ?? 0));
	const activeBreaches = $derived(
		profiles.filter((profile) => (cvarByProfile[profile]?.cvar_utilized_pct ?? 0) >= 100).length,
	);
	const highestUtilization = $derived.by(() => {
		const values = profiles.map((profile) => cvarByProfile[profile]?.cvar_utilized_pct ?? 0);
		return values.length > 0 ? Math.max(...values) : 0;
	});

	// Period selector for CVaR
	const cvarPeriods = ["1M", "3M", "6M", "12M"];
	let selectedCvarPeriod = $state("12M");

	function fmtPct(v: number | null): string {
		return formatPercent(v, 1, "en-US");
	}

	// ── Drift Scan Trigger ──────────────────────────────────────────────────
	let showDriftScan = $state(false);
	let driftScanning = $state(false);
	let driftError = $state<string | null>(null);

	async function runDriftScan() {
		driftScanning = true;
		showDriftScan = false;
		driftError = null;
		try {
			const api = createClientApiClient(getToken);
			await api.post("/analytics/strategy-drift/scan", {});
			await invalidateAll();
		} catch (e) {
			driftError = e instanceof Error ? e.message : "Drift scan failed";
		} finally {
			driftScanning = false;
		}
	}

	// ── Drift Detail Panel ──────────────────────────────────────────────────
	let driftDetailInstrument = $state<string | null>(null);
	let driftDetailData = $state<Record<string, unknown> | null>(null);
	let driftDetailLoading = $state(false);
	let showDriftDetail = $derived(driftDetailData !== null);

	async function loadDriftDetail(instrumentId: string, instrumentName: string) {
		driftDetailInstrument = instrumentName;
		driftDetailLoading = true;
		try {
			const api = createClientApiClient(getToken);
			driftDetailData = await api.get(`/analytics/strategy-drift/${instrumentId}`);
		} catch {
			driftDetailData = null;
		} finally {
			driftDetailLoading = false;
		}
	}
</script>

<div class="space-y-(--netz-space-section-gap) p-(--netz-space-page-gutter)">
	<RegimeBanner regime={currentRegime} signals={macroSignals} macroHref="/macro" />

	<PageHeader title="Risk Monitor">
		{#snippet actions()}
			<div class="flex items-center gap-2">
				<ActionButton
					size="sm"
					variant="outline"
					onclick={() => showDriftScan = true}
					loading={driftScanning}
					loadingText="Scanning..."
				>
					Run Drift Scan
				</ActionButton>
				{#if currentRegime}
					<StatusBadge status={currentRegime} resolve={resolveWealthStatus} />
				{/if}
			</div>
		{/snippet}
	</PageHeader>
	<p class="-mt-3 text-sm text-(--netz-text-muted)">
		Deep risk diagnostics across CVaR utilization, macro regime context, and drift surveillance.
	</p>

	<div class="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
		<MetricCard label="Current Regime" value={currentRegime ?? "RISK_ON"} sublabel="Macro engine status" status={currentRegime && currentRegime !== "RISK_ON" ? "warn" : "ok"} />
		<MetricCard label="Profiles In Breach" value={String(activeBreaches)} sublabel="Utilization at or above 100%" status={activeBreaches > 0 ? "breach" : "ok"} />
		<MetricCard label="Highest Utilization" value={`${formatNumber(highestUtilization, 0, "en-US")}%`} sublabel="Across monitored profiles" status={highestUtilization >= 100 ? "breach" : highestUtilization >= 85 ? "warn" : "ok"} />
		<MetricCard label="Open Drift Alerts" value={String(driftAlertCount)} sublabel="DTW and behavior-change signals" status={driftAlertCount > 0 ? "warn" : undefined} />
	</div>

	{#if driftError}
		<div class="rounded-md border border-(--netz-status-error) bg-(--netz-status-error)/10 p-3 text-sm text-(--netz-status-error)">
			{driftError}
		</div>
	{/if}

	<!-- CVaR 95% — Utilização por Portfólio -->
	<SectionCard title="CVaR 95% — Utilização por Portfólio" subtitle="Rolling 12M · Limite configurado por perfil de risco">
		{#snippet actions()}
			<PeriodSelector periods={cvarPeriods} selected={selectedCvarPeriod} onSelect={(p) => selectedCvarPeriod = p} />
		{/snippet}

		<div class="space-y-4">
			{#each profiles as profile (profile)}
				{@const cvar = cvarByProfile[profile] as CVaRStatus | undefined}
				<div class="rounded-(--netz-radius-md) border border-(--netz-border-subtle) bg-(--netz-surface-highlight) px-4 py-3">
					<div class="mb-3 flex flex-wrap items-center justify-between gap-3">
						<div>
							<p class="text-sm font-medium capitalize text-(--netz-text-primary)">{profileLabels[profile] ?? profile}</p>
							<p class="mt-1 text-xs text-(--netz-text-muted)">
								{cvar?.trigger_status ?? "stable"}
								{#if cvar && cvar.consecutive_breach_days > 0}
									· {cvar.consecutive_breach_days} breach day{cvar.consecutive_breach_days === 1 ? "" : "s"}
								{/if}
							</p>
						</div>
						{#if cvar?.regime}
							<Badge variant={cvar.cvar_utilized_pct != null && cvar.cvar_utilized_pct >= 100 ? "destructive" : "secondary"}>
								{cvar.regime}
							</Badge>
						{/if}
					</div>
					<div class="flex items-center gap-4">
						<span class="w-28 shrink-0 text-sm font-medium capitalize text-(--netz-text-primary)">{profileLabels[profile] ?? profile}</span>
					<div class="flex-1">
						<UtilizationBar
							current={cvar?.cvar_utilized_pct ?? 0}
							limit={100}
							showValues={false}
						/>
					</div>
						<span class="w-32 shrink-0 text-right text-sm font-mono text-(--netz-text-secondary)">
						{fmtPct(cvar?.cvar_current ?? null)} / {fmtPct(cvar?.cvar_limit ?? null)}
					</span>
					</div>
				</div>
			{/each}
		</div>
	</SectionCard>

	<!-- Regime de Mercado + Drift Alerts side-by-side -->
	<div class="grid gap-4 lg:grid-cols-5">
		<!-- Regime Chart (60%) -->
		<SectionCard title="Regime de Mercado — FRED Indicators" class="lg:col-span-3">
			{#snippet actions()}
				{#if currentRegime}
					<StatusBadge status={currentRegime} resolve={resolveWealthStatus} />
				{/if}
			{/snippet}
			{#if regimeBands.length > 0}
				<div class="h-64">
					<RegimeChart series={cvarSeries.slice(0, 1)} regimes={regimeBands} ariaLabel="Market regime history chart" />
				</div>
			{:else}
				<EmptyState title="Sem histórico de regime" message="Histórico de regimes aparecerá após a detecção de regime executar." />
			{/if}
		</SectionCard>

		<!-- Drift Alerts (40%) -->
		<SectionCard title="Drift Alerts" subtitle="Threshold: 0.60 = drift significativo vs benchmark" class="lg:col-span-2">
			<!-- DTW vs Benchmark -->
			<h4 class="mb-2 text-xs font-semibold uppercase tracking-wider text-(--netz-text-muted)">DTW vs Benchmark</h4>
			{#if driftAlerts?.dtw_alerts && driftAlerts.dtw_alerts.length > 0}
				<div class="mb-4 space-y-1">
					{#each driftAlerts.dtw_alerts as alert (alert.instrument_name)}
						<div class="flex items-center justify-between rounded-(--netz-radius-md) border border-(--netz-border-subtle) bg-(--netz-surface-highlight) px-3 py-2 text-sm">
							<span class="text-(--netz-text-primary)">{alert.instrument_name}</span>
							<span class="font-mono" style:color={alert.dtw_score > 0.6 ? "var(--netz-danger)" : alert.dtw_score > 0.4 ? "var(--netz-warning)" : "var(--netz-success)"}>
								{formatNumber(alert.dtw_score, 3, "en-US")}
							</span>
						</div>
					{/each}
				</div>
				<p class="text-xs text-(--netz-text-muted)">Threshold: 0.60 · Acima é drift significativo vs benchmark</p>
			{:else}
				<p class="mb-4 text-sm text-(--netz-text-muted)">Sem alertas de DTW drift.</p>
			{/if}

			<!-- Behavior Change -->
			<h4 class="mb-2 mt-4 text-xs font-semibold uppercase tracking-wider text-(--netz-text-muted)">Behavior Change</h4>
			{#if driftAlerts?.behavior_change_alerts && driftAlerts.behavior_change_alerts.length > 0}
				<div class="space-y-1">
					{#each driftAlerts.behavior_change_alerts as alert (alert.instrument_name)}
						<div class="flex items-center justify-between rounded-(--netz-radius-md) border border-(--netz-border-subtle) bg-(--netz-surface-highlight) px-3 py-2 text-sm">
							<span class="text-(--netz-text-primary)">{alert.instrument_name}</span>
							<span class="text-xs text-(--netz-text-muted)">{alert.anomalous_count}/{alert.total_metrics} metrics</span>
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
			<MacroChips {macro} />
		</SectionCard>
	{/if}
</div>

<!-- Drift Scan Confirm Dialog -->
<ConfirmDialog
	bind:open={showDriftScan}
	title="Run Strategy Drift Scan"
	message="This will analyze all instruments for strategy drift against benchmarks. Continue?"
	confirmLabel="Run Scan"
	confirmVariant="default"
	onConfirm={runDriftScan}
	onCancel={() => showDriftScan = false}
/>

<!-- Drift Detail Panel -->
{#if showDriftDetail}
	<ContextPanel
		open={showDriftDetail}
		title={`Drift: ${driftDetailInstrument ?? "Instrument"}`}
		onClose={() => { driftDetailData = null; driftDetailInstrument = null; }}
	>
		<div class="space-y-3 p-4">
			{#if driftDetailLoading}
				<p class="text-sm text-(--netz-text-muted)">Loading...</p>
			{:else if driftDetailData}
				{#each Object.entries(driftDetailData) as [key, value]}
					<div>
						<p class="text-xs text-(--netz-text-muted)">{key}</p>
						<p class="text-sm text-(--netz-text-primary)">{typeof value === "number" ? formatNumber(value, 4, "en-US") : String(value ?? "—")}</p>
					</div>
				{/each}
			{:else}
				<p class="text-sm text-(--netz-text-muted)">No drift data available.</p>
			{/if}
		</div>
	</ContextPanel>
{/if}
