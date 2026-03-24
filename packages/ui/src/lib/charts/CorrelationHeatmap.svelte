<script lang="ts">
	import { onMount } from "svelte";
	import type { BaseChartProps } from "./ChartContainer.svelte";
	import ChartContainer from "./ChartContainer.svelte";
	import { echarts } from "./echarts-setup.js";

	interface CorrelationHeatmapProps extends BaseChartProps {
		matrix: number[][];
		labels: string[];
		onPairSelect?: (a: string, b: string) => void;
	}

	let {
		matrix,
		labels,
		onPairSelect,
		height = 500,
		...rest
	}: CorrelationHeatmapProps = $props();

	// ── Clustering ──────────────────────────────────────────────────────

	let clustered = $state(false);

	function greedyClusterOrder(mat: number[][]): number[] {
		const n = mat.length;
		if (n <= 2) return Array.from({ length: n }, (_, i) => i);

		const visited = new Set<number>();
		const order: number[] = [0];
		visited.add(0);

		for (let step = 1; step < n; step++) {
			const last = order[order.length - 1]!;
			let bestIdx = -1;
			let bestCorr = -Infinity;

			for (let j = 0; j < n; j++) {
				if (visited.has(j)) continue;
				const corr = mat[last]?.[j] ?? 0;
				if (corr > bestCorr) {
					bestCorr = corr;
					bestIdx = j;
				}
			}

			if (bestIdx >= 0) {
				order.push(bestIdx);
				visited.add(bestIdx);
			}
		}

		return order;
	}

	let displayOrder = $derived.by(() => {
		if (!clustered || matrix.length === 0) {
			return Array.from({ length: labels.length }, (_, i) => i);
		}
		return greedyClusterOrder(matrix);
	});

	let displayLabels = $derived(displayOrder.map((i) => labels[i] ?? ""));

	// ── Chart option ────────────────────────────────────────────────────

	let option = $derived.by(() => {
		const n = displayOrder.length;
		const data: [number, number, number][] = [];

		for (let yi = 0; yi < n; yi++) {
			for (let xi = 0; xi < n; xi++) {
				const origY = displayOrder[yi]!;
				const origX = displayOrder[xi]!;
				const v = matrix[origY]?.[origX] ?? 0;
				data.push([xi, yi, Number(v.toFixed(3))]);
			}
		}

		const isLarge = n > 15;

		return {
			tooltip: {
				position: "top",
				formatter: (params: { data: [number, number, number] }) => {
					const [x, y, v] = params.data;
					return `${displayLabels[x] ?? x} / ${displayLabels[y] ?? y}: ${v.toFixed(3)}`;
				},
			},
			grid: {
				left: isLarge ? 120 : 100,
				right: 80,
				top: 20,
				bottom: isLarge ? 100 : 60,
			},
			xAxis: {
				type: "category",
				data: displayLabels,
				splitArea: { show: true },
				axisLabel: {
					rotate: isLarge ? 90 : 45,
					fontSize: isLarge ? 9 : 11,
					interval: 0,
					overflow: "truncate",
					width: 80,
				},
			},
			yAxis: {
				type: "category",
				data: displayLabels,
				splitArea: { show: true },
				axisLabel: {
					fontSize: isLarge ? 9 : 11,
					interval: 0,
					overflow: "truncate",
					width: 80,
				},
			},
			visualMap: {
				min: -1,
				max: 1,
				calculable: true,
				orient: "horizontal",
				left: "center",
				bottom: 0,
				inRange: {
					color: [
						"#053061", "#2166ac", "#92c5de",
						"#f7f7f7",
						"#f4a582", "#d6604d", "#67001f",
					],
				},
				text: ["+1", "\u22121"],
			},
			series: [
				{
					type: "heatmap",
					data,
					label: { show: !isLarge, fontSize: 9 },
					emphasis: { itemStyle: { shadowBlur: 10, shadowColor: "rgba(0,0,0,0.3)" } },
				},
			],
		} as Record<string, unknown>;
	});

	// ── Click handler ───────────────────────────────────────────────────

	let containerEl: HTMLDivElement | undefined = $state();

	$effect(() => {
		if (!containerEl || !onPairSelect) return;
		const chart = echarts.getInstanceByDom(containerEl.querySelector("[role='img']") as HTMLElement);
		if (!chart) return;

		const handler = (params: { componentType?: string; data?: unknown }) => {
			if (params.componentType !== "series") return;
			const d = params.data as [number, number, number] | undefined;
			if (!d) return;
			const [xi, yi] = d;
			if (xi === yi) return;
			const labelA = displayLabels[xi];
			const labelB = displayLabels[yi];
			if (labelA && labelB) onPairSelect!(labelA, labelB);
		};

		chart.on("click", handler);
		return () => chart.off("click", handler);
	});
</script>

<div class="corr-heatmap" bind:this={containerEl}>
	<div class="corr-toolbar">
		<button
			class="corr-toggle"
			class:corr-toggle--active={clustered}
			onclick={() => clustered = !clustered}
		>
			{clustered ? "Clustered" : "Original order"}
		</button>
	</div>
	<ChartContainer {option} {height} {...rest} />
</div>

<style>
	.corr-heatmap {
		position: relative;
	}

	.corr-toolbar {
		display: flex;
		justify-content: flex-end;
		padding: 0 0 var(--netz-space-stack-2xs, 4px);
	}

	.corr-toggle {
		padding: 2px 10px;
		border: 1px solid var(--netz-border);
		border-radius: var(--netz-radius-sm, 6px);
		background: transparent;
		color: var(--netz-text-secondary);
		font-size: var(--netz-text-label, 0.75rem);
		font-family: var(--netz-font-sans);
		cursor: pointer;
		transition: background-color 120ms ease, color 120ms ease;
	}

	.corr-toggle:hover {
		background: var(--netz-surface-alt);
	}

	.corr-toggle--active {
		background: color-mix(in srgb, var(--netz-brand-primary) 10%, transparent);
		color: var(--netz-brand-primary);
		border-color: var(--netz-brand-primary);
	}
</style>
