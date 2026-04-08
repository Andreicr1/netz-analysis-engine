<!--
  StressScenarioMatrixTab — the "Matrix" tab of the StressScenarioPanel.

  Renders all 4 canonical DL7 stress scenarios as a single grid showing
  NAV impact, CVaR impact, and a Pass/Warn chip. Reads from the
  persisted ``portfolio_construction_runs.stress_results`` via the
  workspace store.

  When no run has stress results yet, renders a strict empty state
  (OD-26) — the panel never fabricates values.
-->
<script lang="ts">
	import { workspace } from "$lib/state/portfolio-workspace.svelte";
	import { EmptyState, formatPercent } from "@investintell/ui";
	import type { ConstructionStressResult } from "$lib/state/portfolio-workspace.svelte";
	import type { StressScenarioId } from "$lib/types/portfolio-calibration";

	interface Meta {
		id: StressScenarioId;
		label: string;
		description: string;
	}

	// OD-22 + DL7 — canonical scenario metadata mirroring the backend
	// ``_STRESS_CATALOG_META`` dict. Future sprint can fetch this from
	// GET /portfolio/stress-test/scenarios (Phase 3 Task 3.5) but the
	// static mirror is cheaper and avoids a second fetch on every render.
	const SCENARIO_META: readonly Meta[] = [
		{
			id: "gfc_2008",
			label: "Global Financial Crisis (2008)",
			description:
				"Subprime collapse and Lehman failure. Equity -38% to -50%, HY credit -26%, Treasuries +6%.",
		},
		{
			id: "covid_2020",
			label: "COVID-19 Pandemic (Q1 2020)",
			description:
				"Rapid global selloff. Equity -30% to -40%, HY credit -12%, Treasuries +8%.",
		},
		{
			id: "taper_2013",
			label: "Taper Tantrum (2013)",
			description:
				"Fed signalled tapering of QE. Bonds and EM equities sold off simultaneously. Gold -28%.",
		},
		{
			id: "rate_shock_200bps",
			label: "Rate Shock (+200 bps)",
			description:
				"Parallel 200bp shift in the yield curve. Long-duration bonds -12%, equity -8% to -12%.",
		},
	];

	const run = $derived(workspace.constructionRun);
	const stressResults = $derived(run?.stress_results ?? []);

	const rows = $derived.by(() => {
		return SCENARIO_META.map((meta) => {
			const found = stressResults.find(
				(r: ConstructionStressResult) => r.scenario === meta.id,
			);
			return { meta, result: found ?? null };
		});
	});

	function passChip(result: ConstructionStressResult | null): "pass" | "warn" | "na" {
		if (!result) return "na";
		const nav = result.nav_impact_pct;
		if (nav === null || nav === undefined) return "na";
		// Institutional heuristic: a scenario that produces worse than
		// -25% NAV impact flags warn; otherwise pass. Phase 10 jargon
		// table will tune the threshold from ConfigService.
		return nav < -0.25 ? "warn" : "pass";
	}
</script>

{#if !run}
	<EmptyState
		title="No stress results yet"
		message="Run a construction to compute the scenario matrix."
	/>
{:else if stressResults.length === 0}
	<EmptyState
		title="No active scenarios"
		message="Select at least one scenario in the calibration panel and re-run construction."
	/>
{:else}
	<table class="ssm-table">
		<thead>
			<tr>
				<th scope="col">Scenario</th>
				<th scope="col" class="ssm-num">NAV impact</th>
				<th scope="col" class="ssm-num">Tail impact</th>
				<th scope="col">Pass/Warn</th>
			</tr>
		</thead>
		<tbody>
			{#each rows as row (row.meta.id)}
				{@const chip = passChip(row.result)}
				<tr>
					<th scope="row" class="ssm-scenario">
						<span class="ssm-label">{row.meta.label}</span>
						<span class="ssm-description">{row.meta.description}</span>
					</th>
					<td class="ssm-num">
						{row.result && row.result.nav_impact_pct !== null
							? formatPercent(row.result.nav_impact_pct, 1)
							: "—"}
					</td>
					<td class="ssm-num">
						{row.result && row.result.cvar_impact_pct !== null
							? formatPercent(row.result.cvar_impact_pct, 1)
							: "—"}
					</td>
					<td>
						<span class="ssm-chip" data-chip={chip}>
							{chip === "pass" ? "Pass" : chip === "warn" ? "Warn" : "—"}
						</span>
					</td>
				</tr>
			{/each}
		</tbody>
	</table>
{/if}

<style>
	.ssm-table {
		width: 100%;
		border-collapse: collapse;
		font-family: "Urbanist", system-ui, sans-serif;
		font-size: 12px;
	}
	.ssm-table th,
	.ssm-table td {
		padding: 10px 12px;
		border-bottom: 1px solid var(--ii-border-subtle, rgba(64, 66, 73, 0.4));
		text-align: left;
		vertical-align: top;
	}
	.ssm-table thead th {
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.04em;
		text-transform: uppercase;
		color: var(--ii-text-muted, #85a0bd);
	}
	.ssm-scenario {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}
	.ssm-label {
		font-size: 12px;
		font-weight: 600;
		color: var(--ii-text-primary, #ffffff);
	}
	.ssm-description {
		font-size: 11px;
		color: var(--ii-text-muted, #85a0bd);
		line-height: 1.45;
	}
	.ssm-num {
		text-align: right;
		font-variant-numeric: tabular-nums;
		color: var(--ii-text-primary, #ffffff);
	}
	.ssm-chip {
		display: inline-flex;
		align-items: center;
		padding: 2px 8px;
		border-radius: 999px;
		font-size: 10px;
		font-weight: 700;
		letter-spacing: 0.02em;
		text-transform: uppercase;
	}
	.ssm-chip[data-chip="pass"] {
		background: rgba(63, 185, 80, 0.12);
		color: var(--ii-success, #3fb950);
	}
	.ssm-chip[data-chip="warn"] {
		background: rgba(240, 160, 32, 0.14);
		color: var(--ii-warning, #f0a020);
	}
	.ssm-chip[data-chip="na"] {
		background: rgba(255, 255, 255, 0.06);
		color: var(--ii-text-muted, #85a0bd);
	}
</style>
