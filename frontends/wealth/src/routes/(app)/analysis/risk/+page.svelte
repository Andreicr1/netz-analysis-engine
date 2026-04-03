<!--
  Risk Workstation — Command dashboard wired to SSE riskStore.
  Panels: Connection status, Regime, CVaR per profile, CVaR History, Drift Alerts.
  Reactive: regime/trigger changes flash via CSS transition on $derived state.
-->
<script lang="ts">
	import { getContext, onMount } from "svelte";
	import {
		PageHeader, StatusBadge,
		formatPercent, formatDateTime, formatNumber,
	} from "@investintell/ui";
	import type { RiskStore, CVaRStatus, CVaRPoint, DriftAlert, BehaviorAlert, RegimeData } from "$lib/stores/risk-store.svelte";

	let { data } = $props();

	const riskStore = getContext<RiskStore>("netz:riskStore");

	onMount(() => {
		try {
			const hasSsrData = data.riskSummary || data.regime;
			if (hasSsrData) {
				riskStore.seedFromSSR({
					riskSummary: data.riskSummary as Record<string, unknown> | null,
					regime: data.regime as RegimeData | null,
					driftAlerts: data.alerts as { dtw_alerts: DriftAlert[]; behavior_change_alerts: BehaviorAlert[] } | null,
				});
				riskStore.start(true);
			} else {
				riskStore.start(false);
			}
		} catch (e) {
			console.warn("Risk store failed to start:", e);
		}
		return () => riskStore.destroy();
	});

	// ── Derived reactive state from SSE ticks ─────────────────────────────

	let profiles = $derived(Object.entries(riskStore.cvarByProfile ?? {}) as [string, CVaRStatus][]);
	let regime = $derived(riskStore.regime);
	let connectionQuality = $derived(riskStore.connectionQuality);
	let storeStatus = $derived(riskStore.status);
	let dtwAlerts = $derived(riskStore.driftAlerts?.dtw_alerts ?? []);
	let behaviorAlerts = $derived(riskStore.driftAlerts?.behavior_change_alerts ?? []);
	let totalAlerts = $derived(dtwAlerts.length + behaviorAlerts.length);

	// ── Regime severity for visual flash ──────────────────────────────────

	function regimeColor(r: string | null | undefined): string {
		switch (r) {
			case "crisis":   return "var(--ii-danger)";
			case "stress":   return "var(--ii-warning)";
			case "low_vol":  return "var(--ii-info)";
			case "normal":   return "var(--ii-success)";
			default:         return "var(--ii-text-muted)";
		}
	}

	function triggerColor(t: string | null | undefined): string {
		switch (t) {
			case "hard_stop": return "var(--ii-danger)";
			case "breach":    return "var(--ii-danger)";
			case "warning":   return "var(--ii-warning)";
			case "ok":        return "var(--ii-success)";
			default:          return "var(--ii-text-muted)";
		}
	}

	function pctNum(v: string | number | null | undefined): number | null {
		if (v === null || v === undefined) return null;
		return typeof v === "string" ? parseFloat(v) : v;
	}

	function fmtPct(v: string | number | null | undefined): string {
		const n = pctNum(v);
		if (n === null || isNaN(n)) return "—";
		return formatPercent(n);
	}

	// ── Aggregate risk summary ──────────────────────────────────────────
	let worstUtil = $derived(
		profiles.reduce((max, [, c]) => {
			const u = pctNum(c.cvar_utilized_pct);
			return u !== null && u > max ? u : max;
		}, 0)
	);
	let breachedCount = $derived(
		profiles.filter(([, c]) => c.trigger_status === "breach" || c.trigger_status === "hard_stop").length
	);
	let warningCount = $derived(
		profiles.filter(([, c]) => c.trigger_status === "warning").length
	);

	// ── CVaR history sparkline (CSS-only mini bar chart) ──────────────────

	function sparkBars(history: CVaRPoint[] | undefined | null): { value: number; date: string }[] {
		if (!Array.isArray(history)) return [];
		const tail = history.slice(-20);
		if (tail.length === 0) return [];
		const max = Math.max(...tail.map((p) => Math.abs(p.cvar)), 0.001);
		return tail.map((p) => ({ value: (Math.abs(p.cvar) / max) * 100, date: p.date }));
	}

	// ── Connection badge ──────────────────────────────────────────────────

	function connectionLabel(q: string): string {
		switch (q) {
			case "live":     return "Live";
			case "degraded": return "Degraded";
			case "offline":  return "Offline";
			default:         return q;
		}
	}

	function connectionColor(q: string): string {
		switch (q) {
			case "live":     return "var(--ii-success)";
			case "degraded": return "var(--ii-warning)";
			case "offline":  return "var(--ii-danger)";
			default:         return "var(--ii-text-muted)";
		}
	}
