<!--
  Dashboard — Wealth OS entry point.
  SSR provides initial snapshot; riskStore (SSE) streams live CVaR/regime updates.
  Owns riskStore lifecycle — start() on mount, destroy() on unmount.
-->
<script lang="ts">
	import { getContext, onMount } from "svelte";
	import { PageHeader, StatusBadge, formatPercent, formatNumber } from "@netz/ui";
	import type { RiskStore, CVaRStatus } from "$lib/stores/risk-store.svelte";

	let { data } = $props();

	const riskStore = getContext<RiskStore>("netz:riskStore");

	onMount(() => {
		try { riskStore.start(); } catch (e) { console.warn("Risk store failed to start:", e); }
		return () => riskStore.destroy();
	});

	// ── Regime — live from store, SSR fallback ──────────────────────────
	let regime = $derived(
		riskStore.regime?.regime
		?? (data.regime as { regime?: string } | null)?.regime
		?? null
	);

	function regimeBadgeStatus(r: string | null): "neutral" | "warning" | "danger" | "success" {
		switch (r) {
			case "RISK_OFF":    return "warning";
			case "CRISIS":      return "danger";
			case "RISK_ON":     return "success";
			case "INFLATION":   return "warning";
			default:            return "neutral";
		}
	}

	// ── Profile display config ───────────────────────────────────────────
	const PROFILES = ["conservative", "moderate", "growth"] as const;
	type Profile = typeof PROFILES[number];

	const profileLabel: Record<Profile, string> = {
		conservative: "Conservador",
		moderate:     "Moderado",
		growth:       "Growth",
	};
	const profileSubLabel: Record<Profile, string> = {
		conservative: "Conservative",
		moderate:     "Moderate",
		growth:       "Aggressive",
	};

	// ── CVaR per profile — live from store, SSR fallback ────────────────
	function getCvar(profile: Profile): CVaRStatus | null {
		const live = riskStore.cvarByProfile[profile];
		if (live?.cvar_current != null) return live;
		// SSR fallback from riskSummary
		const summaryProfiles = (data.riskSummary as { profiles?: CVaRStatus[] } | null)?.profiles;
		return summaryProfiles?.find(p => p.profile === profile) ?? null;
	}

	function utilizationColor(pct: number | null): string {
		if (pct == null) return "var(--netz-text-muted)";
		if (pct >= 100)  return "var(--netz-danger)";
		if (pct >= 80)   return "var(--netz-warning)";
		return "var(--netz-success)";
	}

	function utilizationBarColor(pct: number | null): string {
		if (pct == null) return "var(--netz-border)";
		if (pct >= 100)  return "var(--netz-danger)";
		if (pct >= 80)   return "var(--netz-warning)";
		return "var(--netz-success)";
	}

	// ── NAV from snapshot SSR data ───────────────────────────────────────
	function getSnapshot(profile: Profile) {
		return (data.snapshotsByProfile as Record<string, unknown>)?.[profile] as {
			nav?: number;
			ytd_return?: number;
			snapshot_date?: string;
		} | null;
	}

	// ── Alerts ───────────────────────────────────────────────────────────
	let dtwAlerts   = $derived(riskStore.driftAlerts.dtw_alerts.length > 0
		? riskStore.driftAlerts.dtw_alerts
		: ((data.alerts as { dtw_alerts?: unknown[] } | null)?.dtw_alerts ?? []));
	let behaviorAlerts = $derived(riskStore.driftAlerts.behavior_change_alerts.length > 0
		? riskStore.driftAlerts.behavior_change_alerts
		: ((data.alerts as { behavior_change_alerts?: unknown[] } | null)?.behavior_change_alerts ?? []));

	// ── Timestamp ────────────────────────────────────────────────────────
	let updatedAt = $derived(
		riskStore.computedAt
			? new Date(riskStore.computedAt).toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" })
			: null
	);
	let today = new Date().toLocaleDateString("pt-BR", { day: "2-digit", month: "short", year: "numeric" });
</script>

