<script lang="ts">
	import { cn } from "../utils/cn.js";
	import type { Snippet } from "svelte";
	import UtilizationBar from "./UtilizationBar.svelte";

	type Direction = "up" | "down" | "flat";
	type CardStatus = "ok" | "warn" | "breach";

	interface Props {
		label: string;
		value: string;
		sublabel?: string;
		delta?: { value: string; direction: Direction; period?: string };
		status?: CardStatus;
		utilization?: { current: number; limit: number };
		class?: string;
		sparkline?: Snippet;
	}

	let {
		label,
		value,
		sublabel,
		delta,
		status,
		utilization,
		class: className,
		sparkline,
	}: Props = $props();

	const borderColor: Record<CardStatus, string> = {
		ok: "var(--netz-success)",
		warn: "var(--netz-warning)",
		breach: "var(--netz-danger)",
	};

	const deltaColor: Record<Direction, string> = {
		up: "var(--netz-success)",
		down: "var(--netz-danger)",
		flat: "var(--netz-text-muted)",
	};
</script>

<div
	class={cn(
		"relative overflow-hidden rounded-[var(--netz-radius-lg)] border border-[var(--netz-border-subtle)] bg-[var(--netz-surface-highlight)] p-[var(--netz-space-card-padding)]",
		"shadow-[var(--netz-shadow-card)]",
		className,
	)}
	style={status
		? `border-left: 3px solid ${borderColor[status]};`
		: "border-left: 3px solid transparent;"}
>
	<div class="flex items-start justify-between gap-3">
		<div class="min-w-0 flex-1">
			<!-- Label -->
			<p class="netz-ui-kicker">
				{label}
			</p>

			<!-- Value -->
			<p
				class="mt-2 font-mono text-[1.75rem] font-semibold leading-none tracking-[-0.03em] text-[var(--netz-text-primary)]"
			>
				{value}
			</p>

			<!-- Sublabel -->
			{#if sublabel}
				<p class="mt-1 text-sm text-[var(--netz-text-secondary)]">{sublabel}</p>
			{/if}

			<!-- Delta -->
			{#if delta}
				<div class="mt-3 flex items-center gap-1.5 text-xs font-semibold">
					{#if delta.direction === "up"}
						<svg
							xmlns="http://www.w3.org/2000/svg"
							width="12"
							height="12"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="2.5"
							style="color: {deltaColor[delta.direction]};"
						>
							<path d="m5 12 7-7 7 7" /><path d="M12 19V5" />
						</svg>
					{:else if delta.direction === "down"}
						<svg
							xmlns="http://www.w3.org/2000/svg"
							width="12"
							height="12"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="2.5"
							style="color: {deltaColor[delta.direction]};"
						>
							<path d="M12 5v14" /><path d="m19 12-7 7-7-7" />
						</svg>
					{:else}
						<svg
							xmlns="http://www.w3.org/2000/svg"
							width="12"
							height="12"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="2.5"
							style="color: {deltaColor[delta.direction]};"
						>
							<path d="M5 12h14" />
						</svg>
					{/if}
					<span style="color: {deltaColor[delta.direction]};">{delta.value}</span>
					{#if delta.period}
						<span class="text-[var(--netz-text-muted)]">{delta.period}</span>
					{/if}
				</div>
			{/if}

			<!-- Utilization bar -->
			{#if utilization}
				<div class="mt-4">
					<UtilizationBar current={utilization.current} limit={utilization.limit} />
				</div>
			{/if}
		</div>

		<!-- Sparkline slot -->
		{#if sparkline}
			<div class="shrink-0 self-start rounded-[var(--netz-radius-md)] border border-[var(--netz-border-subtle)] bg-[var(--netz-surface-elevated)] p-2 shadow-[var(--netz-shadow-1)]">
				{@render sparkline()}
			</div>
		{/if}
	</div>
</div>
