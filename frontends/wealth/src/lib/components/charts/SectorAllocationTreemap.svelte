<!--
  Sector Allocation Treemap — current portfolio sector exposure.
  Uses ChartContainer + ii-theme for institutional consistency.
-->
<script lang="ts">
	import { ChartContainer } from "@investintell/ui/charts";
	import { globalChartOptions } from "@investintell/ui/charts/echarts-setup";

	interface Props {
		sectorWeights: Record<string, number>;
		height?: number;
	}

	let { sectorWeights = {}, height = 350 }: Props = $props();

	// GICS-inspired sector palette — 11 distinct hues for max sector coverage
	const SECTOR_COLORS: Record<string, string> = {
		"Information Technology": "#0177fb",
		"Communication Services": "#6366f1",
		"Health Care":            "#06b6d4",
		"Financials":             "#0ea5e9",
		"Consumer Discretionary": "#f59e0b",
		"Consumer Staples":       "#84cc16",
		"Industrials":            "#8b5cf6",
		"Energy":                 "#f97316",
		"Materials":              "#14b8a6",
		"Real Estate":            "#ec4899",
		"Utilities":              "#a78bfa",
	};
	const FALLBACK_COLORS = [
		"#64748b", "#94a3b8", "#78716c", "#a1a1aa",
	];

	let option = $derived.by(() => {
		if (!sectorWeights || Object.keys(sectorWeights).length === 0) return {};

		const entries = Object.entries(sectorWeights)
			.filter(([, v]) => v > 0)
			.sort(([, a], [, b]) => b - a);

		let fallbackIdx = 0;
		const data = entries.map(([name, value]) => {
			let color = SECTOR_COLORS[name];
			if (!color) {
				color = FALLBACK_COLORS[fallbackIdx % FALLBACK_COLORS.length];
				fallbackIdx++;
			}
			return {
				name,
				value: Number(value) * 100,
				itemStyle: { color },
			};
		});

		return {
			...globalChartOptions,
			toolbox: { show: false },
			tooltip: {
				formatter(info: any) {
					const pct = info.value?.toFixed(2) ?? "0";
					return `<span style="font-weight:600">${info.name}</span><br/>${pct}%`;
				},
				backgroundColor: "var(--ii-bg-elevated, #1e1e22)",
				borderColor: "var(--ii-border-subtle, #2a2a2e)",
				textStyle: { color: "var(--ii-text-primary, #e4e4e7)", fontSize: 12 },
			},
			series: [
				{
					name: "Sectors",
					type: "treemap",
					width: "100%",
					height: "100%",
					roam: false,
					nodeClick: false,
					breadcrumb: { show: false },
					label: {
						show: true,
						formatter(params: any) {
							return `${params.name}\n${params.value.toFixed(1)}%`;
						},
						fontSize: 13,
						fontWeight: 500,
						color: "#fff",
						lineHeight: 18,
						textShadowColor: "rgba(0,0,0,0.4)",
						textShadowBlur: 3,
					},
					upperLabel: { show: false },
					itemStyle: {
						borderColor: "var(--ii-bg, #14151a)",
						borderWidth: 2,
						gapWidth: 2,
						borderRadius: 4,
					},
					emphasis: {
						itemStyle: { borderColor: "#fff", borderWidth: 2 },
						label: { fontSize: 14, fontWeight: 700 },
					},
					data,
				},
			],
		};
	});

	let isEmpty = $derived(
		!sectorWeights || Object.keys(sectorWeights).length === 0,
	);
</script>

{#if !isEmpty}
	<ChartContainer {option} {height} />
{:else}
	<div class="no-data">Current allocation data not available.</div>
{/if}

<style>
	.no-data {
		height: 100%;
		display: flex;
		align-items: center;
		justify-content: center;
		color: var(--ii-text-muted);
		font-style: italic;
		font-size: 13px;
	}
</style>
