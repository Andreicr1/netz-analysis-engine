<!--
  StressTestPanel — Parametric stress scenario inputs + bar chart results.
  Inputs: Equity Shock (%), Rates Shock (bps), Credit Spread (bps).
  Results: portfolio NAV impact + per-block breakdown via POST /stress-test API.
-->
<script lang="ts">
	import { Button } from "@investintell/ui/components/ui/button";
	import { Input } from "@investintell/ui/components/ui/input";
	import { ChartContainer } from "@investintell/ui/charts";
	import { globalChartOptions } from "@investintell/ui/charts/echarts-setup";
	import { EmptyState, formatPercent } from "@investintell/ui";
	import { blockLabel } from "$lib/constants/blocks";
	import Activity from "lucide-svelte/icons/activity";
	import Zap from "lucide-svelte/icons/zap";
	import Loader2 from "lucide-svelte/icons/loader-2";
	import { workspace } from "$lib/state/portfolio-workspace.svelte";

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

	// ── Portfolio impact chart ────────────────────────────────────────────
	let chartOption = $derived.by(() => {
		const stress = workspace.localStress;
		if (!stress) return {};

		const value = stress.portfolioDrop;

		return {
			...globalChartOptions,
			toolbox: { show: false },
			grid: { left: 100, right: 40, top: 24, bottom: 24, containLabel: false },
			tooltip: {
				...globalChartOptions.tooltip,
				trigger: "axis" as const,
				formatter(params: unknown) {
					const list = Array.isArray(params) ? params : [params];
					const p = list[0] as { name?: string; value?: number; marker?: string };
					if (p.value == null) return "";
					return `<strong>${p.name}</strong><br/>${p.marker ?? ""} Impact: ${p.value > 0 ? "+" : ""}${p.value.toFixed(2)}%`;
				},
			},
			xAxis: {
				type: "value" as const,
				axisLabel: { formatter: "{value}%", fontSize: 11 },
				splitLine: { lineStyle: { type: "dashed" as const } },
			},
			yAxis: {
				type: "category" as const,
				data: ["Portfolio NAV"],
				inverse: true,
				axisLabel: { fontSize: 12, fontWeight: 600 },
				axisTick: { show: false },
				axisLine: { show: false },
			},
			series: [
				{
					name: "Impact",
					type: "bar" as const,
					data: [
						{
							value,
							itemStyle: {
								color: value <= 0 ? "#fc1a1a" : "#11ec79",
								borderRadius: value >= 0 ? [0, 4, 4, 0] : [4, 0, 0, 4],
							},
						},
					],
					barWidth: "50%",
					label: {
						show: true,
						position: "right" as const,
						fontSize: 11,
						fontWeight: 600,
						formatter: (p: { value: number }) => `${p.value > 0 ? "+" : ""}${p.value.toFixed(2)}%`,
					},
					markLine: {
						silent: true,
						symbol: "none" as const,
						data: [{ xAxis: 0 }],
						lineStyle: { color: "var(--ii-text-muted)", type: "solid" as const, width: 1 },
						label: { show: false },
					},
				},
			],
		};
	});

	// ── Block impacts chart ───────────────────────────────────────────────
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
				formatter(params: unknown) {
					const list = Array.isArray(params) ? params : [params];
					const p = list[0] as { name?: string; value?: number };
					if (p.value == null) return "";
					return `<strong>${p.name}</strong><br/>Impact: ${p.value > 0 ? "+" : ""}${p.value.toFixed(2)}%`;
				},
			},
			xAxis: {
				type: "value" as const,
				axisLabel: { formatter: "{value}%", fontSize: 10 },
				splitLine: { lineStyle: { type: "dashed" as const } },
			},
			yAxis: {
				type: "category" as const,
				data: categories,
				inverse: true,
				axisLabel: { fontSize: 11 },
				axisTick: { show: false },
				axisLine: { show: false },
			},
			series: [
				{
					name: "Block Impact",
					type: "bar" as const,
					data: values.map((v) => ({
						value: Math.round(v * 100) / 100,
						itemStyle: {
							color: v <= 0 ? "#fc1a1a" : "#11ec79",
							borderRadius: v >= 0 ? [0, 3, 3, 0] : [3, 0, 0, 3],
						},
					})),
					barWidth: "55%",
					label: {
						show: true,
						position: "right" as const,
						fontSize: 10,
						formatter: (p: { value: number }) => `${p.value > 0 ? "+" : ""}${p.value.toFixed(1)}%`,
					},
					markLine: {
						silent: true,
						symbol: "none" as const,
						data: [{ xAxis: 0 }],
						lineStyle: { color: "var(--ii-text-muted)", type: "solid" as const, width: 1 },
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
	<div class="stress-panel">
		<!-- Input section -->
		<div class="stress-inputs">
			<div class="stress-header">
				<Zap class="h-4 w-4" style="color: var(--ii-warning);" />
				<span class="stress-title">Parametric Stress Scenario</span>
			</div>

			<div class="shock-grid">
				<div class="shock-field">
					<label class="shock-label" for="equity-shock">Equity Shock (%)</label>
					<Input
						id="equity-shock"
						type="number"
						step={5}
						bind:value={equityShock}
						class="shock-input"
					/>
				</div>
				<div class="shock-field">
					<label class="shock-label" for="rates-shock">Rates Shock (bps)</label>
					<Input
						id="rates-shock"
						type="number"
						step={25}
						bind:value={ratesShock}
						class="shock-input"
					/>
				</div>
				<div class="shock-field">
					<label class="shock-label" for="credit-shock">Credit Spread (bps)</label>
					<Input
						id="credit-shock"
						type="number"
						step={25}
						bind:value={creditShock}
						class="shock-input"
					/>
				</div>
			</div>

			<Button
				size="sm"
				onclick={handleRun}
				disabled={workspace.isStressing}
				class="run-btn"
			>
				{#if workspace.isStressing}
					<Loader2 class="mr-1.5 h-4 w-4 animate-spin" />
					Running…
				{:else}
					<Activity class="mr-1.5 h-4 w-4" />
					Run Scenario
				{/if}
			</Button>
		</div>

		<!-- Results section -->
		{#if hasResult}
			<div class="stress-results">
				<div class="result-section">
					<span class="result-label">Portfolio NAV Impact</span>
					<ChartContainer
						option={chartOption}
						height={80}
						empty={!hasResult}
						ariaLabel="Stress test portfolio NAV impact"
					/>
				</div>

				<div class="result-section">
					<span class="result-label">Impact by Allocation Block</span>
					<ChartContainer
						option={blockChartOption}
						height={Math.max(120, Object.keys(workspace.localStress!.blockImpacts).length * 28)}
						empty={!hasResult}
						ariaLabel="Stress test impact by allocation block"
					/>
				</div>

				<!-- KPI summary strip -->
				<div class="kpi-strip">
					<div class="kpi-item">
						<span class="kpi-label">NAV Impact</span>
						<span class="kpi-value" class:kpi-negative={workspace.localStress!.portfolioDrop <= 0}>
							{workspace.localStress!.portfolioDrop > 0 ? "+" : ""}{formatPercent(workspace.localStress!.portfolioDrop / 100)}
						</span>
					</div>
					{#if workspace.localStress!.cvarStressed != null}
						<div class="kpi-item">
							<span class="kpi-label">CVaR Stressed</span>
							<span class="kpi-value kpi-negative">
								{formatPercent(workspace.localStress!.cvarStressed)}
							</span>
						</div>
					{/if}
					{#if workspace.localStress!.worstBlock}
						<div class="kpi-item">
							<span class="kpi-label">Worst Block</span>
							<span class="kpi-value kpi-negative">
								{blockLabel(workspace.localStress!.worstBlock)}
							</span>
						</div>
					{/if}
					{#if workspace.localStress!.bestBlock}
						<div class="kpi-item">
							<span class="kpi-label">Best Block</span>
							<span class="kpi-value kpi-positive">
								{blockLabel(workspace.localStress!.bestBlock)}
							</span>
						</div>
					{/if}
				</div>
			</div>
		{:else if !workspace.isStressing}
			<div class="stress-empty">
				<Activity class="h-8 w-8" style="color: var(--ii-text-muted); opacity: 0.4;" />
				<p>Configure shocks above and click <strong>Run Scenario</strong> to see projected impacts.</p>
			</div>
		{/if}
	</div>
{/if}

<style>
	.stress-panel {
		display: flex;
		flex-direction: column;
		gap: 0;
		height: 100%;
	}

	.stress-inputs {
		padding: 16px;
		border-bottom: 1px solid var(--ii-border-subtle);
	}

	.stress-header {
		display: flex;
		align-items: center;
		gap: 6px;
		margin-bottom: 12px;
	}

	.stress-title {
		font-size: var(--ii-text-body, 0.9375rem);
		font-weight: 700;
		color: var(--ii-text-primary);
	}

	.shock-grid {
		display: grid;
		grid-template-columns: 1fr 1fr 1fr;
		gap: 12px;
		margin-bottom: 12px;
	}

	.shock-field {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}

	.shock-label {
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 600;
		color: var(--ii-text-muted);
	}

	.stress-results {
		display: flex;
		flex-direction: column;
		gap: 16px;
		padding: 16px;
		flex: 1;
		overflow-y: auto;
	}

	.result-section {
		display: flex;
		flex-direction: column;
		gap: 4px;
	}

	.result-label {
		font-size: var(--ii-text-label, 0.75rem);
		font-weight: 600;
		color: var(--ii-text-muted);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}

	.kpi-strip {
		display: flex;
		gap: 24px;
		padding: 12px 16px;
		background: var(--ii-surface-alt);
		border-radius: var(--ii-radius-md, 9px);
	}

	.kpi-item {
		display: flex;
		flex-direction: column;
		gap: 2px;
	}

	.kpi-label {
		font-size: var(--ii-text-label, 0.75rem);
		color: var(--ii-text-muted);
		font-weight: 500;
	}

	.kpi-value {
		font-size: var(--ii-text-body, 0.9375rem);
		font-weight: 700;
		font-variant-numeric: tabular-nums;
		color: var(--ii-text-primary);
	}

	.kpi-positive {
		color: var(--ii-success);
	}

	.kpi-negative {
		color: var(--ii-danger);
	}

	.stress-empty {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 12px;
		flex: 1;
		padding: 40px 24px;
		text-align: center;
		color: var(--ii-text-muted);
		font-size: var(--ii-text-small, 0.8125rem);
	}
</style>
