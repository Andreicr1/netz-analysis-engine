<script lang="ts">
	import { onMount } from "svelte";
	import { echarts, initTheme } from "./echarts-setup.js";
	import { cn } from "../utils/cn.js";

	export interface BaseChartProps {
		class?: string;
		height?: number;
		palette?: string[];
		loading?: boolean;
		empty?: boolean;
		emptyMessage?: string;
		ariaLabel?: string;
		optionsOverride?: Record<string, unknown>;
	}

	interface ChartContainerProps extends BaseChartProps {
		option: Record<string, unknown>;
		/** Bindable echarts instance — exposed so callers can drive live
		 *  updates via setOption({ replaceMerge }) without triggering the
		 *  full notMerge replacement done by this component's $effect. */
		chart?: ReturnType<typeof echarts.init> | undefined;
	}

	let {
		class: className,
		height = 320,
		palette,
		loading = false,
		empty = false,
		emptyMessage = "No data available",
		ariaLabel = "Chart visualization",
		optionsOverride,
		option,
		chart = $bindable(),
	}: ChartContainerProps = $props();

	let containerEl: HTMLDivElement | undefined = $state();
	// Plain vars (not $state) — avoid proxy equality mismatch causing infinite $effect loop
	let lastAppliedOption: Record<string, unknown> | null = null;
	let lastAppliedOverride: Record<string, unknown> | undefined;

	onMount(() => {
		if (!containerEl) return;

		// Global theme registered once in echarts-setup.ts with MutationObserver
		initTheme();

		chart = echarts.init(containerEl, "ii-theme", { renderer: "canvas" });

		const ro = new ResizeObserver(() => {
			chart?.resize();
		});
		ro.observe(containerEl);

		return () => {
			ro.disconnect();
			chart?.dispose();
			chart = undefined;
		};
	});

	$effect(() => {
		if (!chart || loading || empty) return;
		if (option === lastAppliedOption && optionsOverride === lastAppliedOverride) return;
		const merged = optionsOverride ? { ...option, ...optionsOverride } : option;
		lastAppliedOption = option;
		lastAppliedOverride = optionsOverride;
		chart.setOption(merged, { notMerge: true });
	});
</script>

<div
	class={cn("relative w-full overflow-hidden rounded-lg", className)}
	style="height: {height}px"
>
	{#if loading}
		<div class="absolute inset-0 z-10 flex items-center justify-center bg-(--ii-surface)/80">
			<div class="h-8 w-8 animate-spin rounded-full border-4 border-(--ii-border) border-t-(--ii-brand-secondary)"></div>
		</div>
	{/if}

	{#if empty && !loading}
		<div class="absolute inset-0 z-10 flex items-center justify-center">
			<p class="text-sm text-(--ii-text-muted)">{emptyMessage}</p>
		</div>
	{/if}

	<div
		bind:this={containerEl}
		class="h-full w-full"
		role="img"
		aria-label={ariaLabel}
		style:visibility={empty ? "hidden" : "visible"}
	></div>
</div>
