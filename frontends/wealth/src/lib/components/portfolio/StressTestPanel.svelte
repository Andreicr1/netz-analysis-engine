<!--
  StressTestPanel — Parametric stress scenario inputs + bar chart results.
  Inputs: Equity Shock (%), Rates Shock (bps), Credit Spread (bps).
  Results: portfolio NAV impact + per-block breakdown via POST /stress-test API.
  Design: dark premium (Figma One X).
-->
<script lang="ts">
	import { Button } from "@investintell/ui/components/ui/button";
	import { Input } from "@investintell/ui/components/ui/input";
	import { ChartContainer } from "@investintell/ui/charts";
	import { globalChartOptions } from "@investintell/ui/charts/echarts-setup";
	import { EmptyState, formatPercent } from "@investintell/ui";
	import { blockLabel } from "$wealth/constants/blocks";
	import Loader2 from "lucide-svelte/icons/loader-2";
	import { workspace } from "$wealth/state/portfolio-workspace.svelte";

	// ── Shock inputs ──────────────────────────────────────────────────────
	let equityShock = $state(-20);
	let ratesShock = $state(200);
	let creditShock = $state(150);

	function handleRun() {
		workspace.runStressTest({
			equity: equityShock,
			rates: ratesShock,
			credit: creditShock,
		});
	}

	// ECharts series colors must be resolved hex (CSS vars don't work
	// inside the option object). Read from CSS at mount + on theme change.
	let successColor = $state("#22c55e");
	let dangerColor = $state("#ef4444");
	let textMuted = $state("#94a3b8");
	let textSecondary = $state("#cbccd1");
	let borderColor = $state("rgba(64,66,73,0.3)");

	function readChartTokens() {
		if (typeof document === "undefined") return;
		const cs = getComputedStyle(document.documentElement);
		const get = (n: string, fallback: string) => cs.getPropertyValue(n).trim() || fallback;
		successColor = get("--ii-success", "#22c55e");
		dangerColor = get("--ii-danger", "#ef4444");
		textMuted = get("--ii-text-muted", "#94a3b8");
		textSecondary = get("--ii-text-secondary", "#cbccd1");
		borderColor = get("--ii-border", "rgba(64,66,73,0.3)");
	}

	$effect(() => {
		readChartTokens();
		if (typeof document === "undefined") return;
		const obs = new MutationObserver(() => readChartTokens());
		obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
		return () => obs.disconnect();
	});

	// ── Block impacts chart ───────────────────────────────────────────────
	// Note: a single-bar "Portfolio NAV Impact" chart used to live above
	// this one. It was deleted as chart-junk — the same value is shown in
	// the KPI strip below, so the chart added zero information.
	let blockChartOption = $derived.by(() => {
		const stress = workspace.localStress;
		if (!stress || !stress.blockImpacts) return {};

		const entries = Object.entries(stress.blockImpacts).sort((a, b) => a[1] - b[1]);
		const categories = entries.map(([k]) => blockLabel(k));
		const values = entries.map(([, v]) => v);

		return {
			...globalChartOptions,
			toolbox: { show: false },
			grid: { left: 130, right: 40, top: 8, bottom: 24, containLabel: false },
			tooltip: {
				...globalChartOptions.tooltip,
				trigger: "axis" as const,
				axisPointer: { type: "shadow" },
				formatter(params: unknown) {
					const list = Array.isArray(params) ? params : [params];
					const p = list[0] as { name?: string; value?: number };
					if (p.value == null) return "";
					const sign = p.value > 0 ? "+" : "";
					return `<strong>${p.name}</strong><br/>Impact: ${sign}${formatPercent(p.value / 100, 2)}`;
				},
			},
			xAxis: {
				type: "value" as const,
				axisLabel: { formatter: "{value}%", fontSize: 10, color: textMuted },
				splitLine: { lineStyle: { type: "dashed" as const, color: borderColor } },
			},
			yAxis: {
				type: "category" as const,
				data: categories,
				inverse: true,
				axisLabel: { fontSize: 11, fontWeight: 500, color: textSecondary },
				axisTick: { show: false },
				axisLine: { show: false },
			},
			series: [
				{
					name: "Block Impact",
					type: "bar" as const,
					// Flat fills, no gradient, no shadow, no borderRadius —
					// institutional bar charts don't decorate.
					data: values.map((v) => ({
						value: Math.round(v * 100) / 100,
						itemStyle: { color: v >= 0 ? successColor : dangerColor },
					})),
					barWidth: "45%",
					label: {
						show: true,
						position: "right" as const,
						fontSize: 10,
						fontWeight: 600,
						color: textSecondary,
						formatter: (p: { value: number }) => {
							const sign = p.value > 0 ? "+" : "";
							return `${sign}${formatPercent(p.value / 100, 1)}`;
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

	let hasResult = $derived(workspace.localStress !== null);
</script>

{#if !workspace.portfolio}
	<div class="p-6">
		<EmptyState
			title="No portfolio selected"
			message="Select a model portfolio to run stress scenarios."
		/>
	</div>
{:else if !workspace.portfolio.fund_selection_schema}
	<div class="p-6">
		<EmptyState
			title="Portfolio not constructed"
			message="Run Construct first to generate fund weights before stress testing."
		/>
	</div>
{:else}
	<div class="flex flex-col h-full">
		<!-- Input section -->
		<div class="stress-input-section">
			<div class="stress-header">
				<span class="stress-title">Parametric Stress Scenario</span>
			</div>

			<div class="stress-input-grid">
				<div class="stress-input-col">
					<label class="stress-label" for="equity-shock">Equity Shock (%)</label>
					<Input id="equity-shock" type="number" step={5} bind:value={equityShock} />
				</div>
				<div class="stress-input-col">
					<label class="stress-label" for="rates-shock">Rates Shock (bps)</label>
					<Input id="rates-shock" type="number" step={25} bind:value={ratesShock} />
				</div>
				<div class="stress-input-col">
					<label class="stress-label" for="credit-shock">Credit Spread (bps)</label>
					<Input id="credit-shock" type="number" step={25} bind:value={creditShock} />
				</div>
			</div>

			<Button size="sm" onclick={handleRun} disabled={workspace.isStressing}>
				{#if workspace.isStressing}
					<Loader2 class="mr-1.5 h-4 w-4 animate-spin" />
					Running…
				{:else}
					Run Scenario
				{/if}
			</Button>
		</div>

		<!-- Results section -->
		{#if hasResult}
			<div class="stress-results">
				<div class="stress-chart-block">
					<span class="stress-label">Impact by Allocation Block</span>
					<ChartContainer
						option={blockChartOption}
						height={Math.max(120, Object.keys(workspace.localStress!.blockImpacts).length * 28)}
						empty={!hasResult}
						ariaLabel="Stress test impact by allocation block"
					/>
				</div>

				<!-- KPI summary strip -->
				<div class="stress-kpi-strip">
					<div class="stress-kpi">
						<span class="stress-kpi-label">NAV Impact</span>
						<span class="stress-kpi-value tabular-nums" class:stress-kpi-value--bad={workspace.localStress!.portfolioDrop <= 0} class:stress-kpi-value--good={workspace.localStress!.portfolioDrop > 0}>
							{workspace.localStress!.portfolioDrop > 0 ? "+" : ""}{formatPercent(workspace.localStress!.portfolioDrop / 100)}
						</span>
					</div>
					{#if workspace.localStress!.cvarStressed != null}
						<div class="stress-kpi">
							<span class="stress-kpi-label">Stressed Tail Loss</span>
							<span class="stress-kpi-value stress-kpi-value--bad tabular-nums">
								{formatPercent(workspace.localStress!.cvarStressed)}
							</span>
						</div>
					{/if}
					{#if workspace.localStress!.worstBlock}
						<div class="stress-kpi">
							<span class="stress-kpi-label">Worst Block</span>
							<span class="stress-kpi-value stress-kpi-value--bad">
								{blockLabel(workspace.localStress!.worstBlock)}
							</span>
						</div>
					{/if}
					{#if workspace.localStress!.bestBlock}
						<div class="stress-kpi">
							<span class="stress-kpi-label">Best Block</span>
							<span class="stress-kpi-value stress-kpi-value--good">
								{blockLabel(workspace.localStress!.bestBlock)}
							</span>
						</div>
					{/if}
				</div>
			</div>
		{:else if !workspace.isStressing}
			<div class="stress-empty">
				<p>Configure shocks above and click <strong>Run Scenario</strong> to see projected impacts.</p>
			</div>
		{/if}
	</div>

<style>
	.stress-input-section {
		padding: 20px 24px;
		border-bottom: 1px solid var(--ii-border-subtle);
	}

	.stress-header {
		display: flex;
		align-items: center;
		gap: 12px;
		margin-bottom: 20px;
	}

	.stress-title {
		font-size: 16px;
		font-weight: 700;
		color: var(--ii-text-primary);
		letter-spacing: -0.02em;
	}

	.stress-input-grid {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: 24px;
		margin-bottom: 20px;
	}

	.stress-input-col {
		display: flex;
		flex-direction: column;
		gap: 8px;
	}

	.stress-label {
		font-size: 11px;
		font-weight: 600;
		color: var(--ii-text-muted);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.stress-results {
		display: flex;
		flex-direction: column;
		gap: 20px;
		padding: 20px;
		flex: 1;
		overflow-y: auto;
	}

	.stress-chart-block {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}

	.stress-kpi-strip {
		display: flex;
		gap: 24px;
		padding: 12px 20px;
		background: color-mix(in srgb, var(--ii-text-primary) 3%, transparent);
		border-radius: 12px;
	}

	.stress-kpi {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.stress-kpi-label {
		font-size: 11px;
		color: var(--ii-text-muted);
		font-weight: 500;
	}

	.stress-kpi-value {
		font-size: 15px;
		font-weight: 700;
	}

	.stress-kpi-value--bad  { color: var(--ii-danger); }
	.stress-kpi-value--good { color: var(--ii-success); }

	.stress-empty {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 12px;
		flex: 1;
		padding: 48px 0;
		text-align: center;
		color: var(--ii-text-muted);
		font-size: 13px;
	}

	.stress-empty strong {
		color: var(--ii-text-secondary);
	}
</style>
{/if}
