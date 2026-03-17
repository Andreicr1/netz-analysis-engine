<script lang="ts">
	import { cn } from "../utils/cn.js";

	export type WealthAlert = {
		id: string;
		timestamp: string;
		type:
			| "cvar_breach"
			| "behavior_change"
			| "regime_change"
			| "dtw_drift"
			| "universe_removal";
		title: string;
		description: string;
		severity: "critical" | "warning" | "info";
		meta?: Record<string, unknown>;
	};

	interface Props {
		alerts: WealthAlert[];
		maxItems?: number;
		class?: string;
	}

	let { alerts, maxItems = 50, class: className }: Props = $props();

	const visible = $derived(alerts.slice(0, maxItems));

	const severityBorder: Record<WealthAlert["severity"], string> = {
		critical: "var(--netz-danger)",
		warning: "var(--netz-warning)",
		info: "var(--netz-info)",
	};

	const severityIcon: Record<WealthAlert["severity"], string> = {
		critical: "●",
		warning: "▲",
		info: "ℹ",
	};

	const typeLabel: Record<WealthAlert["type"], string> = {
		cvar_breach: "CVaR",
		behavior_change: "Comportamento",
		regime_change: "Regime",
		dtw_drift: "DTW Drift",
		universe_removal: "Universo",
	};

	function relativeTime(iso: string): string {
		try {
			const diff = Date.now() - new Date(iso).getTime();
			const mins = Math.floor(diff / 60_000);
			if (mins < 1) return "agora";
			if (mins < 60) return `${mins}m atrás`;
			const hrs = Math.floor(mins / 60);
			if (hrs < 24) return `${hrs}h atrás`;
			const days = Math.floor(hrs / 24);
			return `${days}d atrás`;
		} catch {
			return iso;
		}
	}
</script>

<div class={cn("flex flex-col divide-y divide-[var(--netz-border)]", className)} role="feed">
	{#if visible.length === 0}
		<p class="py-8 text-center text-sm text-[var(--netz-text-muted)]">Nenhum alerta.</p>
	{:else}
		{#each visible as alert (alert.id)}
			<article
				class="flex gap-3 py-3 pl-4 pr-2"
				style="border-left: 3px solid {severityBorder[alert.severity]};"
			>
				<!-- Severity indicator -->
				<span
					class="mt-0.5 shrink-0 text-xs leading-none"
					style="color: {severityBorder[alert.severity]};"
					aria-hidden="true"
				>
					{severityIcon[alert.severity]}
				</span>

				<div class="min-w-0 flex-1">
					<!-- Header row -->
					<div class="flex flex-wrap items-center gap-x-2 gap-y-0.5">
						<span
							class="inline-flex items-center rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide"
							style="background-color: {severityBorder[alert.severity]}1a; color: {severityBorder[alert.severity]};"
						>
							{typeLabel[alert.type]}
						</span>
						<p class="text-sm font-semibold text-[var(--netz-text-primary)]">
							{alert.title}
						</p>
					</div>

					<!-- Description -->
					<p class="mt-0.5 text-xs leading-relaxed text-[var(--netz-text-secondary)]">
						{alert.description}
					</p>
				</div>

				<!-- Timestamp -->
				<time
					class="shrink-0 text-xs text-[var(--netz-text-muted)]"
					datetime={alert.timestamp}
					title={alert.timestamp}
				>
					{relativeTime(alert.timestamp)}
				</time>
			</article>
		{/each}
	{/if}
</div>
