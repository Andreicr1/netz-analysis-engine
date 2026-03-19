<!--
  PortfolioCard — model portfolio summary card for dashboard.
  Layout matches Figma spec: large NAV, inline CVaR/utilization/Sharpe, bar indicator.
-->
<script lang="ts">
	import { Badge, StatusBadge, formatCurrency, formatPercent, formatNumber, plColor } from "@netz/ui";
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
		name, profile,
		nav = null, ytdReturn = null,
		cvarCurrent = null, cvarLimit = null,
		cvarUtilization = null, sharpe = null,
		regime = null, triggerStatus = null,
	}: Props = $props();

	let ytdColor = $derived(
		ytdReturn === null ? "var(--netz-text-muted)" : plColor(ytdReturn)
	);

	// Bar color based on utilization
	let barColor = $derived(() => {
		if (cvarUtilization === null) return "var(--netz-text-muted)";
		if (cvarUtilization >= 100) return "var(--netz-danger)";
		if (cvarUtilization >= 85) return "var(--netz-warning)";
		return "var(--netz-success)";
	});

	let barWidth = $derived(
		cvarUtilization !== null ? Math.min(cvarUtilization, 100) + "%" : "0%"
	);

	// CVaR color
	let cvarColor = $derived(() => {
		if (cvarUtilization === null) return "var(--netz-text-secondary)";
		if (cvarUtilization >= 100) return "var(--netz-danger)";
		if (cvarUtilization >= 85) return "var(--netz-warning)";
		return "var(--netz-text-primary)";
	});

	// Profile display label
	const profileLabels: Record<string, string> = {
		conservative: "Conservative",
		moderate: "Moderate",
		growth: "Aggressive",
	};
	let profileLabel = $derived(profileLabels[profile] ?? profile);
</script>

<div class="flex h-full flex-col overflow-hidden rounded-[var(--netz-radius-xl)] border border-[var(--netz-border-subtle)] bg-[var(--netz-surface-panel)] p-[var(--netz-space-card-padding-lg)] shadow-[var(--netz-shadow-card)]">

	<!-- Header: name + profile badge -->
	<div class="mb-4 flex items-start justify-between gap-3">
		<div class="space-y-2">
			<p class="netz-ui-kicker">Model Portfolio</p>
			<h3 class="text-base font-semibold tracking-[-0.015em] text-[var(--netz-text-primary)]">{name}</h3>
		</div>
		<Badge variant="secondary" class="shrink-0">{profileLabel}</Badge>
	</div>

	<!-- NAV — dominant value -->
	<div class="mb-2">
		<p class="font-mono text-[2rem] font-semibold leading-none tracking-[-0.04em] text-[var(--netz-text-primary)]">
			{nav !== null ? formatCurrency(nav, "USD", "en-US") : "—"}
		</p>
	</div>

	<!-- NAV · YTD line -->
	<p class="mb-5 text-sm text-[var(--netz-text-secondary)]">
		NAV
		{#if ytdReturn !== null}
			·
			<span style:color={ytdColor} class="font-semibold">
				{formatPercent(ytdReturn, 1, "en-US", true)} YTD
			</span>
		{/if}
	</p>

	<!-- Status strip -->
	<div class="mb-5 flex flex-wrap items-center gap-2">
		{#if regime}
			<StatusBadge status={regime} resolve={resolveWealthStatus} />
		{/if}
		{#if triggerStatus === "breach"}
			<Badge variant="destructive">Action Required</Badge>
		{:else if triggerStatus === "warning"}
			<Badge variant="outline">Monitor</Badge>
		{/if}
	</div>

	<!-- Three metrics row -->
	<div class="mb-5 grid grid-cols-3 gap-3">
		<div class="rounded-[var(--netz-radius-md)] border border-[var(--netz-border-subtle)] bg-[var(--netz-surface-elevated)] p-3 shadow-[var(--netz-shadow-1)]">
			<p class="mb-1 text-[11px] font-semibold uppercase tracking-[0.08em] text-[var(--netz-text-muted)]">CVaR 95%</p>
			<p class="text-sm font-semibold tracking-[-0.01em]" style:color={cvarColor()}>
				{formatPercent(cvarCurrent, 1, "en-US")}
			</p>
			<p class="mt-1 text-xs text-[var(--netz-text-muted)]">
				lim {formatPercent(cvarLimit, 1, "en-US")}
			</p>
		</div>
		<div class="rounded-[var(--netz-radius-md)] border border-[var(--netz-border-subtle)] bg-[var(--netz-surface-elevated)] p-3 shadow-[var(--netz-shadow-1)]">
			<p class="mb-1 text-[11px] font-semibold uppercase tracking-[0.08em] text-[var(--netz-text-muted)]">Utilização</p>
			<p class="text-sm font-semibold tracking-[-0.01em]" style:color={barColor()}>
				{cvarUtilization !== null ? formatNumber(cvarUtilization, 0, "en-US") + "%" : "—"}
			</p>
		</div>
		<div class="rounded-[var(--netz-radius-md)] border border-[var(--netz-border-subtle)] bg-[var(--netz-surface-elevated)] p-3 shadow-[var(--netz-shadow-1)]">
			<p class="mb-1 text-[11px] font-semibold uppercase tracking-[0.08em] text-[var(--netz-text-muted)]">Sharpe</p>
			<p class="text-sm font-semibold tracking-[-0.01em] text-[var(--netz-success)]">
				{sharpe !== null ? formatNumber(sharpe, 2, "en-US") : "—"}
			</p>
		</div>
	</div>

	<!-- Utilization bar -->
	<div class="mt-auto space-y-2">
		<div class="flex items-center justify-between text-[11px] font-semibold uppercase tracking-[0.08em] text-[var(--netz-text-muted)]">
			<span>Risk utilization</span>
			<span>{cvarUtilization !== null ? formatNumber(cvarUtilization, 0, "en-US") + "%" : "—"}</span>
		</div>
		<div class="h-2 w-full overflow-hidden rounded-full bg-[var(--netz-surface-inset)]">
		<div
			class="h-full rounded-full transition-all duration-500"
			style:width={barWidth}
			style:background-color={barColor()}
		></div>
		</div>
	</div>
</div>
