<script lang="ts">
	import { cn } from "../../utils/cn.js";
	import type { Snippet } from "svelte";
	import UtilizationBar from "./UtilizationBar.svelte";
	import * as Card from "$lib/components/ui/card";

	type Direction = "up" | "down" | "flat";
	type CardStatus = "ok" | "warn" | "breach";

	interface Props {
		label: string;
		value: string;
		sublabel?: string;
		delta?: { value: string; direction: Direction; period?: string };
		status?: CardStatus;
		accentColor?: string;
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
		accentColor,
		utilization,
		class: className,
		sparkline,
	}: Props = $props();

	const borderColor: Record<CardStatus, string> = {
		ok: "var(--ii-success)",
		warn: "var(--ii-warning)",
		breach: "var(--ii-danger)",
	};

	const deltaColor: Record<Direction, string> = {
		up: "var(--ii-success)",
		down: "var(--ii-danger)",
		flat: "var(--ii-text-muted)",
	};
</script>

<Card.Root
	class={cn(
		"relative overflow-hidden rounded-(--ii-radius-lg) border border-(--ii-border-subtle) bg-(--ii-surface-highlight) p-0 gap-0 ring-0",
		"shadow-(--ii-shadow-card)",
		className,
	)}
	style="border-left: 3px solid {accentColor ?? (status ? borderColor[status] : 'transparent')};"
>
	<Card.Content class="p-(--ii-space-card-padding)">
		<div class="flex items-start justify-between gap-3">
			<div class="min-w-0 flex-1">
				<!-- Label -->
				<p class="ii-ui-kicker">
					{label}
				</p>

				<!-- Value -->
				<p
					class="mt-2 font-mono text-[1.75rem] font-semibold leading-none tracking-[-0.03em] text-(--ii-text-primary)"
				>
					{value}
				</p>

				<!-- Sublabel -->
				{#if sublabel}
					<p class="mt-1 text-sm text-(--ii-text-secondary)">{sublabel}</p>
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
							<span class="text-(--ii-text-muted)">{delta.period}</span>
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
				<div class="shrink-0 self-start rounded-(--ii-radius-md) border border-(--ii-border-subtle) bg-(--ii-surface-elevated) p-2 shadow-(--ii-shadow-1)">
					{@render sparkline()}
				</div>
			{/if}
		</div>
	</Card.Content>
</Card.Root>
