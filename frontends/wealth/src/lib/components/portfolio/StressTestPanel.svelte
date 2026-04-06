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
	import { blockLabel } from "$lib/constants/blocks";
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
				axisPointer: { type: 'shadow' },
				formatter(params: unknown) {
					const list = Array.isArray(params) ? params : [params];
					const p = list[0] as { name?: string; value?: number; marker?: string };
					if (p.value == null) return "";
					return `<strong>${p.name}</strong><br/>${p.marker ?? ""} Impact: ${p.value > 0 ? "+" : ""}${p.value.toFixed(2)}%`;
				},
			},
			xAxis: {
				type: "value" as const,
				axisLabel: { formatter: "{value}%", fontSize: 10, color: '#85a0bd' },
				splitLine: { lineStyle: { type: "dashed" as const, color: 'rgba(64,66,73,0.3)' } },
			},
			yAxis: {
				type: "category" as const,
				data: ["Portfolio NAV"],
				inverse: true,
				axisLabel: { fontSize: 11, fontWeight: 600, color: '#cbccd1' },
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
								color: value >= 0
									? { type: 'linear', x: 0, y: 0, x2: 1, y2: 0, colorStops: [{offset: 0, color: '#09a552'}, {offset: 1, color: '#11ec79'}] }
									: { type: 'linear', x: 0, y: 0, x2: 1, y2: 0, colorStops: [{offset: 0, color: '#fc1a1a'}, {offset: 1, color: '#a30c0c'}] },
								borderRadius: value >= 0 ? [0, 6, 6, 0] : [6, 0, 0, 6],
								shadowBlur: 8,
								shadowColor: value >= 0 ? 'rgba(17,236,121,0.2)' : 'rgba(252,26,26,0.2)'
							},
						},
					],
					barWidth: "40%",
					label: {
						show: true,
						position: "right" as const,
						fontSize: 10,
						fontWeight: 600,
						color: '#ffffff',
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
				axisPointer: { type: 'shadow' },
				formatter(params: unknown) {
					const list = Array.isArray(params) ? params : [params];
					const p = list[0] as { name?: string; value?: number };
					if (p.value == null) return "";
					return `<strong>${p.name}</strong><br/>Impact: ${p.value > 0 ? "+" : ""}${p.value.toFixed(2)}%`;
				},
			},
			xAxis: {
				type: "value" as const,
				axisLabel: { formatter: "{value}%", fontSize: 10, color: '#85a0bd' },
				splitLine: { lineStyle: { type: "dashed" as const, color: 'rgba(64,66,73,0.3)' } },
			},
			yAxis: {
				type: "category" as const,
				data: categories,
				inverse: true,
				axisLabel: { fontSize: 11, fontWeight: 500, color: '#cbccd1' },
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
							color: v >= 0
									? { type: 'linear', x: 0, y: 0, x2: 1, y2: 0, colorStops: [{offset: 0, color: '#09a552'}, {offset: 1, color: '#11ec79'}] }
									: { type: 'linear', x: 0, y: 0, x2: 1, y2: 0, colorStops: [{offset: 0, color: '#fc1a1a'}, {offset: 1, color: '#a30c0c'}] },
							borderRadius: v >= 0 ? [0, 4, 4, 0] : [4, 0, 0, 4],
							shadowBlur: 8,
							shadowColor: v >= 0 ? 'rgba(17,236,121,0.2)' : 'rgba(252,26,26,0.2)'
						},
					})),
					barWidth: "45%",
					label: {
						show: true,
						position: "right" as const,
						fontSize: 10,
						fontWeight: 600,
						color: '#ffffff',
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
	<div class="flex flex-col h-full">
		<!-- Input section -->
		<div class="px-6 py-5 border-b border-[#404249]/30">
			<!-- Header -->
			<div class="flex items-center gap-3 mb-5">
				<span class="text-[16px] font-bold text-white tracking-tight">Parametric Stress Scenario</span>
			</div>

			<div class="grid grid-cols-3 gap-6 mb-5">
				<div class="flex flex-col gap-2">
					<label class="text-[11px] font-semibold text-[#85a0bd] uppercase tracking-wide" for="equity-shock">Equity Shock (%)</label>
					<Input id="equity-shock" type="number" step={5} bind:value={equityShock} class="bg-[#141519] border-[#404249]" />
				</div>
				<div class="flex flex-col gap-2">
					<label class="text-[11px] font-semibold text-[#85a0bd] uppercase tracking-wide" for="rates-shock">Rates Shock (bps)</label>
					<Input id="rates-shock" type="number" step={25} bind:value={ratesShock} class="bg-[#141519] border-[#404249]" />
				</div>
				<div class="flex flex-col gap-2">
					<label class="text-[11px] font-semibold text-[#85a0bd] uppercase tracking-wide" for="credit-shock">Credit Spread (bps)</label>
					<Input id="credit-shock" type="number" step={25} bind:value={creditShock} class="bg-[#141519] border-[#404249]" />
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
			<div class="flex flex-col gap-5 p-5 flex-1 overflow-y-auto">
				<div class="flex flex-col gap-1">
					<span class="text-[11px] font-semibold text-[#85a0bd] uppercase tracking-[0.04em]">Portfolio NAV Impact</span>
					<ChartContainer
						option={chartOption}
						height={80}
						empty={!hasResult}
						ariaLabel="Stress test portfolio NAV impact"
					/>
				</div>

				<div class="flex flex-col gap-1">
					<span class="text-[11px] font-semibold text-[#85a0bd] uppercase tracking-[0.04em]">Impact by Allocation Block</span>
					<ChartContainer
						option={blockChartOption}
						height={Math.max(120, Object.keys(workspace.localStress!.blockImpacts).length * 28)}
						empty={!hasResult}
						ariaLabel="Stress test impact by allocation block"
					/>
				</div>

				<!-- KPI summary strip -->
				<div class="flex gap-6 px-5 py-3 bg-white/[0.03] rounded-[12px]">
					<div class="flex flex-col gap-0.5">
						<span class="text-[11px] text-[#85a0bd] font-medium">NAV Impact</span>
						<span class="text-[15px] font-bold tabular-nums {workspace.localStress!.portfolioDrop <= 0 ? 'text-[#fc1a1a]' : 'text-[#11ec79]'}">
							{workspace.localStress!.portfolioDrop > 0 ? "+" : ""}{formatPercent(workspace.localStress!.portfolioDrop / 100)}
						</span>
					</div>
					{#if workspace.localStress!.cvarStressed != null}
						<div class="flex flex-col gap-0.5">
							<span class="text-[11px] text-[#85a0bd] font-medium">CVaR Stressed</span>
							<span class="text-[15px] font-bold tabular-nums text-[#fc1a1a]">
								{formatPercent(workspace.localStress!.cvarStressed)}
							</span>
						</div>
					{/if}
					{#if workspace.localStress!.worstBlock}
						<div class="flex flex-col gap-0.5">
							<span class="text-[11px] text-[#85a0bd] font-medium">Worst Block</span>
							<span class="text-[15px] font-bold text-[#fc1a1a]">
								{blockLabel(workspace.localStress!.worstBlock)}
							</span>
						</div>
					{/if}
					{#if workspace.localStress!.bestBlock}
						<div class="flex flex-col gap-0.5">
							<span class="text-[11px] text-[#85a0bd] font-medium">Best Block</span>
							<span class="text-[15px] font-bold text-[#11ec79]">
								{blockLabel(workspace.localStress!.bestBlock)}
							</span>
						</div>
					{/if}
				</div>
			</div>
		{:else if !workspace.isStressing}
			<div class="flex flex-col items-center justify-center gap-3 flex-1 py-12 text-center">
				<p class="text-[13px] text-[#85a0bd]">Configure shocks above and click <strong class="text-[#cbccd1]">Run Scenario</strong> to see projected impacts.</p>
			</div>
		{/if}
	</div>
{/if}
