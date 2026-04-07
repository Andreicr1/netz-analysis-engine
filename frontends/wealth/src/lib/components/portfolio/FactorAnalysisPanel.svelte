<!--
  FactorAnalysisPanel — Risk decomposition (donut) + Style factor exposures (horizontal bar).
  Live API data integrated.
  Design: dark premium (Figma One X).
-->
<script lang="ts">
	import { ChartContainer } from "@investintell/ui/charts";
	import { globalChartOptions } from "@investintell/ui/charts/echarts-setup";
	import { EmptyState, formatNumber } from "@investintell/ui";
	import { workspace, type FactorContribution } from "$lib/state/portfolio-workspace.svelte";

	// ── Real API Data Integration ───────────────────────────────────────
	let data = $derived(workspace.localFactorAnalysis);
	let isLoading = $derived(workspace.isLoadingFactorAnalysis);
	let hasData = $derived(data != null);

	// Theme tokens for ECharts (CSS vars don't work inside option objects).
	let chartPalette = $state<string[]>(["#3a7bd5", "#ff975a", "#1b365d", "#8b9daf", "#d4e4f7"]);
	let successColor = $state("#22c55e");
	let dangerColor = $state("#ef4444");
	let textMuted = $state("#94a3b8");
	let textSecondary = $state("#cbccd1");
	let surfaceColor = $state("#141519");
	let borderSubtle = $state("rgba(64,66,73,0.3)");

	function readChartTokens() {
		if (typeof document === "undefined") return;
		const cs = getComputedStyle(document.documentElement);
		const get = (n: string, fallback: string) => cs.getPropertyValue(n).trim() || fallback;
		successColor = get("--ii-success", "#22c55e");
		dangerColor = get("--ii-danger", "#ef4444");
		textMuted = get("--ii-text-muted", "#94a3b8");
		textSecondary = get("--ii-text-secondary", "#cbccd1");
		surfaceColor = get("--ii-surface", "#141519");
		borderSubtle = get("--ii-border", "rgba(64,66,73,0.3)");
		chartPalette = [
			get("--ii-chart-2", "#3a7bd5"),
			get("--ii-chart-3", "#ff975a"),
			get("--ii-chart-1", "#1b365d"),
			get("--ii-chart-4", "#8b9daf"),
			get("--ii-chart-5", "#d4e4f7"),
		];
	}

	$effect(() => {
		readChartTokens();
		if (typeof document === "undefined") return;
		const obs = new MutationObserver(() => readChartTokens());
		obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
		return () => obs.disconnect();
	});

	// ── Risk Decomposition (Donut) ──────────────────────────────────────
	// Note: donut for 2-5 slices is sub-institutional (FactSet/Bloomberg
	// would use a stacked-100 horizontal bar). Kept as a donut for now;
	// chart-type change is queued for the redesign PR. This pass strips
	// the gradients / drop shadows / border-radius pitch-deck styling.
	let donutOption = $derived.by(() => {
		if (!data) return {};

		const systematic = data.systematic_risk_pct * 100;
		const idiosyncratic = data.specific_risk_pct * 100;

		const factorSlices = (data.factor_contributions || []).map((fc: FactorContribution) => ({
			value: fc.pct_contribution * 100,
			name: fc.factor_label,
		}));
		const slices = factorSlices.length > 0
			? factorSlices
			: [
				{ value: systematic, name: "Systematic (Market)" },
				{ value: idiosyncratic, name: "Idiosyncratic" },
			];

		return {
			...globalChartOptions,
			color: chartPalette,
			toolbox: { show: false },
			tooltip: {
				...globalChartOptions.tooltip,
				trigger: "item" as const,
				formatter: (p: { name?: string; value?: number; percent?: number; marker?: string }) =>
					`${p.marker ?? ""} ${p.name}<br/><strong>${formatNumber(p.percent ?? 0, 1)}%</strong> of total risk`,
			},
			legend: {
				bottom: 0,
				itemWidth: 10,
				itemHeight: 10,
				textStyle: { fontSize: 11, color: textMuted },
			},
			series: [
				{
					name: "Risk Decomposition",
					type: "pie" as const,
					radius: ["55%", "75%"],
					center: ["50%", "42%"],
					avoidLabelOverlap: true,
					label: { show: false },
					labelLine: { show: false },
					// Flat slices: 1px separator border using surface color,
					// no shadow, no border-radius. Institutional convention.
					itemStyle: {
						borderColor: surfaceColor,
						borderWidth: 1,
					},
					emphasis: {
						label: { show: true, fontSize: 13, fontWeight: 700, color: textSecondary },
					},
					data: slices,
				},
			],
		};
	});

	// ── Style Exposures (Horizontal Bar) ────────────────────────────────
	let barOption = $derived.by(() => {
		if (!data) return {};

		const exposures = data.portfolio_factor_exposures || {};
		const categories = Object.keys(exposures);
		const values = Object.values(exposures).map((v: unknown) => Math.round((v as number) * 1000) / 1000);

		return {
			...globalChartOptions,
			toolbox: { show: false },
			grid: { left: 110, right: 40, top: 8, bottom: 24, containLabel: false },
			tooltip: {
				...globalChartOptions.tooltip,
				trigger: "axis" as const,
				axisPointer: { type: "shadow" },
				formatter(params: unknown) {
					const list = Array.isArray(params) ? params : [params];
					const p = list[0] as { name?: string; value?: number; marker?: string };
					if (p.value == null) return "";
					const sign = p.value > 0 ? "+" : "";
					return `<strong>${p.name}</strong><br/>${p.marker ?? ""} Exposure: ${sign}${formatNumber(p.value, 3)}`;
				},
			},
			xAxis: {
				type: "value" as const,
				min: -1,
				max: 1,
				axisLabel: { formatter: "{value}", fontSize: 10, color: textMuted },
				splitLine: { lineStyle: { type: "dashed" as const, color: borderSubtle } },
			},
			yAxis: {
				type: "category" as const,
				data: categories,
				inverse: true,
				axisLabel: { fontSize: 11, fontWeight: 600, color: textSecondary },
				axisTick: { show: false },
				axisLine: { show: false },
			},
			series: [
				{
					name: "Exposure",
					type: "bar" as const,
					data: values.map((v) => ({
						value: v,
						// Flat fill — no gradient, shadow, or border-radius.
						itemStyle: { color: v >= 0 ? successColor : dangerColor },
					})),
					barWidth: "40%",
					label: {
						show: true,
						position: "right" as const,
						fontSize: 10,
						fontWeight: 600,
						color: textSecondary,
						formatter: (p: { value: number }) => {
							const sign = p.value > 0 ? "+" : "";
							return `${sign}${formatNumber(p.value, 2)}`;
						},
					},
					markLine: {
						silent: true,
						symbol: "none" as const,
						data: [{ xAxis: 0 }],
						lineStyle: { color: textMuted, type: "solid" as const, width: 1 },
						label: { show: false },
					},
				},
			],
		};
	});

	let fundCount = $derived(workspace.funds.length);
