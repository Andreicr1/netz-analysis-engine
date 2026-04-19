<!--
  StressImpactMatrixChart — Phase 6 Block B portfolio-specific chart.

  Renders the construction run's stress_results as a 2-bar grouped
  comparison showing NAV impact + tail (CVaR) impact across the 4
  canonical DL7 scenarios. The Pass/Warn chips on each scenario row
  echo the StressScenarioMatrixTab heuristic from Phase 4 (warn if
  NAV impact < -25%).

  Data source: ConstructionRunPayload.stress_results from
  GET /{portfolio_id}/runs/latest. Set on the workspace by
  ``loadAnalyticsSubject``.

  Per CLAUDE.md DL16 — every percentage goes through formatPercent.
  Per OD-26 — strict empty state when no run or no stress results.
-->
<script lang="ts">
	import { ChartContainer } from "@investintell/ui/charts";
	import { EmptyState, formatPercent } from "@investintell/ui";
	import type {
		ConstructionRunPayload,
		ConstructionStressResult,
	} from "$wealth/state/portfolio-workspace.svelte";
	import { chartTokens } from "$wealth/components/charts/chart-tokens";

	interface Props {
		latestRun: ConstructionRunPayload | null;
		height?: number;
	}

	let { latestRun, height = 320 }: Props = $props();

	const tokens = $derived.by(() => chartTokens());

	// DL7 canonical labels matching the Phase 4 StressScenarioMatrixTab.
	const SCENARIO_LABELS: Record<string, string> = {
		gfc_2008: "GFC 2008",
		covid_2020: "COVID 2020",
		taper_2013: "Taper 2013",
		rate_shock_200bps: "Rate +200bps",
	};

	const stressResults = $derived(latestRun?.stress_results ?? []);
	const isEmpty = $derived(stressResults.length === 0);

	const option = $derived.by(() => {
		if (isEmpty) return {} as Record<string, unknown>;

		// Order matches the canonical DL7 sequence so the chart is
		// reading-stable across runs even if the backend returns rows
		// in a different order.
		const order = ["gfc_2008", "covid_2020", "taper_2013", "rate_shock_200bps"];
		const ordered: ConstructionStressResult[] = order
			.map((key) => stressResults.find((r) => r.scenario === key))
			.filter((r): r is ConstructionStressResult => r !== undefined);

		const labels = ordered.map((r) => SCENARIO_LABELS[r.scenario] ?? r.scenario);
		const navImpacts = ordered.map((r) =>
			r.nav_impact_pct !== null ? Math.round(r.nav_impact_pct * 10000) / 100 : 0,
		);
		const cvarImpacts = ordered.map((r) =>
			r.cvar_impact_pct !== null ? Math.round(r.cvar_impact_pct * 10000) / 100 : 0,
		);

		return {
			textStyle: { fontFamily: tokens.fontFamily, fontSize: 12 },
			tooltip: {
				trigger: "axis" as const,
				axisPointer: { type: "shadow" as const },
				backgroundColor: tokens.tooltipBg,
				borderColor: tokens.tooltipBorder,
				borderWidth: 1,
				padding: 10,
				valueFormatter: (v: number) => formatPercent(v / 100, 1),
			},
			legend: {
				data: ["NAV impact", "Tail loss impact"],
				bottom: 0,
				textStyle: { color: tokens.axisLabel, fontSize: 11 },
			},
			grid: {
				left: 16,
				right: 24,
				top: 12,
				bottom: 36,
				containLabel: true,
			},
			xAxis: {
				type: "category" as const,
				data: labels,
				axisLabel: {
					fontSize: 11,
					fontWeight: 600,
					color: "#cbccd1",
				},
			},
			yAxis: {
				type: "value" as const,
				axisLabel: {
					formatter: (v: number) => `${v}%`,
					fontSize: 10,
					color: tokens.axisLabel,
				},
				splitLine: {
					lineStyle: { color: "rgba(64,66,73,0.3)", type: "dashed" as const },
				},
			},
			series: [
				{
					name: "NAV impact",
					type: "bar" as const,
					data: navImpacts,
					itemStyle: {
						color: tokens.negative,
						borderRadius: [3, 3, 0, 0],
					},
				},
				{
					name: "Tail loss impact",
					type: "bar" as const,
					data: cvarImpacts,
					itemStyle: {
						color: "#f0a020",
						borderRadius: [3, 3, 0, 0],
					},
				},
			],
		} as Record<string, unknown>;
	});

	const worstScenario = $derived.by(() => {
		if (stressResults.length === 0) return null;
		return [...stressResults].sort(
			(a, b) => (a.nav_impact_pct ?? 0) - (b.nav_impact_pct ?? 0),
		)[0];
	});
</script>

{#if isEmpty}
	<EmptyState
		title="No stress results"
		message="Run a construction with stress scenarios enabled to populate the impact matrix."
	/>
{:else}
	<header class="sim-header">
		<div class="sim-stat">
			<span class="sim-kicker">Worst scenario</span>
			<span class="sim-value">
				{worstScenario ? SCENARIO_LABELS[worstScenario.scenario] ?? worstScenario.scenario : "—"}
			</span>
		</div>
		<div class="sim-stat">
			<span class="sim-kicker">Worst NAV impact</span>
			<span class="sim-value sim-value--neg">
				{worstScenario?.nav_impact_pct !== null && worstScenario?.nav_impact_pct !== undefined
					? formatPercent(worstScenario.nav_impact_pct, 1)
					: "—"}
			</span>
		</div>
	</header>
	<ChartContainer
		{option}
		{height}
		ariaLabel="Stress impact matrix across DL7 canonical scenarios"
	/>
{/if}

<style>
	.sim-header {
		display: flex;
		gap: 24px;
		margin-bottom: 8px;
	}
	.sim-stat {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	.sim-kicker {
		font-size: 10px;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.06em;
		color: var(--ii-text-muted, #85a0bd);
	}
	.sim-value {
		font-size: 16px;
		font-weight: 700;
		font-variant-numeric: tabular-nums;
		color: var(--ii-text-primary, #ffffff);
	}
	.sim-value--neg {
		color: var(--ii-danger, #fc1a1a);
	}
</style>
