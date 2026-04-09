<!--
  ConstructionResultsOverlay — Full-screen takeover displaying
  construction run results (Phase 11 "Million Dollar" refactor).

  Layout:
    Header — portfolio name + "Construction Successful" badge + close
    Row 1  — KPI strip (Expected Return, Volatility, Risk Level, Return Efficiency)
    Row 2  — Donut chart (allocation) + Horizontal bar (stress scenarios)
    Row 3  — Narrative summary (if available)

  Charts use ECharts via ChartContainer from @investintell/ui/charts
  and chartTokens() for institutional dark-mode styling.
-->
<script lang="ts">
	import X from "lucide-svelte/icons/x";
	import CheckCircle from "lucide-svelte/icons/check-circle";
	import { formatPercent, formatNumber } from "@investintell/ui";
	import { ChartContainer } from "@investintell/ui/charts";
	import { workspace } from "$lib/state/portfolio-workspace.svelte";
	import type { ConstructionStressResult } from "$lib/state/portfolio-workspace.svelte";
	import { portfolioDisplayName } from "$lib/constants/blocks";
	import { blockLabel } from "$lib/constants/blocks";
	import { chartTokens } from "$lib/components/charts/chart-tokens";

	interface Props {
		onClose: () => void;
	}

	let { onClose }: Props = $props();

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === "Escape") {
			e.preventDefault();
			onClose();
		}
	}

	// ── Derived data ─────────────────────────────────────────
	const run = $derived(workspace.constructionRun);
	const metrics = $derived(run?.ex_ante_metrics ?? null);
	const narrative = $derived(run?.narrative ?? null);
	const stressResults = $derived(run?.stress_results ?? []);

	const portfolioName = $derived(
		workspace.portfolio
			? portfolioDisplayName(workspace.portfolio.display_name)
			: "Portfolio",
	);

	const tokens = $derived.by(() => chartTokens());

	// ── KPI helpers ──────────────────────────────────────────
	function kpiValue(key: string, format: "pct" | "ratio"): string {
		const v = metrics?.[key];
		if (v == null) return "—";
		if (format === "pct") return formatPercent(v, 2);
		return formatNumber(v, 2);
	}

	// ── Allocation Donut ─────────────────────────────────────
	// Institutional palette — distinct hues for up to 8 asset class blocks.
	const BLOCK_COLORS = [
		"#0177fb", "#11ec79", "#f59e0b", "#a855f7",
		"#06b6d4", "#ec4899", "#84cc16", "#f97316",
	];

	interface DonutSlice {
		name: string;
		value: number;
	}

	const allocationData = $derived.by<DonutSlice[]>(() => {
		const weights = run?.weights_proposed;
		if (!weights) return [];

		// Group weights by block_id from the fund_selection_schema
		const funds = workspace.portfolio?.fund_selection_schema?.funds ?? [];
		const blockMap = new Map<string, number>();

		for (const fund of funds) {
			const w = weights[fund.instrument_id];
			if (w == null || w <= 0) continue;
			const block = fund.block_id || "unallocated";
			blockMap.set(block, (blockMap.get(block) ?? 0) + w);
		}

		// Also include proposed weights not in schema (defensive)
		for (const [id, w] of Object.entries(weights)) {
			if (w <= 0) continue;
			const existing = funds.find((f) => f.instrument_id === id);
			if (existing) continue;
			blockMap.set("other", (blockMap.get("other") ?? 0) + w);
		}

		return Array.from(blockMap.entries())
			.map(([blockId, weight]) => ({
				name: blockLabel(blockId) || blockId,
				value: Math.round(weight * 10000) / 100,
			}))
			.sort((a, b) => b.value - a.value);
	});

	const allocationOption = $derived.by(() => {
		if (allocationData.length === 0) return {} as Record<string, unknown>;

		return {
			backgroundColor: "transparent",
			textStyle: { fontFamily: tokens.fontFamily },
			animation: true,
			animationDuration: 600,
			animationEasing: "cubicOut",
			tooltip: {
				trigger: "item" as const,
				backgroundColor: tokens.tooltipBg,
				borderColor: tokens.tooltipBorder,
				borderWidth: 1,
				padding: 12,
				formatter: (params: { name: string; value: number; percent: number }) => {
					return `<div style="font-family:Urbanist,sans-serif">
						<strong style="font-size:13px">${params.name}</strong><br/>
						<span style="font-size:12px;color:#85a0bd">Weight: ${formatPercent(params.value / 100, 2)}</span>
					</div>`;
				},
			},
			legend: {
				orient: "vertical" as const,
				right: 16,
				top: "center" as const,
				textStyle: {
					color: "#cbccd1",
					fontSize: 11,
					fontFamily: tokens.fontFamily,
				},
				itemWidth: 10,
				itemHeight: 10,
				itemGap: 8,
				formatter: (name: string) => {
					const item = allocationData.find((d) => d.name === name);
					return item ? `${name}  ${formatPercent(item.value / 100, 1)}` : name;
				},
			},
			series: [
				{
					type: "pie" as const,
					radius: ["40%", "72%"],
					center: ["35%", "50%"],
					avoidLabelOverlap: true,
					padAngle: 2,
					itemStyle: {
						borderRadius: 4,
						borderColor: "#05080f",
						borderWidth: 2,
					},
					label: { show: false },
					emphasis: {
						label: {
							show: true,
							fontSize: 14,
							fontWeight: 700,
							color: "#ffffff",
							formatter: "{b}\n{d}%",
						},
						itemStyle: {
							shadowBlur: 20,
							shadowColor: "rgba(0,0,0,0.4)",
						},
					},
					data: allocationData.map((d, i) => ({
						...d,
						itemStyle: { color: BLOCK_COLORS[i % BLOCK_COLORS.length] },
					})),
				},
			],
		} as Record<string, unknown>;
	});

	// ── Stress Horizontal Bar ────────────────────────────────
	const SCENARIO_LABELS: Record<string, string> = {
		gfc_2008: "GFC 2008",
		covid_2020: "COVID 2020",
		taper_2013: "Taper 2013",
		rate_shock_200bps: "Rate +200bps",
	};

	const SCENARIO_ORDER = ["gfc_2008", "covid_2020", "taper_2013", "rate_shock_200bps"];

	const stressOption = $derived.by(() => {
		if (stressResults.length === 0) return {} as Record<string, unknown>;

		const ordered: ConstructionStressResult[] = SCENARIO_ORDER
			.map((key) => stressResults.find((r) => r.scenario === key))
			.filter((r): r is ConstructionStressResult => r !== undefined);

		// Append user-defined scenarios not in canonical order
		for (const r of stressResults) {
			if (!SCENARIO_ORDER.includes(r.scenario)) ordered.push(r);
		}

		// Reverse for horizontal bar (bottom-to-top rendering)
		const reversed = [...ordered].reverse();
		const labels = reversed.map((r) => SCENARIO_LABELS[r.scenario] ?? r.scenario);
		const navImpacts = reversed.map((r) =>
			r.nav_impact_pct != null ? Math.round(r.nav_impact_pct * 10000) / 100 : 0,
		);
		const cvarImpacts = reversed.map((r) =>
			r.cvar_impact_pct != null ? Math.round(r.cvar_impact_pct * 10000) / 100 : 0,
		);

		return {
			backgroundColor: "transparent",
			textStyle: { fontFamily: tokens.fontFamily, fontSize: 12 },
			animation: true,
			animationDuration: 500,
			animationEasing: "cubicOut",
			animationDelay: (idx: number) => idx * 80,
			tooltip: {
				trigger: "axis" as const,
				axisPointer: { type: "shadow" as const },
				backgroundColor: tokens.tooltipBg,
				borderColor: tokens.tooltipBorder,
				borderWidth: 1,
				padding: 12,
				valueFormatter: (v: number) => formatPercent(v / 100, 2),
			},
			legend: {
				data: ["Portfolio Impact", "Worst-Case Impact"],
				bottom: 0,
				textStyle: { color: "#cbccd1", fontSize: 11 },
				itemWidth: 12,
				itemHeight: 8,
			},
			grid: {
				left: 16,
				right: 24,
				top: 12,
				bottom: 40,
				containLabel: true,
			},
			xAxis: {
				type: "value" as const,
				axisLabel: {
					formatter: (v: number) => formatPercent(v / 100, 0),
					fontSize: 10,
					color: tokens.axisLabel,
				},
				splitLine: {
					lineStyle: { color: "rgba(64,66,73,0.3)", type: "dashed" as const },
				},
			},
			yAxis: {
				type: "category" as const,
				data: labels,
				axisLabel: {
					fontSize: 12,
					fontWeight: 600,
					color: "#cbccd1",
				},
				axisTick: { show: false },
				axisLine: { show: false },
			},
			series: [
				{
					name: "Portfolio Impact",
					type: "bar" as const,
					data: navImpacts,
					barWidth: 14,
					itemStyle: {
						color: tokens.negative,
						borderRadius: [0, 3, 3, 0],
					},
				},
				{
					name: "Worst-Case Impact",
					type: "bar" as const,
					data: cvarImpacts,
					barWidth: 14,
					itemStyle: {
						color: "#f0a020",
						borderRadius: [0, 3, 3, 0],
					},
				},
			],
		} as Record<string, unknown>;
	});
