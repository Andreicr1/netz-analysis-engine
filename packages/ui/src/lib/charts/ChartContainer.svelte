<script lang="ts">
	import { onMount } from "svelte";
	import { echarts } from "./echarts-setup.js";
	import { cn } from "../utils/cn.js";

	export interface BaseChartProps {
		class?: string;
		height?: number;
		palette?: string[];
		loading?: boolean;
		empty?: boolean;
		emptyMessage?: string;
		optionsOverride?: Record<string, unknown>;
	}

	interface ChartContainerProps extends BaseChartProps {
		option: Record<string, unknown>;
	}

	let {
		class: className,
		height = 320,
		palette,
		loading = false,
		empty = false,
		emptyMessage = "No data available",
		optionsOverride,
		option,
	}: ChartContainerProps = $props();

	let containerEl: HTMLDivElement | undefined = $state();
	let chart: ReturnType<typeof echarts.init> | undefined = $state();

	function readCSSPalette(): string[] {
		if (typeof document === "undefined") return [];
		const style = getComputedStyle(document.documentElement);
		const colors: string[] = [];
		for (let i = 1; i <= 5; i++) {
			const c = style.getPropertyValue(`--netz-chart-${i}`).trim();
			if (c) colors.push(c);
		}
		return colors;
	}

	function buildTheme(colors: string[]): Record<string, unknown> {
		return {
			color: colors.length > 0 ? colors : ["#0F172A", "#3B82F6", "#10B981", "#F59E0B", "#EF4444"],
		};
	}

	onMount(() => {
		if (!containerEl) return;

		const themePalette = palette ?? readCSSPalette();
		const themeName = "netz-theme";
		echarts.registerTheme(themeName, buildTheme(themePalette));

		chart = echarts.init(containerEl, themeName, { renderer: "canvas" });

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
		const merged = optionsOverride ? { ...option, ...optionsOverride } : option;
		chart.setOption(merged, { notMerge: true });
	});
</script>

<div
	class={cn("relative w-full overflow-hidden rounded-lg", className)}
	style="height: {height}px"
>
	{#if loading}
		<div class="absolute inset-0 z-10 flex items-center justify-center bg-white/80 dark:bg-zinc-900/80">
			<div class="h-8 w-8 animate-spin rounded-full border-4 border-zinc-200 border-t-blue-600"></div>
		</div>
	{/if}

	{#if empty && !loading}
		<div class="absolute inset-0 z-10 flex items-center justify-center">
			<p class="text-sm text-zinc-500 dark:text-zinc-400">{emptyMessage}</p>
		</div>
	{/if}

	<div bind:this={containerEl} class="h-full w-full" style:visibility={empty ? "hidden" : "visible"}></div>
</div>
