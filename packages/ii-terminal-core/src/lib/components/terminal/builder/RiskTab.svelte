<!--
  RiskTab — Zone E RISK tab of the Builder results panel.

  Two sections:
    A) CVaR contribution — 48px horizontal stacked bar
    B) Factor exposure — horizontal bar chart

  Uses TerminalChart with raw EChartsOption (the stacked bar and
  horizontal bar layouts need custom grid/tooltip not covered by
  createTerminalChartOptions).
-->
<script lang="ts">
	import { workspace } from "$wealth/state/portfolio-workspace.svelte";
	import { formatNumber, readTerminalTokens, createTerminalChartOptions } from "@investintell/ui";
	import TerminalChart from "$wealth/components/terminal/charts/TerminalChart.svelte";
	import type { EChartsOption } from "echarts";
	import {
		translateKappa,
		translateShrinkageLambda,
		translateRegime,
		translateFactorCoverage,
		translateRSquaredMedian,
		type TranslatedMetric,
	} from "$wealth/util/metric-translators";

	const run = $derived(workspace.constructionRun);
	const funds = $derived(workspace.funds);

	// ── PR-A5 B.3 — in-flight chip strip from buildMetrics ──────
	const factorMetrics = $derived(workspace.buildMetrics.factor);
	const shrinkageMetrics = $derived(workspace.buildMetrics.shrinkage);
	const inFlightPhase = $derived(
		workspace.runPhase === "factor_modeling" || workspace.runPhase === "shrinkage",
	);

	type Chip = TranslatedMetric & { rawTitle?: string };

	const chips = $derived.by<Chip[]>(() => {
		const out: Chip[] = [];
		if (factorMetrics) {
			const effRaw = factorMetrics.k_factors_effective;
			const totRaw = factorMetrics.k_factors;
			if (typeof effRaw === "number" && typeof totRaw === "number") {
				out.push({
					...translateFactorCoverage(effRaw, totRaw),
					rawTitle: `k_factors_effective=${effRaw}, k_factors=${totRaw}`,
				});
			}
			const regime = factorMetrics.regime;
			if (typeof regime === "string") {
				out.push({ ...translateRegime(regime), rawTitle: `regime=${regime}` });
			}
			const kappa = factorMetrics.kappa;
			if (typeof kappa === "number") {
				out.push({
					...translateKappa(kappa),
					rawTitle: `kappa=${formatNumber(kappa, 0)}`,
				});
			}
			const r2 = factorMetrics.r_squared_p50;
			if (typeof r2 === "number") {
				out.push({
					...translateRSquaredMedian(r2),
					rawTitle: `r_squared_p50=${formatNumber(r2, 3)}`,
				});
			}
		}
		if (shrinkageMetrics) {
			const lambda = shrinkageMetrics.shrinkage_lambda;
			if (typeof lambda === "number") {
				out.push({
					...translateShrinkageLambda(lambda),
					rawTitle: `shrinkage_lambda=${formatNumber(lambda, 4)}`,
				});
			}
		}
		return out;
	});

	const showChips = $derived(chips.length > 0);

	/** Sanitized factor category labels (PC1/PC2/PC3 → Market/Style/Sector). */
	const FACTOR_LABELS: Record<string, string> = {
		PC1: "Market Factor",
		PC2: "Style Factor",
		PC3: "Sector Factor",
	};

	// ── Section A: CVaR Contribution ────────────────────────

	const cvarContributions = $derived.by<Array<{ name: string; value: number }>>(() => {
		if (!run?.ex_ante_metrics || !run.weights_proposed) return [];
		const totalCvar = run.ex_ante_metrics.cvar_95;
		if (totalCvar == null || totalCvar === 0) return [];

		const entries: Array<{ name: string; value: number }> = [];
		for (const fund of funds) {
			const w = run.weights_proposed[fund.instrument_id] ?? 0;
			if (w > 0.001) {
				entries.push({
					name: fund.fund_name || fund.instrument_id,
					value: Math.abs(w * totalCvar),
				});
			}
		}
		return entries.sort((a, b) => b.value - a.value);
	});

	const hasCvar = $derived(cvarContributions.length > 0);

	const cvarOption = $derived.by<EChartsOption>(() => {
		if (!hasCvar) return {};
		const tk = readTerminalTokens();
		const total = cvarContributions.reduce((sum, c) => sum + c.value, 0);

		const base = createTerminalChartOptions({
			slot: "secondary",
			disableAnimation: true,
			showXAxisLabels: false,
			showYAxisLabels: false,
			xAxis: { type: "value" as const, show: false, max: total },
			yAxis: { type: "category" as const, show: false, data: ["Tail Loss"] },
			series: cvarContributions.map((c, i) => ({
				type: "bar" as const,
				stack: "cvar",
				barWidth: "100%",
				data: [c.value],
				name: c.name,
				itemStyle: { color: tk.dataviz[i % tk.dataviz.length] },
			})),
		});
		return { ...base, grid: { left: 0, right: 0, top: 0, bottom: 0 } };
	});

	// ── Section B: Factor Exposure ──────────────────────────

	const factorExposures = $derived.by<Array<{ label: string; value: number }>>(() => {
		const fe = run?.factor_exposure;
		if (!fe || typeof fe !== "object") return [];

		const inner = (fe as Record<string, unknown>).exposures ?? fe;
		if (!inner || typeof inner !== "object") return [];

		return Object.entries(inner as Record<string, unknown>)
			.filter(([, v]) => typeof v === "number")
			.map(([key, v]) => ({
				label: FACTOR_LABELS[key] ?? key,
				value: v as number,
			}))
			.sort((a, b) => Math.abs(b.value) - Math.abs(a.value));
	});

	const hasFactors = $derived(factorExposures.length > 0);

	const factorOption = $derived.by<EChartsOption>(() => {
		if (!hasFactors) return {};
		const tk = readTerminalTokens();

		const labels = factorExposures.map((e) => e.label);
		const values = factorExposures.map((e) => Math.round(e.value * 1000) / 1000);

		const base = createTerminalChartOptions({
			slot: "secondary",
			disableAnimation: true,
			xAxis: {
				type: "value" as const,
				axisLabel: {
					formatter: (v: number) => formatNumber(v, 1),
				},
			},
			yAxis: {
				type: "category" as const,
				data: labels,
				inverse: true,
				axisLabel: { fontWeight: 600 as const },
				axisTick: { show: false },
				axisLine: { show: false },
			},
			series: [
				{
					type: "bar" as const,
					barWidth: "55%",
					data: values.map((v) => ({
						value: v,
						itemStyle: {
							color: v >= 0 ? tk.accentCyan : tk.accentAmber,
						},
					})),
					label: {
						show: true,
						position: "right" as const,
						fontSize: tk.text10,
						fontWeight: 600 as const,
						color: tk.fgPrimary,
					},
					markLine: {
						silent: true,
						symbol: "none" as const,
						data: [{ xAxis: 0 }],
						lineStyle: { color: tk.fgTertiary, type: "solid" as const, width: 1 },
						label: { show: false },
					},
				},
			],
		});

		return { ...base, grid: { left: 130, right: 50, top: 12, bottom: 24 } };
	});

	const hasData = $derived(hasCvar || hasFactors);
