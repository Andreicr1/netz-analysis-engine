<!--
  Up/Down Capture Ratios — 4 capture metrics + benchmark label + bar chart.
-->
<script lang="ts">
	import { formatNumber } from "@investintell/ui";
	import { ChartContainer } from "@investintell/ui/charts";
	import { globalChartOptions } from "@investintell/ui/charts/echarts-setup";
	import type { CaptureRatios } from "$wealth/types/entity-analytics";

	interface Props {
		capture: CaptureRatios;
	}

	let { capture }: Props = $props();

	function captureColor(v: number | null, isDown = false): string {
		if (v == null) return "var(--ii-text-muted)";
		if (isDown) return v < 100 ? "var(--ii-success)" : "var(--ii-danger)";
		return v > 100 ? "var(--ii-success)" : "var(--ii-danger)";
	}

	let chartOption = $derived.by(() => {
		const up = capture.up_capture ?? 0;
		const down = capture.down_capture ?? 0;
		const upNum = capture.up_number_ratio ?? 0;
		const downNum = capture.down_number_ratio ?? 0;

		return {
			...globalChartOptions,
			grid: { left: 60, right: 30, top: 30, bottom: 30 },
			xAxis: {
				type: "category",
				data: ["Up Capture", "Down Capture", "Up Number", "Down Number"],
				axisLabel: { fontSize: 10 },
			},
			yAxis: {
				type: "value",
				axisLabel: { fontSize: 10, formatter: (v: number) => `${v}%` },
			},
			tooltip: {
				trigger: "axis",
				confine: true,
				formatter: (params: { data: { value: number; name: string } }[]) => {
					if (!params[0]) return "";
					const d = params[0].data;
					return `<div style="font-size:12px"><b>${d.name}</b>: ${formatNumber(d.value, 1)}%</div>`;
				},
			},
			series: [
				{
					type: "bar",
					data: [
						{ value: up, name: "Up Capture", itemStyle: { color: up > 100 ? "#22c55e" : "#f59e0b" } },
						{ value: down, name: "Down Capture", itemStyle: { color: down < 100 ? "#22c55e" : "#ef4444" } },
						{ value: upNum, name: "Up Number", itemStyle: { color: "#3b82f6" } },
						{ value: downNum, name: "Down Number", itemStyle: { color: "#8b5cf6" } },
					],
					barWidth: "50%",
					label: {
						show: true,
						position: "top",
						fontSize: 11,
						fontWeight: 600,
						formatter: (p: { value: number }) => `${formatNumber(p.value, 1)}%`,
					},
					markLine: {
						silent: true,
						data: [{ yAxis: 100, lineStyle: { color: "var(--ii-text-muted)", type: "dashed", width: 1 }, label: { formatter: "100%", position: "end", fontSize: 10 } }],
					},
				},
			],
		} as Record<string, unknown>;
	});
</script>

<section class="ea-panel">
	<h2 class="ea-panel-title">
		Up/Down Capture
		<span class="ea-bm-badge">vs {capture.benchmark_label}
			<span class="ea-bm-src">({capture.benchmark_source})</span>
		</span>
	</h2>
	<div class="ea-capture-kpis">
		<div class="ea-capture-kpi">
			<span class="ea-stat-label">Up Capture</span>
			<span class="ea-stat-value" style:color={captureColor(capture.up_capture)}>
				{capture.up_capture != null ? `${formatNumber(capture.up_capture, 1)}%` : "\u2014"}
			</span>
		</div>
		<div class="ea-capture-kpi">
			<span class="ea-stat-label">Down Capture</span>
			<span class="ea-stat-value" style:color={captureColor(capture.down_capture, true)}>
				{capture.down_capture != null ? `${formatNumber(capture.down_capture, 1)}%` : "\u2014"}
			</span>
		</div>
		<div class="ea-capture-kpi">
			<span class="ea-stat-label">Up Periods</span>
			<span class="ea-stat-value">{capture.up_periods}</span>
		</div>
		<div class="ea-capture-kpi">
			<span class="ea-stat-label">Down Periods</span>
			<span class="ea-stat-value">{capture.down_periods}</span>
		</div>
	</div>
	<ChartContainer
		option={chartOption}
		height={260}
		empty={false}
		emptyMessage="Insufficient benchmark data for capture analysis"
		ariaLabel="Up/Down capture ratios chart"
	/>
</section>

<style>
	.ea-panel {
		background: var(--ii-surface-elevated);
		border: 1px solid var(--ii-border);
		border-radius: 12px;
		padding: clamp(16px, 1rem + 0.5vw, 28px);
		margin-bottom: 16px;
	}

	.ea-panel-title {
		font-size: 0.9rem;
		font-weight: 700;
		color: var(--ii-text-primary);
		margin: 0 0 12px;
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.ea-capture-kpis {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
		gap: 12px;
		margin-bottom: 16px;
	}

	.ea-capture-kpi {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.ea-stat-label {
		font-size: 0.7rem;
		font-weight: 500;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--ii-text-muted);
	}

	.ea-stat-value {
		font-size: 1.1rem;
		font-weight: 700;
		color: var(--ii-text-primary);
		font-variant-numeric: tabular-nums;
	}

	.ea-bm-badge {
		font-size: 0.7rem;
		font-weight: 500;
		color: var(--ii-text-secondary);
		background: var(--ii-surface-alt);
		padding: 2px 8px;
		border-radius: 4px;
	}

	.ea-bm-src {
		color: var(--ii-text-muted);
		font-style: italic;
	}
</style>
