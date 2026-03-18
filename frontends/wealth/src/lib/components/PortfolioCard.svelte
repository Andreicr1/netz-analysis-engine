<!--
  PortfolioCard — model portfolio summary card for dashboard.
  Shows: name, NAV, YTD return, CVaR gauge, Sharpe, regime chip.
-->
<script lang="ts">
	import { GaugeChart, StatusBadge, formatNumber, formatPercent, formatRatio, plColor } from "@netz/ui";
	import { resolveWealthStatus } from "$lib/utils/status-maps";

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

	// CVaR gauge thresholds
	const gaugeThresholds = [
		{ value: 70, color: "var(--netz-success)" },
		{ value: 90, color: "var(--netz-warning)" },
		{ value: 100, color: "var(--netz-danger)" },
	];

	let ytdColor = $derived(
		ytdReturn === null ? "var(--netz-text-secondary)" : plColor(ytdReturn),
	);
</script>

<div class="rounded-lg border border-[var(--netz-border)] bg-[var(--netz-surface-elevated)] p-5 shadow-sm">
	<!-- Header -->
	<div class="mb-4 flex items-center justify-between">
		<div>
			<h3 class="text-base font-semibold text-[var(--netz-text-primary)]">{name}</h3>
			<span class="text-xs text-[var(--netz-text-muted)] capitalize">{profile}</span>
		</div>
		{#if regime}
			<StatusBadge status={regime} resolve={resolveWealthStatus} />
		{/if}
	</div>

	<!-- NAV + YTD Return -->
	<div class="mb-4 grid grid-cols-2 gap-3">
		<div>
			<p class="text-xs text-[var(--netz-text-muted)]">NAV</p>
			<p class="text-xl font-bold text-[var(--netz-text-primary)]">{formatNumber(nav, 2, "en-US")}</p>
		</div>
		<div>
			<p class="text-xs text-[var(--netz-text-muted)]">YTD Return</p>
			<p class="text-xl font-bold" style:color={ytdColor}>{formatPercent(ytdReturn, 2, "en-US", true)}</p>
		</div>
	</div>

	<!-- CVaR Gauge -->
	<div class="mb-4">
		<div class="mb-1 flex items-center justify-between">
			<p class="text-xs text-[var(--netz-text-muted)]">CVaR Utilization</p>
			<p class="text-xs text-[var(--netz-text-secondary)]">
				{formatPercent(cvarCurrent, 2, "en-US")} / {formatPercent(cvarLimit, 2, "en-US")}
			</p>
		</div>
		<GaugeChart
			value={cvarUtilization ?? 0}
			min={0}
			max={100}
			thresholds={gaugeThresholds}
			height={120}
			ariaLabel={`CVaR utilization gauge for ${name}`}
		/>
		<p class="mt-1 text-center text-sm font-medium text-[var(--netz-text-primary)]">
			{cvarUtilization !== null ? formatPercent(cvarUtilization / 100, 1, "en-US") : "—"}
		</p>
	</div>

	<!-- Bottom metrics -->
	<div class="grid grid-cols-2 gap-3 border-t border-[var(--netz-border)] pt-3">
		<div>
			<p class="text-xs text-[var(--netz-text-muted)]">Sharpe</p>
			<p class="text-sm font-medium text-[var(--netz-text-primary)]">
				{formatRatio(sharpe, 2, "", "en-US")}
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