<div class="dashboard">
	<!-- Header -->
	<div class="dashboard-header">
		<div class="dashboard-title">
			<PageHeader
				title="Wealth OS — Dashboard"
				subtitle="{today}{updatedAt ? ` · Atualizado às ${updatedAt}` : ''}"
			/>
		</div>
		<div class="dashboard-header-meta">
			{#if regime}
				<StatusBadge status={regimeBadgeStatus(regime)} label="{regime.replace('_', '_')} ativo" />
			{/if}
			<span class="org-label">Netz Partners</span>
		</div>
	</div>

	<!-- Portfolio Cards -->
	<div class="portfolio-cards">
		{#each PROFILES as profile (profile)}
			{@const cvar = getCvar(profile)}
			{@const snap = getSnapshot(profile)}
			{@const utilPct = cvar?.cvar_utilized_pct ?? null}
			<div class="portfolio-card" data-status={cvar?.trigger_status ?? "ok"}>
				<div class="card-header">
					<span class="card-title">{profileLabel[profile]}</span>
					<span class="card-sublabel">{profileSubLabel[profile]}</span>
				</div>
				<div class="card-nav">
					{snap?.nav != null ? `USD ${formatNumber(snap.nav, 0)}` : "—"}
				</div>
				<div class="card-ytd">
					NAV · {snap?.ytd_return != null ? formatPercent(snap.ytd_return) : "—"} YTD
				</div>
				<div class="card-metrics">
					<div class="metric">
						<span class="metric-label">CVaR 95%</span>
						<span class="metric-value" style:color={utilizationColor(utilPct)}>
							{cvar?.cvar_current != null ? formatPercent(cvar.cvar_current) : "—"}
						</span>
						{#if cvar?.cvar_limit != null}
							<span class="metric-limit">lim {formatPercent(cvar.cvar_limit)}</span>
						{/if}
					</div>
					<div class="metric">
						<span class="metric-label">Utilização</span>
						<span class="metric-value" style:color={utilizationColor(utilPct)}>
							{utilPct != null ? formatPercent(utilPct / 100) : "—"}
						</span>
					</div>
				</div>
				<!-- Utilization bar -->
				<div class="util-bar-track">
					<div
						class="util-bar-fill"
						style:width="{Math.min(utilPct ?? 0, 100)}%"
						style:background={utilizationBarColor(utilPct)}
					></div>
				</div>
			</div>
		{/each}
	</div>

	<!-- Alerts Panel -->
	<div class="bottom-row">
		<div class="alerts-panel">
			<h2 class="panel-title">Alertas ativos</h2>
			{#if dtwAlerts.length === 0 && behaviorAlerts.length === 0}
				<p class="alerts-empty">Nenhum alerta ativo.</p>
			{/if}
			{#each dtwAlerts as alert}
				<div class="alert-card alert-card--dtw">
					<span class="alert-dot alert-dot--red"></span>
					<div class="alert-body">
						<span class="alert-name">{(alert as { instrument_name: string }).instrument_name}</span>
						<span class="alert-meta">DTW score: {formatNumber((alert as { dtw_score: number }).dtw_score, 2)}</span>
					</div>
				</div>
			{/each}
			{#each behaviorAlerts as alert}
				{@const a = alert as { instrument_name: string; severity: string }}
				<div class="alert-card" class:alert-card--warn={a.severity === "warning"}>
					<span class="alert-dot" class:alert-dot--yellow={a.severity === "warning"} class:alert-dot--red={a.severity !== "warning"}></span>
					<div class="alert-body">
						<span class="alert-name">{a.instrument_name}</span>
						<span class="alert-meta">Anomalia comportamental · {a.severity}</span>
					</div>
				</div>
			{/each}
		</div>
	</div>
</div>

<style>
.dashboard { display: flex; flex-direction: column; gap: 24px; padding: 32px 0; }

/* Header */
.dashboard-header { display: flex; align-items: flex-start; justify-content: space-between; }
.dashboard-header-meta { display: flex; align-items: center; gap: 12px; padding-top: 6px; }
.org-label { font-size: 13px; font-weight: 500; color: var(--netz-text-muted); }

/* Portfolio cards grid */
.portfolio-cards { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }

.portfolio-card {
	background: var(--netz-surface-elevated);
	border: 1px solid var(--netz-border-subtle);
	border-radius: var(--netz-radius-lg, 12px);
	padding: 20px 20px 16px;
	display: flex; flex-direction: column; gap: 6px;
}
.portfolio-card[data-status="breach"] { border-color: var(--netz-danger); }
.portfolio-card[data-status="warning"] { border-color: var(--netz-warning); }

.card-header { display: flex; align-items: baseline; justify-content: space-between; }
.card-title { font-size: 15px; font-weight: 700; color: var(--netz-text-primary); }
.card-sublabel { font-size: 11px; color: var(--netz-text-muted); background: var(--netz-surface-alt); padding: 2px 8px; border-radius: 99px; }
.card-nav { font-size: 28px; font-weight: 700; color: var(--netz-text-primary); font-variant-numeric: tabular-nums; margin-top: 4px; }
.card-ytd { font-size: 12px; color: var(--netz-text-secondary); }

.card-metrics { display: flex; gap: 24px; margin-top: 8px; }
.metric { display: flex; flex-direction: column; gap: 2px; }
.metric-label { font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: 0.5px; color: var(--netz-text-muted); }
.metric-value { font-size: 16px; font-weight: 700; font-variant-numeric: tabular-nums; }
.metric-limit { font-size: 11px; color: var(--netz-text-muted); }

.util-bar-track { height: 4px; background: var(--netz-border); border-radius: 99px; margin-top: 12px; overflow: hidden; }
.util-bar-fill { height: 100%; border-radius: 99px; transition: width 600ms ease, background 300ms ease; }

/* Alerts */
.bottom-row { display: grid; grid-template-columns: 1fr; gap: 16px; }
.alerts-panel { background: var(--netz-surface-elevated); border: 1px solid var(--netz-border-subtle); border-radius: var(--netz-radius-lg, 12px); padding: 20px; display: flex; flex-direction: column; gap: 12px; }
.panel-title { font-size: 13px; font-weight: 700; color: var(--netz-text-primary); margin: 0; }
.alerts-empty { font-size: 13px; color: var(--netz-text-muted); }

.alert-card { display: flex; align-items: flex-start; gap: 10px; background: var(--netz-surface-alt); border-radius: var(--netz-radius-md, 8px); padding: 12px 14px; }
.alert-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; margin-top: 3px; background: var(--netz-border); }
.alert-dot--red { background: var(--netz-danger); }
.alert-dot--yellow { background: var(--netz-warning); }
.alert-body { display: flex; flex-direction: column; gap: 2px; }
.alert-name { font-size: 13px; font-weight: 600; color: var(--netz-text-primary); }
.alert-meta { font-size: 11px; color: var(--netz-text-muted); }

@media (max-width: 900px) {
	.portfolio-cards { grid-template-columns: 1fr; }
}
</style>