</script>

<svelte:boundary>
	<div class="rt-root">
		{#if showChips}
			<!-- PR-A5 B.3 — phase-aware chip strip, pinned above the charts. -->
			<section class="rt-chips" aria-label="Risk model diagnostics">
				{#each chips as chip, i (i)}
					<span class="rt-chip rt-chip--{chip.tone}" title={chip.rawTitle ?? ""}>
						{chip.label}
					</span>
				{/each}
			</section>
		{/if}

		{#if !run}
			{#if inFlightPhase}
				<div class="rt-skeleton" aria-busy="true">
					<div class="rt-skeleton-line rt-skeleton-line--wide"></div>
					<div class="rt-skeleton-line"></div>
					<div class="rt-skeleton-line rt-skeleton-line--narrow"></div>
				</div>
			{:else}
				<div class="rt-empty">Run construction to see risk analysis</div>
			{/if}
		{:else if !hasData}
			<div class="rt-empty">No risk data in this construction run</div>
		{:else}
			{#if hasCvar}
				<section class="rt-section">
					<header class="rt-section-header">
						<span class="rt-kicker">Risk Contribution</span>
						<span class="rt-subtitle">Tail Loss (95% confidence) by position</span>
					</header>
					<TerminalChart option={cvarOption} height={48} ariaLabel="Tail loss contribution stacked bar" />
				</section>
			{/if}

			{#if hasFactors}
				<section class="rt-section">
					<header class="rt-section-header">
						<span class="rt-kicker">Factor Decomposition</span>
						<span class="rt-subtitle">Portfolio factor exposures</span>
					</header>
					<TerminalChart option={factorOption} height={200} ariaLabel="Factor exposure horizontal bar" />
				</section>
			{/if}
		{/if}
	</div>

	{#snippet failed(err: unknown)}
		<div class="rt-empty">Risk panel failed to render</div>
	{/snippet}
</svelte:boundary>

<style>
	.rt-root {
		display: flex;
		flex-direction: column;
		gap: var(--terminal-space-4);
		font-family: var(--terminal-font-mono);
		color: var(--terminal-fg-secondary);
	}

	.rt-empty {
		display: flex;
		align-items: center;
		justify-content: center;
		min-height: 200px;
		color: var(--terminal-fg-muted);
		font-size: var(--terminal-text-11);
		text-transform: uppercase;
		letter-spacing: var(--terminal-tracking-caps);
	}

	.rt-section {
		display: flex;
		flex-direction: column;
		gap: var(--terminal-space-2);
	}

	.rt-section-header {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.rt-kicker {
		font-size: var(--terminal-text-10);
		font-weight: 700;
		letter-spacing: var(--terminal-tracking-caps);
		text-transform: uppercase;
		color: var(--terminal-fg-tertiary);
	}

	.rt-subtitle {
		font-size: var(--terminal-text-11);
		color: var(--terminal-fg-muted);
	}

	/* ── PR-A5 B.3 — diagnostics chip strip ─────────────── */

	.rt-chips {
		display: flex;
		flex-wrap: wrap;
		gap: var(--terminal-space-2);
		padding-bottom: var(--terminal-space-2);
		border-bottom: 1px dashed var(--terminal-fg-muted);
	}

	.rt-chip {
		display: inline-flex;
		align-items: center;
		padding: 4px 8px;
		font-size: var(--terminal-text-10);
		font-weight: 600;
		letter-spacing: 0.02em;
		border: 1px solid var(--terminal-fg-muted);
		border-radius: 2px;
		background: var(--terminal-bg-panel-raised);
		font-family: var(--terminal-font-mono);
		white-space: nowrap;
	}

	.rt-chip--success {
		border-color: var(--terminal-status-success);
		color: var(--terminal-fg-primary);
	}

	.rt-chip--neutral {
		border-color: var(--terminal-fg-muted);
		color: var(--terminal-fg-secondary);
	}

	.rt-chip--warning {
		border-color: var(--terminal-status-warn);
		color: var(--terminal-status-warn);
	}

	.rt-chip--danger {
		border-color: var(--terminal-status-error);
		color: var(--terminal-status-error);
	}

	/* ── PR-A5 B.3/B.5 — shimmer skeleton ─────────────── */

	.rt-skeleton {
		display: flex;
		flex-direction: column;
		gap: var(--terminal-space-2);
		padding: var(--terminal-space-4) 0;
	}

	.rt-skeleton-line {
		height: 12px;
		background: linear-gradient(
			90deg,
			var(--terminal-bg-panel-raised) 0%,
			var(--terminal-fg-muted) 50%,
			var(--terminal-bg-panel-raised) 100%
		);
		background-size: 200% 100%;
		animation: rt-shimmer 1.4s linear infinite;
		opacity: 0.4;
	}

	.rt-skeleton-line--wide {
		width: 80%;
	}

	.rt-skeleton-line--narrow {
		width: 45%;
	}

	@keyframes rt-shimmer {
		0% { background-position: 200% 0; }
		100% { background-position: -200% 0; }
	}
</style>
