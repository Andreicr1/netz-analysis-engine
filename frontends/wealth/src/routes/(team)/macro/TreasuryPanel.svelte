<!--
  Treasury Panel — raw US Treasury time series.
  Yield curve chart with category X axis, markArea for inverted regions.
  Provenance: "Source: US Treasury — Deterministic Metric"
-->
<script lang="ts">
	import { ChartContainer } from "@netz/ui/charts";
	import { EmptyState, formatNumber } from "@netz/ui";
	import { createClientApiClient } from "$lib/api/client";
	import { getContext } from "svelte";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	const seriesOptions = [
		{ value: "YIELD_CURVE", label: "Yield Curve (Latest)" },
		{ value: "10Y_RATE", label: "10-Year Rate" },
		{ value: "2Y_RATE", label: "2-Year Rate" },
		{ value: "30Y_RATE", label: "30-Year Rate" },
		{ value: "FED_FUNDS", label: "Fed Funds Rate" },
	];

	let selectedSeries = $state("10Y_RATE");
	let loading = $state(false);
	let error = $state<string | null>(null);
	let data = $state<{ obs_date: string; value: number }[]>([]);

	async function fetchData() {
		loading = true;
		error = null;
		try {
			const api = createClientApiClient(getToken);
			const resp = await api.get(`/macro/treasury?series=${selectedSeries}`);
			data = resp.data ?? [];
		} catch (e) {
			error = e instanceof Error ? e.message : "Failed to load Treasury data";
			data = [];
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		selectedSeries;
		fetchData();
	});

	let chartOption = $derived.by(() => {
		const dates = data.map((d) => d.obs_date);
		const values = data.map((d) => d.value);

		// Detect inverted regions (value < 0 for spread series)
		const markAreas: { name: string; xAxis: string }[][] = [];
		let invertStart: string | null = null;
		for (let i = 0; i < values.length; i++) {
			if (values[i] < 0 && invertStart === null) {
				invertStart = dates[i];
			} else if (values[i] >= 0 && invertStart !== null) {
				markAreas.push([
					{ name: "Inverted", xAxis: invertStart },
					{ name: "", xAxis: dates[i] },
				]);
				invertStart = null;
			}
		}
		if (invertStart !== null && dates.length > 0) {
			markAreas.push([
				{ name: "Inverted", xAxis: invertStart },
				{ name: "", xAxis: dates[dates.length - 1] },
			]);
		}

		return {
			tooltip: { trigger: "axis" },
			grid: { left: 60, right: 20, top: 20, bottom: 30 },
			xAxis: {
				type: "time",
				data: dates,
				axisLabel: { fontSize: 11 },
			},
			yAxis: {
				type: "value",
				name: "Rate (%)",
				nameLocation: "middle",
				nameGap: 45,
				axisLabel: { fontSize: 11 },
			},
			series: [
				{
					name: selectedSeries,
					type: "line",
					data: data.map((d) => [d.obs_date, d.value]),
					smooth: true,
					showSymbol: false,
					areaStyle: { opacity: 0.1 },
					markArea:
						markAreas.length > 0
							? {
									silent: true,
									itemStyle: { color: "rgba(255, 77, 79, 0.08)" },
									data: markAreas,
								}
							: undefined,
				},
			],
		} as Record<string, unknown>;
	});
</script>

<div class="space-y-3">
	<div class="flex items-center gap-3">
		<select
			class="rounded-md border border-(--netz-border) bg-(--netz-surface) px-2 py-1.5 text-sm text-(--netz-text-primary)"
			bind:value={selectedSeries}
		>
			{#each seriesOptions as s (s.value)}
				<option value={s.value}>{s.label}</option>
			{/each}
		</select>
	</div>

	{#if error}
		<div class="rounded-md border border-(--netz-status-error) bg-(--netz-status-error)/10 p-3 text-sm text-(--netz-status-error)">
			{error}
		</div>
	{:else if data.length === 0 && !loading}
		<EmptyState title="No Data" message="No Treasury data available for this series." />
	{:else}
		<ChartContainer
			option={chartOption}
			height={280}
			{loading}
			empty={data.length === 0}
		/>
	{/if}

	<p class="text-xs text-(--netz-text-muted)">
		Source: US Treasury — Deterministic Metric
	</p>
</div>
