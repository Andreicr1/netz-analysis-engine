<!--
  StressTab — Zone E STRESS tab of the Builder results panel.

  Displays the 4 parametric stress scenario results from the last
  construction run. Terminal-styled table with sanitized scenario names.
  No custom shock form (deferred to Session 3+).
-->
<script lang="ts">
	import { workspace } from "$wealth/state/portfolio-workspace.svelte";
	import type { ConstructionStressResult } from "$wealth/state/portfolio-workspace.svelte";
	import { formatPercent } from "@investintell/ui";

	/** Sanitized scenario names per Appendix D. */
	const SCENARIO_LABELS: Record<string, string> = {
		gfc_2008: "Global Financial Crisis",
		covid_2020: "COVID",
		taper_2013: "Taper Tantrum",
		rate_shock_200bps: "Rate Shock",
	};

	const run = $derived(workspace.constructionRun);
	const stressResults = $derived(run?.stress_results ?? []);

	// ── PR-A5 B.4 — in-flight scenario grid (before run loads) ──
	const inFlight = $derived(workspace.runPhase === "stress");
	const backtestMetrics = $derived(workspace.buildMetrics.backtest);
	const liveScenarioResults = $derived.by<Record<string, unknown> | null>(() => {
		if (!backtestMetrics) return null;
		const raw = backtestMetrics.scenario_results;
		if (raw && typeof raw === "object") return raw as Record<string, unknown>;
		return null;
	});
	const STRESS_KEYS: ReadonlyArray<string> = [
		"gfc_2008",
		"covid_2020",
		"taper_2013",
		"rate_shock_200bps",
	];
	function isScenarioDone(key: string): boolean {
		return !!liveScenarioResults && liveScenarioResults[key] != null;
	}

	interface StressRow {
		scenario: string;
		label: string;
		navImpact: number | null;
		worstBlock: string | null;
		bestBlock: string | null;
		severity: "high" | "medium" | "low" | "none";
	}

	const rows = $derived.by<StressRow[]>(() => {
		return stressResults.map((r: ConstructionStressResult) => {
			const label = SCENARIO_LABELS[r.scenario] ?? r.scenario;
			const navImpact = r.nav_impact_pct;
			const blocks = r.per_block_impact ?? {};
			const blockEntries = Object.entries(blocks);

			let worstBlock: string | null = null;
			let bestBlock: string | null = null;
			if (blockEntries.length > 0) {
				const sorted = [...blockEntries].sort((a, b) => a[1] - b[1]);
				const worst = sorted[0];
				const best = sorted[sorted.length - 1];
				if (worst) worstBlock = worst[0];
				if (best) bestBlock = best[0];
			}

			let severity: StressRow["severity"] = "none";
			if (navImpact != null) {
				const abs = Math.abs(navImpact);
				if (abs > 0.05) severity = "high";
				else if (abs > 0.02) severity = "medium";
				else severity = "low";
			}

			return { scenario: r.scenario, label, navImpact, worstBlock, bestBlock, severity };
		});
	});
</script>

