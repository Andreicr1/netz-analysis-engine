<script lang="ts">
	import { cn } from "../utils/cn.js";
	import type { Snippet } from "svelte";

	type Trend = "up" | "down" | "flat";

	interface Props {
		value: string;
		label: string;
		trend?: Trend;
		trendValue?: string;
		class?: string;
		sparkline?: Snippet;
	}

	let {
		value,
		label,
		trend,
		trendValue,
		class: className,
		sparkline,
	}: Props = $props();

	const trendColors: Record<Trend, string> = {
		up: "text-[#10B981]",
		down: "text-[#EF4444]",
		flat: "text-[var(--netz-text-muted)]",
	};
</script>

<div
	class={cn(
		"rounded-lg border border-[var(--netz-border)] bg-[var(--netz-surface)] p-4 shadow-sm",
		className,
	)}
>
	<div class="flex items-start justify-between">
		<div>
			<p class="text-sm text-[var(--netz-text-muted)]">{label}</p>
			<p class="mt-1 text-2xl font-semibold text-[var(--netz-text-primary)]">
				{value}
			</p>
			{#if trend}
				<div class={cn("mt-1 flex items-center gap-1 text-xs font-medium", trendColors[trend])}>
					{#if trend === "up"}
						<svg
							xmlns="http://www.w3.org/2000/svg"
							width="14"
							height="14"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="2"
							><path d="m5 12 7-7 7 7" /><path d="M12 19V5" /></svg
						>
					{:else if trend === "down"}
						<svg
							xmlns="http://www.w3.org/2000/svg"
							width="14"
							height="14"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="2"
							><path d="M12 5v14" /><path d="m19 12-7 7-7-7" /></svg
						>
					{:else}
						<svg
							xmlns="http://www.w3.org/2000/svg"
							width="14"
							height="14"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="2"><path d="M5 12h14" /></svg
						>
					{/if}
					{#if trendValue}
						<span>{trendValue}</span>
					{/if}
				</div>
			{/if}
		</div>
		{#if sparkline}
			<div class="ml-4">
				{@render sparkline()}
			</div>
		{/if}
	</div>
</div>