</script>

{#if !workspace.portfolio}
	<div class="p-6">
		<EmptyState
			title="No portfolio selected"
			message="Select a model portfolio to view factor analysis."
		/>
	</div>
{:else if isLoading}
	<div class="factor-loading">
		<div class="factor-spinner"></div>
		<p>Running Factor Analysis…</p>
	</div>
{:else if !hasData}
	<div class="p-6">
		<EmptyState
			title="No factor data"
			message="No factor analysis results are available for this portfolio."
		/>
	</div>
{:else}
	<div class="factor-panel">
		<div class="factor-header">
			<span class="factor-title">Factor Analysis</span>
			<span class="factor-pill">{fundCount} fund{fundCount !== 1 ? "s" : ""}</span>
		</div>

		<div class="factor-grid">
			<div class="factor-block">
				<span class="factor-label">Risk Decomposition</span>
				<ChartContainer
					option={donutOption}
					height={240}
					empty={!hasData}
					ariaLabel="Risk decomposition donut chart"
				/>
			</div>

			<div class="factor-block">
				<span class="factor-label">Style Factor Exposures</span>
				<ChartContainer
					option={barOption}
					height={240}
					empty={!hasData}
					ariaLabel="Style factor exposures bar chart"
				/>
			</div>
		</div>
	</div>
{/if}

<style>
	.factor-loading {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		padding: 48px;
		color: var(--ii-text-muted);
		gap: 16px;
	}

	.factor-loading p {
		font-size: 13px;
		font-weight: 500;
		animation: pulse 1.5s ease-in-out infinite;
	}

	.factor-spinner {
		width: 32px;
		height: 32px;
		border: 2px solid var(--ii-brand-primary);
		border-top-color: transparent;
		border-radius: 50%;
		animation: spin 0.8s linear infinite;
	}

	@keyframes spin { to { transform: rotate(360deg); } }
	@keyframes pulse { 50% { opacity: 0.5; } }

	.factor-panel {
		display: flex;
		flex-direction: column;
		gap: 24px;
		padding: 24px;
		height: 100%;
	}

	.factor-header {
		display: flex;
		align-items: center;
		gap: 12px;
	}

	.factor-title {
		font-size: 16px;
		font-weight: 700;
		color: var(--ii-text-primary);
		letter-spacing: -0.02em;
	}

	.factor-pill {
		font-size: 12px;
		color: var(--ii-text-muted);
		background: color-mix(in srgb, var(--ii-text-primary) 5%, transparent);
		border: 1px solid color-mix(in srgb, var(--ii-text-primary) 10%, transparent);
		padding: 2px 8px;
		border-radius: 999px;
		margin-left: auto;
	}

	.factor-grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 32px;
		flex: 1;
		min-height: 0;
		background: color-mix(in srgb, var(--ii-text-primary) 1.5%, transparent);
		border: 1px solid var(--ii-border-subtle);
		border-radius: 20px;
		padding: 20px;
	}

	.factor-block {
		display: flex;
		flex-direction: column;
		gap: 12px;
	}

	.factor-label {
		font-size: 11px;
		font-weight: 600;
		color: var(--ii-text-muted);
		text-transform: uppercase;
		letter-spacing: 0.06em;
	}
</style>