<svelte:boundary>
	<div class="st-root">
		{#if !run && inFlight}
			<!-- PR-A5 B.4 — live scenario grid while BACKTESTING runs. -->
			<section class="st-live" aria-label="Cenários em execução">
				<header class="st-live-header">Executando 4 cenários de stress…</header>
				<div class="st-live-grid">
					{#each STRESS_KEYS as key (key)}
						{@const done = isScenarioDone(key)}
						<div class="st-live-cell" class:st-live-cell--done={done}>
							<span
								class="st-live-icon"
								class:st-live-icon--done={done}
								aria-hidden="true"
							>{done ? "\u2713" : "\u25CF"}</span>
							<span class="st-live-label">{SCENARIO_LABELS[key]}</span>
						</div>
					{/each}
				</div>
			</section>
		{:else if !run}
			<div class="st-empty">Run construction to see stress analysis</div>
		{:else if rows.length === 0}
			<div class="st-empty">No active stress scenarios in this run</div>
		{:else}
			<table class="st-table">
				<thead>
					<tr>
						<th scope="col">Scenario</th>
						<th scope="col" class="st-num">Portfolio Impact</th>
						<th scope="col">Worst Block</th>
						<th scope="col">Best Block</th>
					</tr>
				</thead>
				<tbody>
					{#each rows as row (row.scenario)}
						<tr>
							<td class="st-scenario">{row.label}</td>
							<td class="st-num st-impact st-impact--{row.severity}">
								{row.navImpact != null ? formatPercent(row.navImpact, 1) : "\u2014"}
							</td>
							<td class="st-block">{row.worstBlock ?? "\u2014"}</td>
							<td class="st-block">{row.bestBlock ?? "\u2014"}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		{/if}
	</div>

	{#snippet failed(err: unknown)}
		<div class="st-empty">Stress panel failed to render</div>
	{/snippet}
</svelte:boundary>

<style>
	.st-root {
		font-family: var(--terminal-font-mono);
		color: var(--terminal-fg-secondary);
	}

	.st-empty {
		display: flex;
		align-items: center;
		justify-content: center;
		min-height: 200px;
		color: var(--terminal-fg-muted);
		font-size: var(--terminal-text-11);
		text-transform: uppercase;
		letter-spacing: var(--terminal-tracking-caps);
	}

	.st-table {
		width: 100%;
		border-collapse: collapse;
		font-size: var(--terminal-text-11);
	}

	.st-table th,
	.st-table td {
		padding: var(--terminal-space-2) var(--terminal-space-3);
		border-bottom: var(--terminal-border-hairline);
		text-align: left;
		vertical-align: middle;
	}

	.st-table thead th {
		font-size: var(--terminal-text-10);
		font-weight: 700;
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		color: var(--terminal-fg-tertiary);
	}

	.st-scenario {
		font-weight: 600;
		color: var(--terminal-fg-primary);
	}

	.st-num {
		text-align: right;
		font-variant-numeric: tabular-nums;
	}

	.st-block {
		font-size: var(--terminal-text-10);
		color: var(--terminal-fg-tertiary);
	}

	.st-impact--high {
		color: var(--terminal-status-error);
	}

	.st-impact--medium {
		color: var(--terminal-status-warn);
	}

	.st-impact--low {
		color: var(--terminal-status-success);
	}

	.st-impact--none {
		color: var(--terminal-fg-muted);
	}

	/* ── PR-A5 B.4 — in-flight scenario grid ──────────── */

	.st-live {
		display: flex;
		flex-direction: column;
		gap: var(--terminal-space-3);
		padding: var(--terminal-space-4);
	}

	.st-live-header {
		font-size: var(--terminal-text-11);
		font-weight: 600;
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		color: var(--terminal-fg-tertiary);
		animation: st-live-pulse 1.5s ease-in-out infinite;
	}

	.st-live-grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: var(--terminal-space-2);
	}

	.st-live-cell {
		display: flex;
		align-items: center;
		gap: var(--terminal-space-2);
		padding: var(--terminal-space-2) var(--terminal-space-3);
		border: 1px solid var(--terminal-fg-muted);
		background: var(--terminal-bg-panel-raised);
		font-size: var(--terminal-text-11);
	}

	.st-live-cell--done {
		border-color: var(--terminal-status-success);
	}

	.st-live-icon {
		display: inline-flex;
		width: 16px;
		font-size: var(--terminal-text-12);
		color: var(--terminal-fg-muted);
	}

	.st-live-icon--done {
		color: var(--terminal-status-success);
	}

	.st-live-label {
		font-weight: 600;
		color: var(--terminal-fg-primary);
	}

	@keyframes st-live-pulse {
		0%, 100% { opacity: 1; }
		50% { opacity: 0.5; }
	}
</style>
