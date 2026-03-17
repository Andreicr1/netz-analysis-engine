<!--
  @component AlertFeed
  Chronological feed with discriminated union WealthAlert types.
  Each alert type renders contextually: CVaR shows utilization, behavior change lists metrics, etc.
-->
<script lang="ts">
	import { cn } from "../utils/cn.js";
	import UtilizationBar from "./UtilizationBar.svelte";

	// ── Discriminated Union ──────────────────────────────────
	export type WealthAlert =
		| { type: "cvar_breach"; portfolio: string; utilization: number; ts: Date }
		| { type: "behavior_change"; instrument: string; severity: "LOW" | "MEDIUM" | "HIGH" | "CRITICAL"; changed_metrics: string[]; ts: Date }
		| { type: "dtw_drift"; instrument: string; drift_score: number; ts: Date }
		| { type: "regime_change"; from: string; to: string; ts: Date }
		| { type: "universe_removal"; instrument: string; affected_portfolios: string[]; ts: Date };

	interface Props {
		alerts: WealthAlert[];
		maxItems?: number;
		class?: string;
	}

	let { alerts, maxItems = 50, class: className }: Props = $props();

	const visible = $derived(alerts.slice(0, maxItems));

	// Severity derived from alert type
	function alertSeverity(alert: WealthAlert): "critical" | "warning" | "info" {
		switch (alert.type) {
			case "cvar_breach": return "critical";
			case "behavior_change": return alert.severity === "CRITICAL" || alert.severity === "HIGH" ? "critical" : "warning";
			case "dtw_drift": return "warning";
			case "regime_change": return "warning";
			case "universe_removal": return "info";
		}
	}

	const severityBorder: Record<string, string> = {
		critical: "var(--netz-danger)",
		warning: "var(--netz-warning)",
		info: "var(--netz-info)",
	};

	const typeLabel: Record<WealthAlert["type"], string> = {
		cvar_breach: "CVaR",
		behavior_change: "Comportamento",
		regime_change: "Regime",
		dtw_drift: "DTW Drift",
		universe_removal: "Universo",
	};

	function alertTitle(alert: WealthAlert): string {
		switch (alert.type) {
			case "cvar_breach": return `CVaR breach — ${alert.portfolio}`;
			case "behavior_change": return `Behavior change — ${alert.instrument}`;
			case "dtw_drift": return `DTW drift — ${alert.instrument}`;
			case "regime_change": return `Regime: ${alert.from} → ${alert.to}`;
			case "universe_removal": return `Removido — ${alert.instrument}`;
		}
	}

	function alertKey(alert: WealthAlert, i: number): string {
		return `${alert.type}-${alert.ts.getTime()}-${i}`;
	}

	function relativeTime(ts: Date): string {
		const diff = Date.now() - ts.getTime();
		const mins = Math.floor(diff / 60_000);
		if (mins < 1) return "agora";
		if (mins < 60) return `${mins}m atrás`;
		const hrs = Math.floor(mins / 60);
		if (hrs < 24) return `${hrs}h atrás`;
		const days = Math.floor(hrs / 24);
		return `${days}d atrás`;
	}
</script>

<div class={cn("flex flex-col divide-y divide-[var(--netz-border)]", className)} role="feed">
	{#if visible.length === 0}
		<p class="py-8 text-center text-sm text-[var(--netz-text-muted)]">Nenhum alerta.</p>
	{:else}
		{#each visible as alert, i (alertKey(alert, i))}
			{@const sev = alertSeverity(alert)}
			<article
				class="flex gap-3 py-3 pl-4 pr-2"
				style="border-left: 3px solid {severityBorder[sev]};"
			>
				<div class="min-w-0 flex-1">
					<!-- Header -->
					<div class="flex flex-wrap items-center gap-x-2 gap-y-0.5">
						<span
							class="inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide"
							style="background-color: {severityBorder[sev]}1a; color: {severityBorder[sev]};"
						>
							{typeLabel[alert.type]}
						</span>
						<p class="text-sm font-semibold text-[var(--netz-text-primary)]">
							{alertTitle(alert)}
						</p>
					</div>

					<!-- Type-specific content -->
					{#if alert.type === "cvar_breach"}
						<div class="mt-1.5 max-w-xs">
							<UtilizationBar current={alert.utilization} limit={100} showValues={false} />
						</div>
					{:else if alert.type === "behavior_change"}
						<p class="mt-0.5 text-xs text-[var(--netz-text-secondary)]">
							Severidade: {alert.severity} · Métricas: {alert.changed_metrics.join(", ")}
						</p>
					{:else if alert.type === "dtw_drift"}
						<p class="mt-0.5 text-xs text-[var(--netz-text-secondary)]">
							Drift score: {alert.drift_score.toFixed(3)}
						</p>
					{:else if alert.type === "regime_change"}
						<p class="mt-0.5 text-xs text-[var(--netz-text-secondary)]">
							Transição de regime detectada
						</p>
					{:else if alert.type === "universe_removal"}
						<p class="mt-0.5 text-xs text-[var(--netz-text-secondary)]">
							Portfólios afetados: {alert.affected_portfolios.join(", ")}
						</p>
					{/if}
				</div>

				<time
					class="shrink-0 text-xs text-[var(--netz-text-muted)]"
					datetime={alert.ts.toISOString()}
				>
					{relativeTime(alert.ts)}
				</time>
			</article>
		{/each}
	{/if}
</div>
