<!--
  Entity Analytics Vitrine — institutional-grade analytics for any entity (fund or model portfolio).
  5 Panels: Risk Statistics, Drawdown, Up/Down Capture, Rolling Returns, Return Distribution.
  Fully polymorphic: entity_type is display-only, never branching logic.
-->
<script lang="ts">
	import { goto } from "$app/navigation";
	import { page } from "$app/stores";
	import {
		PageHeader,
		formatPercent,
		formatNumber,
		formatRatio,
		formatBps,
		formatDate,
		plColor,
	} from "@netz/ui";
	import { ChartContainer } from "@netz/ui/charts";
	import { globalChartOptions, statusColors } from "@netz/ui/charts/echarts-setup";
	import type { PageData } from "./$types";
	import type { EntityAnalyticsData } from "./+page.server";

	let { data }: { data: PageData } = $props();

	let analytics = $derived(data.analytics as EntityAnalyticsData | null);
	let currentWindow = $derived(data.window as string);

	const windows = ["3m", "6m", "1y", "3y", "5y"] as const;

	function switchWindow(w: string) {
		const entityId = data.entityId;
		goto(`/entity-analytics?entity_id=${entityId}&window=${w}`, { replaceState: true });
	}

	// ── Metric helpers ─────────────────────────────────────────────────

	function fmtPct(v: number | null): string {
		if (v == null) return "—";
		return formatPercent(v, 2, "en-US", true);
	}

	function fmtNum(v: number | null, decimals = 2): string {
		if (v == null) return "—";
		return formatNumber(v, decimals, "en-US");
	}

	function fmtRat(v: number | null): string {
		if (v == null) return "—";
		return formatRatio(v, 2, "x", "en-US");
	}

	function captureColor(v: number | null, isDown = false): string {
		if (v == null) return "var(--netz-text-muted)";
		if (isDown) return v < 100 ? "var(--netz-success)" : "var(--netz-danger)";
		return v > 100 ? "var(--netz-success)" : "var(--netz-danger)";
	}

	// ── 1. Drawdown Chart Option ───────────────────────────────────────

	let drawdownOption = $derived.by(() => {
		if (!analytics) return null;
		const dd = analytics.drawdown;
		if (!dd.dates.length) return null;
		return {
			...globalChartOptions,
			grid: { left: 60, right: 20, top: 20, bottom: 60 },
			xAxis: {
				type: "category",
				data: dd.dates,
				axisLabel: { fontSize: 10, rotate: 0, formatter: (v: string) => v.slice(5) },
				boundaryGap: false,
			},
			yAxis: {
				type: "value",
				axisLabel: { fontSize: 10, formatter: (v: number) => `${(v * 100).toFixed(1)}%` },
				max: 0,
			},
			tooltip: {
				trigger: "axis",
				confine: true,
				formatter: (params: { data: number; axisValue: string }[]) => {
					const p = params[0];
					if (!p) return "";
					return `<div style="font-size:12px"><b>${p.axisValue}</b><br/>Drawdown: <b style="color:${statusColors.breach}">${(p.data * 100).toFixed(2)}%</b></div>`;
				},
			},
			dataZoom: [
				{ type: "inside", start: 0, end: 100 },
				{ type: "slider", start: 0, end: 100, height: 20, bottom: 8 },
			],
			series: [
				{
					type: "line",
					data: dd.values,
					areaStyle: {
						color: {
							type: "linear",
							x: 0, y: 0, x2: 0, y2: 1,
							colorStops: [
								{ offset: 0, color: "rgba(239, 68, 68, 0.4)" },
								{ offset: 1, color: "rgba(239, 68, 68, 0.05)" },
							],
						},
					},
					lineStyle: { color: "#ef4444", width: 1.5 },
					itemStyle: { color: "#ef4444" },
					symbol: "none",
					smooth: false,
				},
			],
		} as Record<string, unknown>;
	});

	// ── 2. Capture Chart Option ────────────────────────────────────────

	let captureOption = $derived.by(() => {
		if (!analytics) return null;
		const c = analytics.capture;
		const up = c.up_capture ?? 0;
		const down = c.down_capture ?? 0;
		const upNum = c.up_number_ratio ?? 0;
		const downNum = c.down_number_ratio ?? 0;

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
					return `<div style="font-size:12px"><b>${d.name}</b>: ${d.value.toFixed(1)}%</div>`;
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
						formatter: (p: { value: number }) => `${p.value.toFixed(1)}%`,
					},
					markLine: {
						silent: true,
						data: [{ yAxis: 100, lineStyle: { color: "var(--netz-text-muted)", type: "dashed", width: 1 }, label: { formatter: "100%", position: "end", fontSize: 10 } }],
					},
				},
			],
		} as Record<string, unknown>;
	});

	// ── 3. Rolling Returns Chart Option ────────────────────────────────

	const rollingColors = ["#1b365d", "#3a7bd5", "#ff975a", "#8b9daf"];

	let rollingOption = $derived.by(() => {
		if (!analytics) return null;
		const series = analytics.rolling_returns.series;
		if (!series.length) return null;

		// Use dates from the longest series
		const longestSeries = series.reduce((a, b) => a.dates.length > b.dates.length ? a : b);

		return {
			...globalChartOptions,
			grid: { left: 60, right: 20, top: 30, bottom: 60 },
			legend: {
				data: series.map(s => s.window_label),
				top: 0,
				left: "center",
				textStyle: { fontSize: 11 },
			},
			xAxis: {
				type: "category",
				data: longestSeries.dates,
				axisLabel: { fontSize: 10, rotate: 0, formatter: (v: string) => v.slice(5) },
				boundaryGap: false,
			},
			yAxis: {
				type: "value",
				axisLabel: { fontSize: 10, formatter: (v: number) => `${(v * 100).toFixed(0)}%` },
			},
			tooltip: {
				trigger: "axis",
				confine: true,
				formatter: (params: { seriesName: string; data: [string, number]; color: string }[]) => {
					if (!params.length) return "";
					let html = `<div style="font-size:12px"><b>${params[0].data[0]}</b>`;
					for (const p of params) {
						const val = (p.data[1] * 100).toFixed(2);
						html += `<br/><span style="color:${p.color}">\u25CF</span> ${p.seriesName}: <b>${val}%</b>`;
					}
					return html + "</div>";
				},
			},
			dataZoom: [
				{ type: "inside", start: 0, end: 100 },
				{ type: "slider", start: 0, end: 100, height: 20, bottom: 8 },
			],
			series: series.map((s, i) => ({
				name: s.window_label,
				type: "line",
				data: s.dates.map((d, j) => [d, s.values[j]]),
				smooth: false,
				symbol: "none",
				lineStyle: { width: 1.5, color: rollingColors[i % rollingColors.length] },
				itemStyle: { color: rollingColors[i % rollingColors.length] },
			})),
		} as Record<string, unknown>;
	});

	// ── 4. Distribution Chart Option ───────────────────────────────────

	let distributionOption = $derived.by(() => {
		if (!analytics) return null;
		const dist = analytics.distribution;
		if (!dist.bin_edges.length) return null;

		// Bar centers from bin edges
		const centers: number[] = [];
		for (let i = 0; i < dist.bin_edges.length - 1; i++) {
			centers.push((dist.bin_edges[i] + dist.bin_edges[i + 1]) / 2);
		}

		// Normal curve overlay
		const normalCurve: [number, number][] = [];
		if (dist.mean != null && dist.std != null && dist.std > 0) {
			const binWidth = centers.length > 1 ? Math.abs(centers[1] - centers[0]) : 0.001;
			const totalObs = dist.bin_counts.reduce((a, b) => a + b, 0);
			for (const x of centers) {
				const z = (x - dist.mean) / dist.std;
				const pdf = Math.exp(-0.5 * z * z) / (dist.std * Math.sqrt(2 * Math.PI));
				normalCurve.push([x, pdf * totalObs * binWidth]);
			}
		}

		const varLine = dist.var_95 != null ? dist.var_95 : null;
		const cvarLine = dist.cvar_95 != null ? dist.cvar_95 : null;

		return {
			...globalChartOptions,
			grid: { left: 50, right: 30, top: 30, bottom: 50 },
			xAxis: {
				type: "category",
				data: centers.map(c => (c * 100).toFixed(2)),
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
				formatter: (params: { seriesName: string; data: number | [number, number]; color: string }[]) => {
					if (!params.length) return "";
					const idx = (params[0] as { dataIndex: number }).dataIndex;
					const lo = (dist.bin_edges[idx] * 100).toFixed(3);
					const hi = (dist.bin_edges[idx + 1] * 100).toFixed(3);
					let html = `<div style="font-size:12px"><b>${lo}% to ${hi}%</b>`;
					for (const p of params) {
						const val = typeof p.data === "number" ? p.data : (p.data as [number, number])[1]?.toFixed(1);
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
							color: centers[i] < (varLine ?? -Infinity)
								? "rgba(239, 68, 68, 0.7)"
								: centers[i] < 0
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
						data: normalCurve.map((_, i) => normalCurve[i][1]),
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

{#if !analytics}
	<PageHeader title="Entity Analytics" />
	<div class="ea-empty">
		<p>No analytics data available. Verify the entity has sufficient NAV history.</p>
	</div>
{:else}
	<PageHeader title={analytics.entity_name}>
		{#snippet actions()}
			<div class="ea-controls">
				<span class="ea-entity-badge">{analytics.entity_type === "model_portfolio" ? "Model Portfolio" : "Fund"}</span>
				<div class="ea-window-toggle">
					{#each windows as w (w)}
						<button
							class="ea-win-btn"
							class:ea-win-btn--active={currentWindow === w}
							onclick={() => switchWindow(w)}
						>
							{w.toUpperCase()}
						</button>
					{/each}
				</div>
			</div>
		{/snippet}
	</PageHeader>

	<!-- ═══════════════════════════════════════════════════════════════ -->
	<!-- PANEL 1: Risk Statistics                                       -->
	<!-- ═══════════════════════════════════════════════════════════════ -->
	<section class="ea-panel">
		<h2 class="ea-panel-title">Risk Statistics</h2>
		<p class="ea-panel-sub">{analytics.risk_statistics.n_observations} trading days &middot; as of {formatDate(analytics.as_of_date, "medium", "en-US")}</p>
		<div class="ea-stats-grid">
			<div class="ea-stat">
				<span class="ea-stat-label">Ann. Return</span>
				<span class="ea-stat-value" style:color={plColor(analytics.risk_statistics.annualized_return)}>
					{fmtPct(analytics.risk_statistics.annualized_return)}
				</span>
			</div>
			<div class="ea-stat">
				<span class="ea-stat-label">Ann. Volatility</span>
				<span class="ea-stat-value">{fmtPct(analytics.risk_statistics.annualized_volatility)}</span>
			</div>
			<div class="ea-stat">
				<span class="ea-stat-label">Sharpe</span>
				<span class="ea-stat-value">{fmtNum(analytics.risk_statistics.sharpe_ratio)}</span>
			</div>
			<div class="ea-stat">
				<span class="ea-stat-label">Sortino</span>
				<span class="ea-stat-value">{fmtNum(analytics.risk_statistics.sortino_ratio)}</span>
			</div>
			<div class="ea-stat">
				<span class="ea-stat-label">Calmar</span>
				<span class="ea-stat-value">{fmtNum(analytics.risk_statistics.calmar_ratio)}</span>
			</div>
			<div class="ea-stat">
				<span class="ea-stat-label">Max Drawdown</span>
				<span class="ea-stat-value" style:color="var(--netz-danger)">
					{fmtPct(analytics.risk_statistics.max_drawdown)}
				</span>
			</div>
			<div class="ea-stat">
				<span class="ea-stat-label">Alpha</span>
				<span class="ea-stat-value" style:color={plColor(analytics.risk_statistics.alpha)}>
					{fmtPct(analytics.risk_statistics.alpha)}
				</span>
			</div>
			<div class="ea-stat">
				<span class="ea-stat-label">Beta</span>
				<span class="ea-stat-value">{fmtNum(analytics.risk_statistics.beta)}</span>
			</div>
			<div class="ea-stat">
				<span class="ea-stat-label">Tracking Error</span>
				<span class="ea-stat-value">{fmtPct(analytics.risk_statistics.tracking_error)}</span>
			</div>
			<div class="ea-stat">
				<span class="ea-stat-label">Info Ratio</span>
				<span class="ea-stat-value">{fmtNum(analytics.risk_statistics.information_ratio)}</span>
			</div>
		</div>
	</section>

	<!-- ═══════════════════════════════════════════════════════════════ -->
	<!-- PANEL 2: Drawdown Analysis                                     -->
	<!-- ═══════════════════════════════════════════════════════════════ -->
	<section class="ea-panel">
		<h2 class="ea-panel-title">Drawdown Analysis</h2>
		<div class="ea-dd-kpis">
			<div class="ea-dd-kpi">
				<span class="ea-stat-label">Max Drawdown</span>
				<span class="ea-stat-value" style:color="var(--netz-danger)">
					{fmtPct(analytics.drawdown.max_drawdown)}
				</span>
			</div>
			<div class="ea-dd-kpi">
				<span class="ea-stat-label">Current DD</span>
				<span class="ea-stat-value" style:color={analytics.drawdown.current_drawdown && analytics.drawdown.current_drawdown < -0.01 ? "var(--netz-danger)" : "var(--netz-text-secondary)"}>
					{fmtPct(analytics.drawdown.current_drawdown)}
				</span>
			</div>
			<div class="ea-dd-kpi">
				<span class="ea-stat-label">Longest DD</span>
				<span class="ea-stat-value">{analytics.drawdown.longest_duration_days ?? "—"} days</span>
			</div>
			<div class="ea-dd-kpi">
				<span class="ea-stat-label">Avg Recovery</span>
				<span class="ea-stat-value">{analytics.drawdown.avg_recovery_days != null ? `${analytics.drawdown.avg_recovery_days.toFixed(0)} days` : "—"}</span>
			</div>
		</div>
		<ChartContainer
			option={drawdownOption ?? {}}
			height={280}
			empty={!drawdownOption}
			emptyMessage="Insufficient data for drawdown analysis"
			ariaLabel="Drawdown analysis chart"
		/>
		{#if analytics.drawdown.worst_periods.length}
			<div class="ea-dd-table">
				<table>
					<thead>
						<tr>
							<th>Start</th>
							<th>Trough</th>
							<th>Recovery</th>
							<th>Depth</th>
							<th>Duration</th>
						</tr>
					</thead>
					<tbody>
						{#each analytics.drawdown.worst_periods as p (p.start_date)}
							<tr>
								<td>{p.start_date}</td>
								<td>{p.trough_date}</td>
								<td>{p.end_date ?? "open"}</td>
								<td style:color="var(--netz-danger)">{fmtPct(p.depth)}</td>
								<td>{p.duration_days}d</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}
	</section>

	<!-- ═══════════════════════════════════════════════════════════════ -->
	<!-- PANEL 3: Up/Down Capture                                       -->
	<!-- ═══════════════════════════════════════════════════════════════ -->
	<section class="ea-panel">
		<h2 class="ea-panel-title">
			Up/Down Capture
			<span class="ea-bm-badge">vs {analytics.capture.benchmark_label}
				<span class="ea-bm-src">({analytics.capture.benchmark_source})</span>
			</span>
		</h2>
		<div class="ea-capture-kpis">
			<div class="ea-capture-kpi">
				<span class="ea-stat-label">Up Capture</span>
				<span class="ea-stat-value" style:color={captureColor(analytics.capture.up_capture)}>
					{analytics.capture.up_capture != null ? `${analytics.capture.up_capture.toFixed(1)}%` : "—"}
				</span>
			</div>
			<div class="ea-capture-kpi">
				<span class="ea-stat-label">Down Capture</span>
				<span class="ea-stat-value" style:color={captureColor(analytics.capture.down_capture, true)}>
					{analytics.capture.down_capture != null ? `${analytics.capture.down_capture.toFixed(1)}%` : "—"}
				</span>
			</div>
			<div class="ea-capture-kpi">
				<span class="ea-stat-label">Up Periods</span>
				<span class="ea-stat-value">{analytics.capture.up_periods}</span>
			</div>
			<div class="ea-capture-kpi">
				<span class="ea-stat-label">Down Periods</span>
				<span class="ea-stat-value">{analytics.capture.down_periods}</span>
			</div>
		</div>
		<ChartContainer
			option={captureOption ?? {}}
			height={260}
			empty={!captureOption}
			emptyMessage="Insufficient benchmark data for capture analysis"
			ariaLabel="Up/Down capture ratios chart"
		/>
	</section>

	<!-- ═══════════════════════════════════════════════════════════════ -->
	<!-- PANEL 4: Rolling Returns                                       -->
	<!-- ═══════════════════════════════════════════════════════════════ -->
	<section class="ea-panel">
		<h2 class="ea-panel-title">Rolling Returns</h2>
		<ChartContainer
			option={rollingOption ?? {}}
			height={320}
			empty={!rollingOption}
			emptyMessage="Insufficient data for rolling return computation"
			ariaLabel="Rolling returns chart"
		/>
	</section>

	<!-- ═══════════════════════════════════════════════════════════════ -->
	<!-- PANEL 5: Return Distribution                                   -->
	<!-- ═══════════════════════════════════════════════════════════════ -->
	<section class="ea-panel">
		<h2 class="ea-panel-title">Return Distribution</h2>
		<div class="ea-dist-kpis">
			<div class="ea-stat">
				<span class="ea-stat-label">Mean</span>
				<span class="ea-stat-value">{fmtPct(analytics.distribution.mean)}</span>
			</div>
			<div class="ea-stat">
				<span class="ea-stat-label">Std Dev</span>
				<span class="ea-stat-value">{fmtPct(analytics.distribution.std)}</span>
			</div>
			<div class="ea-stat">
				<span class="ea-stat-label">Skewness</span>
				<span class="ea-stat-value" style:color={analytics.distribution.skewness != null && analytics.distribution.skewness < -0.5 ? "var(--netz-warning)" : "var(--netz-text-primary)"}>
					{fmtNum(analytics.distribution.skewness)}
				</span>
			</div>
			<div class="ea-stat">
				<span class="ea-stat-label">Excess Kurtosis</span>
				<span class="ea-stat-value" style:color={analytics.distribution.kurtosis != null && analytics.distribution.kurtosis > 3 ? "var(--netz-warning)" : "var(--netz-text-primary)"}>
					{fmtNum(analytics.distribution.kurtosis)}
				</span>
			</div>
			<div class="ea-stat">
				<span class="ea-stat-label">VaR (95%)</span>
				<span class="ea-stat-value" style:color="var(--netz-danger)">{fmtPct(analytics.distribution.var_95)}</span>
			</div>
			<div class="ea-stat">
				<span class="ea-stat-label">CVaR (95%)</span>
				<span class="ea-stat-value" style:color="var(--netz-danger)">{fmtPct(analytics.distribution.cvar_95)}</span>
			</div>
		</div>
		<ChartContainer
			option={distributionOption ?? {}}
			height={300}
			empty={!distributionOption}
			emptyMessage="Insufficient data for distribution analysis"
			ariaLabel="Return distribution histogram"
		/>
	</section>
{/if}

<style>
	/* ── Layout & Panel ────────────────────────────────────────────── */

	.ea-empty {
		display: flex;
		align-items: center;
		justify-content: center;
		min-height: 300px;
		color: var(--netz-text-muted);
		font-size: 0.875rem;
	}

	.ea-controls {
		display: flex;
		align-items: center;
		gap: 12px;
	}

	.ea-entity-badge {
		font-size: 0.7rem;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--netz-brand-primary);
		background: color-mix(in srgb, var(--netz-brand-primary) 12%, transparent);
		padding: 3px 10px;
		border-radius: 6px;
	}

	.ea-window-toggle {
		display: flex;
		gap: 2px;
		background: var(--netz-surface-alt);
		border-radius: 8px;
		padding: 2px;
	}

	.ea-win-btn {
		font-size: 0.75rem;
		font-weight: 600;
		padding: 4px 12px;
		border: none;
		border-radius: 6px;
		background: transparent;
		color: var(--netz-text-secondary);
		cursor: pointer;
		transition: all 0.15s ease;
	}

	.ea-win-btn:hover {
		color: var(--netz-text-primary);
		background: color-mix(in srgb, var(--netz-border) 40%, transparent);
	}

	.ea-win-btn--active {
		background: var(--netz-surface-elevated);
		color: var(--netz-brand-primary);
		box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
	}

	.ea-panel {
		background: var(--netz-surface-elevated);
		border: 1px solid var(--netz-border);
		border-radius: 12px;
		padding: clamp(16px, 1rem + 0.5vw, 28px);
		margin-bottom: 16px;
	}

	.ea-panel-title {
		font-size: 0.9rem;
		font-weight: 700;
		color: var(--netz-text-primary);
		margin: 0 0 4px;
		display: flex;
		align-items: center;
		gap: 8px;
	}

	.ea-panel-sub {
		font-size: 0.75rem;
		color: var(--netz-text-muted);
		margin: 0 0 16px;
	}

	/* ── Stats Grid ────────────────────────────────────────────────── */

	.ea-stats-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));
		gap: 12px;
		margin-bottom: 8px;
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
		color: var(--netz-text-muted);
	}

	.ea-stat-value {
		font-size: 1.1rem;
		font-weight: 700;
		color: var(--netz-text-primary);
		font-variant-numeric: tabular-nums;
	}

	/* ── Drawdown KPIs ─────────────────────────────────────────────── */

	.ea-dd-kpis,
	.ea-capture-kpis,
	.ea-dist-kpis {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
		gap: 12px;
		margin-bottom: 16px;
	}

	.ea-dd-kpi,
	.ea-capture-kpi {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	/* ── Drawdown Table ────────────────────────────────────────────── */

	.ea-dd-table {
		margin-top: 12px;
		overflow-x: auto;
	}

	.ea-dd-table table {
		width: 100%;
		border-collapse: collapse;
		font-size: 0.78rem;
	}

	.ea-dd-table th {
		text-align: left;
		font-weight: 600;
		font-size: 0.7rem;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--netz-text-muted);
		padding: 6px 8px;
		border-bottom: 1px solid var(--netz-border);
	}

	.ea-dd-table td {
		padding: 5px 8px;
		color: var(--netz-text-secondary);
		border-bottom: 1px solid color-mix(in srgb, var(--netz-border) 50%, transparent);
		font-variant-numeric: tabular-nums;
	}

	/* ── Benchmark Badge ───────────────────────────────────────────── */

	.ea-bm-badge {
		font-size: 0.7rem;
		font-weight: 500;
		color: var(--netz-text-secondary);
		background: var(--netz-surface-alt);
		padding: 2px 8px;
		border-radius: 4px;
	}

	.ea-bm-src {
		color: var(--netz-text-muted);
		font-style: italic;
	}
</style>