</script>

<PageHeader title="Risk Monitor">
	{#snippet actions()}
		<div class="rw-status-bar">
			<span class="rw-conn-dot" style:background={connectionColor(connectionQuality)}></span>
			<span class="rw-conn-label" style:color={connectionColor(connectionQuality)}>
				{connectionLabel(connectionQuality)}
			</span>
			{#if riskStore.computedAt}
				<span class="rw-computed-at">
					{formatDateTime(riskStore.computedAt)}
				</span>
			{/if}
			<button class="rw-refresh" onclick={() => riskStore.refresh()}>Refresh</button>
		</div>
	{/snippet}
</PageHeader>

{#if storeStatus === "loading" && profiles.length === 0}
	<div class="rw-loading">
		<p class="rw-loading-text">Connecting to risk data...</p>
	</div>
{/if}

<div class="rw-grid">
	<!-- ═══════════════════════════════════════════════════════════════════ -->
	<!-- ROW 0: Aggregate Risk Summary                                      -->
	<!-- ═══════════════════════════════════════════════════════════════════ -->
	{#if profiles.length > 0}
		<section class="rw-panel rw-panel--summary">
			<div class="summary-grid">
				<div class="summary-card">
					<span class="summary-label">Profiles</span>
					<span class="summary-value">{profiles.length}</span>
				</div>
				<div class="summary-card">
					<span class="summary-label">Worst Utilization</span>
					<span class="summary-value" style:color={worstUtil > 90 ? "var(--ii-danger)" : worstUtil > 70 ? "var(--ii-warning)" : "var(--ii-text-primary)"}>
						{formatPercent(worstUtil / 100)}
					</span>
				</div>
				<div class="summary-card">
					<span class="summary-label">Breached</span>
					<span class="summary-value" style:color={breachedCount > 0 ? "var(--ii-danger)" : "var(--ii-success)"}>{breachedCount}</span>
				</div>
				<div class="summary-card">
					<span class="summary-label">Warnings</span>
					<span class="summary-value" style:color={warningCount > 0 ? "var(--ii-warning)" : "var(--ii-success)"}>{warningCount}</span>
				</div>
				<div class="summary-card">
					<span class="summary-label">Drift Alerts</span>
					<span class="summary-value" style:color={totalAlerts > 0 ? "var(--ii-warning)" : "var(--ii-text-muted)"}>{totalAlerts}</span>
				</div>
			</div>
		</section>
	{/if}

	<!-- ═══════════════════════════════════════════════════════════════════ -->
	<!-- ROW 1: Regime + Connection                                         -->
	<!-- ═══════════════════════════════════════════════════════════════════ -->
	<section class="rw-panel rw-panel--regime">
		<h3 class="rw-panel-title">Market Regime</h3>
		{#if regime}
			<div class="regime-hero" style:color={regimeColor(regime?.regime)}>
				<span class="regime-name">{(regime?.regime ?? "UNKNOWN").toUpperCase()}</span>
				{#if regime?.confidence != null}
					<span class="regime-confidence">{(regime.confidence * 100).toFixed(0)}%</span>
				{/if}
			</div>
			{#if regime?.timestamp}
				<span class="regime-ts">{formatDateTime(regime.timestamp)}</span>
			{/if}
		{:else}
			<div class="rw-empty">No regime data</div>
		{/if}

		<!-- Regime history mini-timeline -->
		{#if riskStore.regimeHistory.length > 0}
			<div class="regime-timeline">
				{#each riskStore.regimeHistory.slice(-12) as entry (entry.date)}
					<div
						class="regime-dot"
						style:background={regimeColor(entry.regime)}
						title="{entry.date}: {entry.regime}"
					></div>
				{/each}
			</div>
		{/if}
	</section>

	<section class="rw-panel rw-panel--alerts">
		<h3 class="rw-panel-title">
			Drift Alerts
			{#if totalAlerts > 0}
				<span class="rw-alert-count">{totalAlerts}</span>
			{/if}
		</h3>
		{#if totalAlerts === 0}
			<div class="rw-empty">No active alerts</div>
		{:else}
			<div class="alert-list">
				{#each dtwAlerts as alert (alert.instrument_name)}
					<div class="alert-row">
						<span class="alert-name">{alert.instrument_name}</span>
						<span class="alert-tag alert-tag--dtw">DTW {alert.dtw_score != null ? alert.dtw_score.toFixed(2) : "—"}</span>
					</div>
				{/each}
				{#each behaviorAlerts as alert (alert.instrument_name)}
					<div class="alert-row">
						<span class="alert-name">{alert.instrument_name}</span>
						<span class="alert-tag alert-tag--behavior">{alert.severity}</span>
						<span class="alert-meta">{alert.anomalous_count}/{alert.total_metrics}</span>
					</div>
				{/each}
			</div>
		{/if}
	</section>

	<!-- ═══════════════════════════════════════════════════════════════════ -->
	<!-- ROW 2: CVaR per profile (one card per profile)                     -->
	<!-- ═══════════════════════════════════════════════════════════════════ -->
	{#each profiles as [profileId, cvar] (profileId)}
		{@const utilPct = pctNum(cvar.cvar_utilized_pct)}
		{@const isBreached = cvar.trigger_status === "breach" || cvar.trigger_status === "hard_stop"}
		{@const isWarning = cvar.trigger_status === "warning"}
		<section
			class="rw-panel rw-panel--cvar"
			class:rw-panel--flash-danger={isBreached}
			class:rw-panel--flash-warning={isWarning}
		>
			<div class="cvar-header">
				<h3 class="cvar-profile">{profileId}</h3>
				<StatusBadge status={cvar.trigger_status ?? "ok"} />
			</div>

			<div class="cvar-hero">
				<span class="cvar-value" style:color={triggerColor(cvar.trigger_status)}>
					{fmtPct(cvar.cvar_current)}
				</span>
				<span class="cvar-limit-label">
					Limit: {fmtPct(cvar.cvar_limit)}
				</span>
			</div>

			<!-- Utilization bar -->
			<div class="cvar-util-track">
				<div
					class="cvar-util-fill"
					style:width="{Math.min(utilPct ?? 0, 120)}%"
					style:background={triggerColor(cvar.trigger_status)}
				></div>
				{#if utilPct !== null}
					<span class="cvar-util-label">{utilPct.toFixed(1)}%</span>
				{/if}
			</div>

			<div class="cvar-meta">
				<div class="cvar-kv">
					<span class="cvar-k">Regime</span>
					<span class="cvar-v" style:color={regimeColor(cvar.regime)}>{cvar.regime ?? "—"}</span>
				</div>
				<div class="cvar-kv">
					<span class="cvar-k">Breach Days</span>
					<span class="cvar-v" style:color={cvar.consecutive_breach_days > 0 ? "var(--ii-danger)" : "var(--ii-text-primary)"}>
						{cvar.consecutive_breach_days}
					</span>
				</div>
			</div>

			<!-- CVaR history sparkline -->
			{#if (riskStore.cvarHistoryByProfile[profileId] ?? []).length > 0}
				{@const bars = sparkBars(riskStore.cvarHistoryByProfile[profileId]!)}
				<div class="spark-container">
					{#each bars as bar (bar.date)}
						<div class="spark-bar" style:height="{bar.value}%" title="{bar.date}"></div>
					{/each}
				</div>
			{/if}
		</section>
	{/each}

	<!-- ═══════════════════════════════════════════════════════════════════ -->
	<!-- ROW 3: Macro indicators (if available)                             -->
	<!-- ═══════════════════════════════════════════════════════════════════ -->
	{#if riskStore.macroIndicators}
		<section class="rw-panel rw-panel--macro">
			<h3 class="rw-panel-title">Macro Indicators</h3>
			<div class="macro-grid">
				{#each Object.entries(riskStore.macroIndicators) as [key, value] (key)}
					<div class="macro-kv">
						<span class="macro-k">{key}</span>
						<span class="macro-v">{typeof value === "number" ? formatNumber(value) : String(value ?? "—")}</span>
					</div>
				{/each}
			</div>
		</section>
	{/if}
</div>

<style>
	/* ── Grid layout ─────────────────────────────────────────────────────── */
	.rw-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
		gap: var(--ii-space-stack-sm, 12px);
		padding: var(--ii-space-stack-md, 16px) var(--ii-space-inline-lg, 24px);
		align-content: start;
	}

	/* ── Status bar ──────────────────────────────────────────────────────── */
	.rw-status-bar {
		display: flex;
		align-items: center;
		gap: var(--ii-space-inline-sm, 8px);
	}

	.rw-conn-dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		flex-shrink: 0;
		animation: pulse-conn 2s ease infinite;
	}

	@keyframes pulse-conn {
		0%, 100% { opacity: 1; }
		50% { opacity: 0.5; }
	}

	.rw-conn-label {
		font-size: var(--ii-text-small, 0.8125rem);
		font-weight: 600;
	}

	.rw-computed-at {
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-muted);
	}

	.rw-refresh {
		padding: 3px 10px;
		border: 1px solid var(--ii-border);
		border-radius: var(--ii-radius-sm, 6px);
		background: transparent;
		color: var(--ii-text-secondary);
		font-size: var(--ii-text-label, 0.75rem);
		font-family: var(--ii-font-sans);
		cursor: pointer;
		transition: background-color 120ms ease;
	}

	.rw-refresh:hover {
		background: var(--ii-surface-alt);
	}

	/* ── Panel base ──────────────────────────────────────────────────────── */
	.rw-panel {
		border: 1px solid var(--ii-border-subtle);
		border-radius: var(--ii-radius-md, 12px);
		background: var(--ii-surface-elevated);
		overflow: hidden;
		transition: border-color 300ms ease, box-shadow 300ms ease;
	}

	.rw-panel-title {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: var(--ii-space-stack-xs, 10px) var(--ii-space-inline-md, 16px);
		font-size: var(--ii-text-small, 0.8125rem);
		font-weight: 600;
		color: var(--ii-text-primary);
		border-bottom: 1px solid var(--ii-border-subtle);
		background: var(--ii-surface-alt);
	}

	.rw-empty {
		padding: var(--ii-space-stack-md, 20px);
		text-align: center;
		color: var(--ii-text-muted);
		font-size: var(--ii-text-small, 0.8125rem);
	}

	/* ── Summary banner ─────────────────────────────────────────────────── */
	.rw-panel--summary {
		grid-column: 1 / -1;
	}

	.summary-grid {
		display: grid;
		grid-template-columns: repeat(5, 1fr);
		gap: 1px;
		background: var(--ii-border-subtle);
	}

	.summary-card {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 2px;
		padding: var(--ii-space-stack-sm, 12px) var(--ii-space-inline-sm, 12px);
		background: var(--ii-surface-elevated);
	}

	.summary-label {
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-muted);
		text-transform: uppercase;
		letter-spacing: 0.04em;
		font-weight: 600;
	}

	.summary-value {
		font-size: var(--ii-text-h3, 1.375rem);
		font-weight: 800;
		font-variant-numeric: tabular-nums;
	}

	/* ── Flash animation on trigger state change ─────────────────────────── */
	.rw-panel--flash-danger {
		border-color: var(--ii-danger);
		box-shadow: 0 0 0 1px var(--ii-danger),
			0 0 12px color-mix(in srgb, var(--ii-danger) 20%, transparent);
		animation: flash-border 1.5s ease 1;
	}

	.rw-panel--flash-warning {
		border-color: var(--ii-warning);
		box-shadow: 0 0 0 1px var(--ii-warning),
			0 0 8px color-mix(in srgb, var(--ii-warning) 15%, transparent);
		animation: flash-border 1.5s ease 1;
	}

	@keyframes flash-border {
		0% { opacity: 1; }
		25% { opacity: 0.7; }
		50% { opacity: 1; }
		75% { opacity: 0.8; }
		100% { opacity: 1; }
	}

	/* ── Regime panel ────────────────────────────────────────────────────── */
	.rw-panel--regime {
		grid-column: span 1;
	}

	.regime-hero {
		display: flex;
		align-items: baseline;
		gap: var(--ii-space-inline-sm, 8px);
		padding: var(--ii-space-stack-sm, 14px) var(--ii-space-inline-md, 16px);
	}

	.regime-name {
		font-size: var(--ii-text-h2, 1.75rem);
		font-weight: 800;
		letter-spacing: 0.04em;
	}

	.regime-confidence {
		font-size: var(--ii-text-body, 0.9375rem);
		font-weight: 500;
		opacity: 0.7;
	}

	.regime-ts {
		display: block;
		padding: 0 var(--ii-space-inline-md, 16px);
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-muted);
	}

	.regime-timeline {
		display: flex;
		gap: 3px;
		padding: var(--ii-space-stack-sm, 12px) var(--ii-space-inline-md, 16px);
		align-items: center;
	}

	.regime-dot {
		width: 12px;
		height: 12px;
		border-radius: 3px;
		flex-shrink: 0;
		transition: background-color 300ms ease;
	}

	/* ── Alerts panel ────────────────────────────────────────────────────── */
	.rw-alert-count {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		min-width: 20px;
		height: 20px;
		padding: 0 6px;
		border-radius: 10px;
		background: var(--ii-danger);
		color: #fff;
		font-size: 11px;
		font-weight: 700;
	}

	.alert-list {
		display: flex;
		flex-direction: column;
		max-height: 200px;
		overflow-y: auto;
	}

	.alert-row {
		display: flex;
		align-items: center;
		gap: var(--ii-space-inline-xs, 6px);
		padding: var(--ii-space-stack-2xs, 5px) var(--ii-space-inline-md, 16px);
		border-bottom: 1px solid var(--ii-border-subtle);
		font-size: var(--ii-text-small, 0.8125rem);
	}

	.alert-name {
		flex: 1;
		color: var(--ii-text-primary);
		font-weight: 500;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.alert-tag {
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 600;
		padding: 1px 6px;
		border-radius: var(--ii-radius-pill, 999px);
	}

	.alert-tag--dtw {
		background: color-mix(in srgb, var(--ii-warning) 12%, transparent);
		color: var(--ii-warning);
	}

	.alert-tag--behavior {
		background: color-mix(in srgb, var(--ii-danger) 12%, transparent);
		color: var(--ii-danger);
	}

	.alert-meta {
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-muted);
		font-variant-numeric: tabular-nums;
	}

	/* ── CVaR profile panel ──────────────────────────────────────────────── */
	.cvar-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: var(--ii-space-stack-xs, 10px) var(--ii-space-inline-md, 16px);
		border-bottom: 1px solid var(--ii-border-subtle);
		background: var(--ii-surface-alt);
	}

	.cvar-profile {
		font-size: var(--ii-text-body, 0.9375rem);
		font-weight: 700;
		color: var(--ii-text-primary);
		text-transform: capitalize;
	}

	.cvar-hero {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		padding: var(--ii-space-stack-sm, 14px) var(--ii-space-inline-md, 16px) var(--ii-space-stack-2xs, 4px);
	}

	.cvar-value {
		font-size: var(--ii-text-h2, 1.75rem);
		font-weight: 800;
		font-variant-numeric: tabular-nums;
		transition: color 300ms ease;
	}

	.cvar-limit-label {
		font-size: var(--ii-text-small, 0.8125rem);
		color: var(--ii-text-muted);
		font-variant-numeric: tabular-nums;
	}

	/* Utilization bar */
	.cvar-util-track {
		position: relative;
		height: 8px;
		margin: var(--ii-space-stack-2xs, 4px) var(--ii-space-inline-md, 16px);
		background: var(--ii-surface-alt);
		border-radius: 4px;
		overflow: visible;
	}

	.cvar-util-fill {
		height: 100%;
		border-radius: 4px;
		transition: width 500ms ease, background-color 300ms ease;
	}

	.cvar-util-label {
		position: absolute;
		right: 0;
		top: -16px;
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 600;
		color: var(--ii-text-secondary);
		font-variant-numeric: tabular-nums;
	}

	/* CVaR meta */
	.cvar-meta {
		display: flex;
		gap: 0;
		border-top: 1px solid var(--ii-border-subtle);
		margin-top: var(--ii-space-stack-sm, 12px);
	}

	.cvar-kv {
		flex: 1;
		display: flex;
		flex-direction: column;
		gap: 1px;
		padding: var(--ii-space-stack-2xs, 6px) var(--ii-space-inline-md, 16px);
		border-right: 1px solid var(--ii-border-subtle);
	}

	.cvar-kv:last-child {
		border-right: none;
	}

	.cvar-k {
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-muted);
	}

	.cvar-v {
		font-size: var(--ii-text-body, 0.9375rem);
		font-weight: 600;
		font-variant-numeric: tabular-nums;
		transition: color 300ms ease;
	}

	/* Sparkline */
	.spark-container {
		display: flex;
		align-items: flex-end;
		gap: 2px;
		height: 40px;
		padding: var(--ii-space-stack-xs, 8px) var(--ii-space-inline-md, 16px);
		border-top: 1px solid var(--ii-border-subtle);
	}

	.spark-bar {
		flex: 1;
		min-width: 4px;
		background: var(--ii-brand-primary);
		border-radius: 2px 2px 0 0;
		opacity: 0.6;
		transition: height 300ms ease;
	}

	.spark-bar:last-child {
		opacity: 1;
	}

	/* ── Macro panel ─────────────────────────────────────────────────────── */
	.rw-panel--macro {
		grid-column: 1 / -1;
	}

	.macro-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
		gap: 1px;
		background: var(--ii-border-subtle);
	}

	.macro-kv {
		display: flex;
		flex-direction: column;
		gap: 2px;
		padding: var(--ii-space-stack-xs, 8px) var(--ii-space-inline-sm, 12px);
		background: var(--ii-surface-elevated);
	}

	.macro-k {
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-muted);
	}

	.macro-v {
		font-size: var(--ii-text-body, 0.9375rem);
		font-weight: 600;
		color: var(--ii-text-primary);
		font-variant-numeric: tabular-nums;
	}

	/* ── Loading skeleton ────────────────────────────────────────────────── */
	.rw-loading {
		display: flex;
		justify-content: center;
		padding: var(--ii-space-stack-lg, 32px);
	}

	.rw-loading-text {
		font-size: var(--ii-text-body, 0.9375rem);
		color: var(--ii-text-muted);
		animation: pulse-loading 1.5s ease infinite;
	}

	@keyframes pulse-loading {
		0%, 100% { opacity: 0.5; }
		50% { opacity: 1; }
	}

	/* ── Responsive ──────────────────────────────────────────────────────── */
	@media (max-width: 768px) {
		.rw-grid {
			grid-template-columns: 1fr;
		}

		.rw-panel--macro {
			grid-column: 1;
		}
	}
</style>
