<script lang="ts">
	import { cn } from "../utils/cn.js";

	interface Props {
		current: number;
		limit: number;
		showValues?: boolean;
		formatValue?: (v: number) => string;
		class?: string;
	}

	let {
		current,
		limit,
		showValues = true,
		formatValue,
		class: className,
	}: Props = $props();

	const defaultFormat = (v: number) => `${v >= 0 ? "" : ""}${v.toFixed(1)}%`;
	const fmt = $derived(formatValue ?? defaultFormat);

	/** ratio: how full the bar is (capped at 1.2 for visual overflow) */
	const ratio = $derived(limit > 0 ? current / limit : 0);
	const fillPct = $derived(Math.min(Math.abs(ratio) * 100, 120));

	type BarStatus = "ok" | "warn" | "breach";
	const status = $derived<BarStatus>(
		Math.abs(ratio) >= 1.0 ? "breach" : Math.abs(ratio) >= 0.8 ? "warn" : "ok",
	);

	const fillColor: Record<BarStatus, string> = {
		ok: "var(--netz-success)",
		warn: "var(--netz-warning)",
		breach: "var(--netz-danger)",
	};
</script>

<div class={cn("w-full", className)}>
	{#if showValues}
		<div class="mb-1 flex justify-end gap-1 text-xs text-(--netz-text-muted)">
			<span style="color: {fillColor[status]};">{fmt(current)}</span>
			<span>/</span>
			<span>{fmt(limit)}</span>
		</div>
	{/if}

	<!-- Track -->
	<div
		class="relative h-2 w-full overflow-hidden rounded-full"
		style="background-color: var(--netz-surface-inset);"
		role="progressbar"
		aria-valuenow={current}
		aria-valuemin={0}
		aria-valuemax={limit}
	>
		<!-- 100% marker line (visible only when ratio > 1) -->
		{#if ratio > 1}
			<div
				class="absolute top-0 h-full w-px"
				style="left: {(1 / Math.min(ratio, 1.2)) * 100}%; background-color: var(--netz-text-muted); opacity: 0.5;"
			></div>
		{/if}

		<!-- Fill bar -->
		<div
			class="h-full rounded-full transition-all duration-300"
			style="width: {fillPct}%; background-color: {fillColor[status]};"
		></div>
	</div>
</div>
