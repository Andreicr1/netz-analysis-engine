<!--
  Return Distribution — histogram with normal overlay + moments sidebar + VaR/CVaR.
-->
<script lang="ts">
	import { formatPercent, formatNumber } from "@investintell/ui";
	import { ChartContainer } from "@investintell/ui/charts";
	import { globalChartOptions } from "@investintell/ui/charts/echarts-setup";
	import type { ReturnDistribution } from "$wealth/types/entity-analytics";

	interface Props {
		distribution: ReturnDistribution;
	}

	let { distribution }: Props = $props();

	function fmtPct(v: number | null): string {
		if (v == null) return "\u2014";
		return formatPercent(v, 2, "en-US", true);
	}

	function fmtNum(v: number | null, decimals = 2): string {
		if (v == null) return "\u2014";
		return formatNumber(v, decimals, "en-US");
	}

	let isEmpty = $derived(!distribution.bin_edges.length);

	let chartOption = $derived.by(() => {
		const dist = distribution;
		if (!dist.bin_edges.length) return null;

		const centers: number[] = [];
		for (let i = 0; i < dist.bin_edges.length - 1; i++) {
			centers.push((dist.bin_edges[i]! + dist.bin_edges[i + 1]!) / 2);
		}

		const normalCurve: [number, number][] = [];
		if (dist.mean != null && dist.std != null && dist.std > 0) {
			const binWidth = centers.length > 1 ? Math.abs(centers[1]! - centers[0]!) : 0.001;
			const totalObs = dist.bin_counts.reduce((a, b) => a + b, 0);
			for (const x of centers) {
				const z = (x - dist.mean) / dist.std;
				const pdf = Math.exp(-0.5 * z * z) / (dist.std * Math.sqrt(2 * Math.PI));
				normalCurve.push([x, pdf * totalObs * binWidth]);
			}
		}

		const varLine = dist.var_95;

		return {
			...globalChartOptions,
			grid: { left: 50, right: 30, top: 30, bottom: 50 },
			xAxis: {
				type: "category",
				data: centers.map(c => formatNumber(c * 100, 2)),
				axisLabel: {
					fontSize: 9,
					rotate: 45,
					formatter: (v: string) => `${v}%`,
				},
			},
			yAxis: {
				type: "value",
				name: "Frequency",
				nameTextStyle: { fontSize: 10 },
				axisLabel: { fontSize: 10 },
			},
			tooltip: {
				trigger: "axis",
				confine: true,
				formatter: (params: { seriesName: string; data: number | [number, number]; color: string; dataIndex: number }[]) => {
					if (!params.length) return "";
					const idx = params[0]!.dataIndex;
					const lo = formatNumber(dist.bin_edges[idx]! * 100, 3);
					const hi = formatNumber(dist.bin_edges[idx + 1]! * 100, 3);
					let html = `<div style="font-size:12px"><b>${lo}% to ${hi}%</b>`;
					for (const p of params) {
						const val = typeof p.data === "number" ? p.data : formatNumber((p.data as [number, number])[1], 1);
						html += `<br/><span style="color:${p.color}">\u25CF</span> ${p.seriesName}: <b>${val}</b>`;
					}
					return html + "</div>";
				},
			},
			series: [
				{
					name: "Returns",
					type: "bar",
					data: dist.bin_counts.map((count, i) => ({
						value: count,
						itemStyle: {
							color: centers[i]! < (varLine ?? -Infinity)
								? "rgba(239, 68, 68, 0.7)"
								: centers[i]! < 0
									? "rgba(251, 146, 60, 0.6)"
									: "rgba(59, 130, 246, 0.6)",
						},
					})),
					barWidth: "90%",
				},
				...(normalCurve.length
					? [{
						name: "Normal",
						type: "line",
						data: normalCurve.map((_, i) => normalCurve[i]![1]),
						smooth: true,
						symbol: "none",
						lineStyle: { color: "#a855f7", width: 2, type: "dashed" as const },
						itemStyle: { color: "#a855f7" },
						z: 10,
					}]
					: []),
			],
		} as Record<string, unknown>;
	});
</script>

<section class="ea-panel">
	<h2 class="ea-panel-title">Return Distribution</h2>
	<div class="ea-dist-kpis">
		<div class="ea-stat">
			<span class="ea-stat-label">Mean</span>
			<span class="ea-stat-value">{fmtPct(distribution.mean)}</span>
		</div>
		<div class="ea-stat">
			<span class="ea-stat-label">Std Dev</span>
			<span class="ea-stat-value">{fmtPct(distribution.std)}</span>
		</div>
		<div class="ea-stat">
			<span class="ea-stat-label">Skewness</span>
			<span class="ea-stat-value" style:color={distribution.skewness != null && distribution.skewness < -0.5 ? "var(--ii-warning)" : "var(--ii-text-primary)"}>
				{fmtNum(distribution.skewness)}
			</span>
		</div>
		<div class="ea-stat">
			<span class="ea-stat-label">Excess Kurtosis</span>
			<span class="ea-stat-value" style:color={distribution.kurtosis != null && distribution.kurtosis > 3 ? "var(--ii-warning)" : "var(--ii-text-primary)"}>
				{fmtNum(distribution.kurtosis)}
			</span>
		</div>
		<div class="ea-stat">
			<span class="ea-stat-label">VaR (95%)</span>
			<span class="ea-stat-value" style:color="var(--ii-danger)">{fmtPct(distribution.var_95)}</span>
		</div>
		<div class="ea-stat">
			<span class="ea-stat-label">CVaR (95%)</span>
			<span class="ea-stat-value" style:color="var(--ii-danger)">{fmtPct(distribution.cvar_95)}</span>
		</div>
	</div>
	<ChartContainer
		option={chartOption ?? {}}
		height={300}
		empty={isEmpty}
		emptyMessage="Insufficient data for distribution analysis"
		ariaLabel="Return distribution histogram"
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
	}

	.ea-dist-kpis {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
		gap: 12px;
		margin-bottom: 16px;
	}

	.ea-stat {
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
</style>
