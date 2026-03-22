<!--
  OFR Panel — raw OFR hedge fund data.
  Area chart for AUM, bar chart for strategy, gauge for repo stress.
  Provenance: "Source: OFR — Deterministic Metric (Survey-Based)"
-->
<script lang="ts">
	import { ChartContainer } from "@netz/ui/charts";
	import { EmptyState, GaugeChart, formatNumber } from "@netz/ui";
	import { createClientApiClient } from "$lib/api/client";
	import { getContext } from "svelte";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	const metrics = [
		{ value: "HF_AUM", label: "Hedge Fund AUM" },
		{ value: "HF_LEVERAGE", label: "Leverage Ratio" },
		{ value: "HF_REPO_STRESS", label: "Repo Stress Index" },
		{ value: "HF_STRATEGY_EQUITY", label: "Strategy: Equity" },
		{ value: "HF_STRATEGY_CREDIT", label: "Strategy: Credit" },
		{ value: "HF_STRATEGY_MACRO", label: "Strategy: Macro" },
	];

	let selectedMetric = $state("HF_AUM");
	let loading = $state(false);
	let error = $state<string | null>(null);
	let data = $state<{ obs_date: string; value: number }[]>([]);

	async function fetchData() {
		loading = true;
		error = null;
		try {
			const api = createClientApiClient(getToken);
			const resp = await api.get<{ data?: { obs_date: string; value: number }[] }>(`/macro/ofr?metric=${selectedMetric}`);
			data = resp.data ?? [];
		} catch (e) {
			error = e instanceof Error ? e.message : "Failed to load OFR data";
			data = [];
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		selectedMetric;
		fetchData();
	});

	let isStressMetric = $derived(selectedMetric === "HF_REPO_STRESS");
	let latestValue = $derived(data.length > 0 ? data[data.length - 1]!.value : 0);

	let areaChartOption = $derived.by(() => {
		return {
			tooltip: { trigger: "axis" },
			grid: { left: 60, right: 20, top: 20, bottom: 30 },
			xAxis: {
				type: "time",
				axisLabel: { fontSize: 11 },
			},
			yAxis: {
				type: "value",
				nameLocation: "middle",
				nameGap: 45,
				axisLabel: { fontSize: 11 },
			},
			series: [
				{
					name: selectedMetric,
					type: "line",
					data: data.map((d) => [d.obs_date, d.value]),
					smooth: true,
					showSymbol: false,
					areaStyle: { opacity: 0.2 },
				},
			],
		} as Record<string, unknown>;
	});
</script>

<div class="space-y-3">
	<div class="flex items-center gap-3">
		<select
			class="rounded-md border border-(--netz-border) bg-(--netz-surface) px-2 py-1.5 text-sm text-(--netz-text-primary)"
			bind:value={selectedMetric}
		>
			{#each metrics as m (m.value)}
				<option value={m.value}>{m.label}</option>
			{/each}
		</select>
	</div>

	{#if error}
		<div class="rounded-md border border-(--netz-status-error) bg-(--netz-status-error)/10 p-3 text-sm text-(--netz-status-error)">
			{error}
		</div>
	{:else if data.length === 0 && !loading}
		<EmptyState title="No Data" message="No OFR data available for this metric." />
	{:else if isStressMetric}
		<div class="flex items-center justify-center">
			<GaugeChart
				value={latestValue}
				min={0}
				max={100}
				label="Repo Stress"
				height={260}
				thresholds={[
					{ value: 30, color: "#52c41a" },
					{ value: 60, color: "#faad14" },
					{ value: 100, color: "#ff4d4f" },
				]}
				{loading}
			/>
		</div>
		{#if data.length > 1}
			<ChartContainer
				option={areaChartOption}
				height={200}
				{loading}
				empty={data.length === 0}
			/>
		{/if}
	{:else}
		<ChartContainer
			option={areaChartOption}
			height={280}
			{loading}
			empty={data.length === 0}
		/>
	{/if}

	<p class="text-xs text-(--netz-text-muted)">
		Source: OFR — Deterministic Metric (Survey-Based)
	</p>
</div>