</script>

<svelte:window onkeydown={handleKeydown} />

<div
	class="cro-root"
	role="dialog"
	aria-label="Construction results for {portfolioName}"
	aria-modal="true"
>
	<!-- ── Header ──────────────────────────────────────────── -->
	<header class="cro-header">
		<div class="cro-header-left">
			<h1 class="cro-title">{portfolioName}</h1>
			<span class="cro-badge">
				<CheckCircle size={14} />
				Construction Successful
			</span>
		</div>
		<button type="button" class="cro-close" onclick={onClose}>
			<X size={18} />
			<span>Close & Return to Builder</span>
		</button>
	</header>

	<!-- ── Content ─────────────────────────────────────────── -->
	<div class="cro-body">
		<!-- Row 1: KPI Strip -->
		<div class="cro-kpi-strip">
			<div class="cro-kpi">
				<span class="cro-kpi-label">Expected Return</span>
				<span class="cro-kpi-value">{kpiValue("expected_return", "pct")}</span>
			</div>
			<div class="cro-kpi">
				<span class="cro-kpi-label">Volatility</span>
				<span class="cro-kpi-value">{kpiValue("portfolio_volatility", "pct")}</span>
			</div>
			<div class="cro-kpi">
				<span class="cro-kpi-label">Risk Level</span>
				<span class="cro-kpi-value">{kpiValue("cvar_95", "pct")}</span>
			</div>
			<div class="cro-kpi">
				<span class="cro-kpi-label">Return Efficiency</span>
				<span class="cro-kpi-value">{kpiValue("sharpe_ratio", "ratio")}</span>
			</div>
		</div>

		<!-- Row 2: Charts -->
		<div class="cro-charts-row">
			<!-- Allocation Donut -->
			<div class="cro-chart-panel">
				<span class="cro-chart-label">ALLOCATION</span>
				{#if allocationData.length > 0}
					<ChartContainer
						option={allocationOption}
						height={360}
						empty={allocationData.length === 0}
						emptyMessage="No allocation data"
						ariaLabel="Portfolio allocation by asset class"
					/>
				{:else}
					<div class="cro-chart-empty">
						<span>No allocation data available</span>
					</div>
				{/if}
			</div>

			<!-- Stress Horizontal Bar -->
			<div class="cro-chart-panel">
				<span class="cro-chart-label">STRESS RESISTANCE</span>
				{#if stressResults.length > 0}
					<ChartContainer
						option={stressOption}
						height={360}
						empty={stressResults.length === 0}
						emptyMessage="No stress scenarios"
						ariaLabel="Stress scenario impact analysis"
					/>
				{:else}
					<div class="cro-chart-empty">
						<span>No stress scenarios available</span>
					</div>
				{/if}
			</div>
		</div>

		<!-- Row 3: Narrative summary -->
		{#if narrative?.headline}
			<div class="cro-narrative">
				<span class="cro-narrative-label">CONSTRUCTION SUMMARY</span>
				<p class="cro-narrative-headline">{narrative.headline}</p>
				{#if narrative.key_points && narrative.key_points.length > 0}
					<ul class="cro-narrative-points">
						{#each narrative.key_points as point}
							<li>{point}</li>
						{/each}
					</ul>
				{/if}
			</div>
		{/if}
	</div>
</div>

<style>
	/* ── Root — full-screen takeover ─────────────────────────── */
	.cro-root {
		position: fixed;
		inset: 0;
		z-index: 60;
		background: #05080f;
		display: flex;
		flex-direction: column;
		overflow: hidden;
		animation: cro-fade-in 280ms ease-out;
	}

	@keyframes cro-fade-in {
		from {
			opacity: 0;
			transform: translateY(12px);
		}
		to {
			opacity: 1;
			transform: translateY(0);
		}
	}

	/* ── Header ──────────────────────────────────────────────── */
	.cro-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 16px;
		padding: 20px 28px;
		border-bottom: 1px solid rgba(64, 66, 73, 0.3);
		flex-shrink: 0;
	}

	.cro-header-left {
		display: flex;
		align-items: center;
		gap: 16px;
		min-width: 0;
	}

	.cro-title {
		margin: 0;
		font-size: 18px;
		font-weight: 700;
		color: #ffffff;
		font-family: "Urbanist", sans-serif;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.cro-badge {
		display: inline-flex;
		align-items: center;
		gap: 6px;
		padding: 4px 12px;
		border-radius: 999px;
		background: rgba(17, 236, 121, 0.1);
		color: #11ec79;
		font-size: 12px;
		font-weight: 600;
		font-family: "Urbanist", sans-serif;
		white-space: nowrap;
	}

	.cro-close {
		display: inline-flex;
		align-items: center;
		gap: 8px;
		padding: 8px 18px;
		border: 1px solid rgba(255, 255, 255, 0.15);
		border-radius: 999px;
		background: transparent;
		color: #cbccd1;
		font-family: "Urbanist", sans-serif;
		font-size: 13px;
		font-weight: 500;
		cursor: pointer;
		transition: all 120ms ease;
		flex-shrink: 0;
	}
	.cro-close:hover {
		background: rgba(255, 255, 255, 0.05);
		color: #ffffff;
		border-color: rgba(255, 255, 255, 0.3);
	}
	.cro-close:focus-visible {
		outline: 2px solid #2d7ef7;
		outline-offset: 2px;
	}

	/* ── Body ────────────────────────────────────────────────── */
	.cro-body {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
		padding: 24px 28px;
		display: flex;
		flex-direction: column;
		gap: 24px;
	}

	/* ── KPI Strip ───────────────────────────────────────────── */
	.cro-kpi-strip {
		display: grid;
		grid-template-columns: repeat(4, 1fr);
		gap: 2px;
	}

	.cro-kpi {
		display: flex;
		flex-direction: column;
		gap: 6px;
		padding: 20px 16px;
		background: rgba(255, 255, 255, 0.02);
		border-radius: 4px;
	}

	.cro-kpi-label {
		font-size: 10px;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: #85a0bd;
		font-family: "Urbanist", sans-serif;
	}

	.cro-kpi-value {
		font-size: 24px;
		font-weight: 700;
		color: #ffffff;
		font-variant-numeric: tabular-nums;
		font-family: "Urbanist", sans-serif;
	}

	/* ── Chart panels row ────────────────────────────────────── */
	.cro-charts-row {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 16px;
	}

	.cro-chart-panel {
		display: flex;
		flex-direction: column;
		gap: 8px;
	}

	.cro-chart-label {
		font-size: 10px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: #85a0bd;
		font-family: "Urbanist", sans-serif;
		padding-left: 4px;
	}

	.cro-chart-empty {
		display: flex;
		align-items: center;
		justify-content: center;
		min-height: 360px;
		border: 1px solid rgba(64, 66, 73, 0.3);
		border-radius: 8px;
		color: #85a0bd;
		font-family: "Urbanist", sans-serif;
		font-size: 13px;
	}

	/* ── Narrative section ────────────────────────────────────── */
	.cro-narrative {
		padding: 20px;
		background: rgba(255, 255, 255, 0.02);
		border-radius: 6px;
		border: 1px solid rgba(64, 66, 73, 0.2);
	}

	.cro-narrative-label {
		display: block;
		font-size: 10px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: #85a0bd;
		font-family: "Urbanist", sans-serif;
		margin-bottom: 12px;
	}

	.cro-narrative-headline {
		margin: 0 0 12px;
		font-size: 15px;
		font-weight: 600;
		color: #ffffff;
		font-family: "Urbanist", sans-serif;
		line-height: 1.4;
	}

	.cro-narrative-points {
		margin: 0;
		padding: 0 0 0 18px;
		list-style: disc;
		display: flex;
		flex-direction: column;
		gap: 6px;
	}
	.cro-narrative-points li {
		font-size: 13px;
		color: #cbccd1;
		font-family: "Urbanist", sans-serif;
		line-height: 1.5;
	}
</style>
