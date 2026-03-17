<!--
  PortfolioCard — model portfolio summary card for dashboard.
  Shows: name, NAV, YTD return, CVaR gauge, Sharpe, regime chip.
-->
<script lang="ts">
	import { DataCard, StatusBadge, GaugeChart } from "@netz/ui";

	interface Props {
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

	let {
		name,
		profile,
		nav = null,
		ytdReturn = null,
		cvarCurrent = null,
		cvarLimit = null,
		cvarUtilization = null,
		sharpe = null,
		regime = null,
		triggerStatus = null,
	}: Props = $props();

	// Format helpers
	function formatNav(value: number | null): string {
		if (value === null) return "—";
		return new Intl.NumberFormat("en-US", {
			style: "decimal",
			minimumFractionDigits: 2,
			maximumFractionDigits: 2,
		}).format(value);
	}

	function formatPercent(value: number | null): string {
		if (value === null) return "—";
		const sign = value >= 0 ? "+" : "";
		return `${sign}${(value * 100).toFixed(2)}%`;
	}

	function formatCvar(value: number | null): string {
		if (value === null) return "—";
		return `${(value * 100).toFixed(2)}%`;
	}

	// CVaR gauge thresholds
	let gaugeThresholds = $derived([
		{ value: 70, color: "var(--netz-success, #22c55e)" },
		{ value: 90, color: "var(--netz-warning, #f59e0b)" },
		{ value: 100, color: "var(--netz-danger, #ef4444)" },
	]);

	let ytdColor = $derived(
		ytdReturn === null ? "var(--netz-text-secondary)" :
		ytdReturn >= 0 ? "var(--netz-success, #22c55e)" :
		"var(--netz-danger, #ef4444)"
	);

	// Regime display name mapping
	const regimeLabels: Record<string, string> = {
		RISK_ON: "Risk On",
		RISK_OFF: "Risk Off",
		INFLATION: "Inflation",
		CRISIS: "Crisis",
	};
</script>

<div class="rounded-lg border border-[var(--netz-border)] bg-[var(--netz-surface-elevated)] p-5 shadow-sm">
	<!-- Header -->
	<div class="mb-4 flex items-center justify-between">
		<div>
			<h3 class="text-base font-semibold text-[var(--netz-text-primary)]">{name}</h3>
			<span class="text-xs text-[var(--netz-text-muted)] capitalize">{profile}</span>
		</div>
		{#if regime}
			<StatusBadge status={regime} />
		{/if}
	</div>

	<!-- NAV + YTD Return -->
	<div class="mb-4 grid grid-cols-2 gap-3">
		<div>
			<p class="text-xs text-[var(--netz-text-muted)]">NAV</p>
			<p class="text-xl font-bold text-[var(--netz-text-primary)]">{formatNav(nav)}</p>
		</div>
		<div>
			<p class="text-xs text-[var(--netz-text-muted)]">YTD Return</p>
			<p class="text-xl font-bold" style:color={ytdColor}>{formatPercent(ytdReturn)}</p>
		</div>
	</div>

	<!-- CVaR Gauge -->
	<div class="mb-4">
		<div class="mb-1 flex items-center justify-between">
			<p class="text-xs text-[var(--netz-text-muted)]">CVaR Utilization</p>
			<p class="text-xs text-[var(--netz-text-secondary)]">
				{formatCvar(cvarCurrent)} / {formatCvar(cvarLimit)}
			</p>
		</div>
		<GaugeChart
			value={cvarUtilization ?? 0}
			min={0}
			max={100}
			thresholds={gaugeThresholds}
			height={120}
		/>
		<p class="mt-1 text-center text-sm font-medium text-[var(--netz-text-primary)]">
			{cvarUtilization !== null ? `${cvarUtilization.toFixed(1)}%` : "—"}
		</p>
	</div>

	<!-- Bottom metrics -->
	<div class="grid grid-cols-2 gap-3 border-t border-[var(--netz-border)] pt-3">
		<div>
			<p class="text-xs text-[var(--netz-text-muted)]">Sharpe</p>
			<p class="text-sm font-medium text-[var(--netz-text-primary)]">
				{sharpe !== null ? sharpe.toFixed(2) : "—"}
			</p>
		</div>
		<div>
			<p class="text-xs text-[var(--netz-text-muted)]">Trigger</p>
			<p class="text-sm font-medium text-[var(--netz-text-primary)] capitalize">
				{triggerStatus ?? "—"}
			</p>
		</div>
	</div>
</div>
