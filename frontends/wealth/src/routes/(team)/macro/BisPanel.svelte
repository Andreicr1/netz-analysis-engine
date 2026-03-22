<!--
  BIS Panel — raw BIS SDMX time series.
  Country selector, multi-series line chart.
  Provenance: "Source: BIS SDMX — Deterministic Metric"
-->
<script lang="ts">
	import { SectionCard, TimeSeriesChart, EmptyState, formatNumber } from "@netz/ui";
	import { createClientApiClient } from "$lib/api/client";
	import { getContext } from "svelte";

	const getToken = getContext<() => Promise<string>>("netz:getToken");

	const countries = [
		{ value: "US", label: "United States" },
		{ value: "DE", label: "Germany" },
		{ value: "GB", label: "United Kingdom" },
		{ value: "JP", label: "Japan" },
		{ value: "CN", label: "China" },
		{ value: "BR", label: "Brazil" },
		{ value: "FR", label: "France" },
	];

	const indicators = [
		{ value: "CREDIT_GAP", label: "Credit-to-GDP Gap" },
		{ value: "DSR", label: "Debt Service Ratio" },
		{ value: "SPP", label: "Property Prices" },
	];

	let selectedCountry = $state("US");
	let selectedIndicator = $state("CREDIT_GAP");
	let loading = $state(false);
	let error = $state<string | null>(null);
	let data = $state<{ period: string; value: number }[]>([]);

	async function fetchData() {
		loading = true;
		error = null;
		try {
			const api = createClientApiClient(getToken);
			const resp = await api.get(
				`/macro/bis?country=${selectedCountry}&indicator=${selectedIndicator}`,
			);
			data = resp.data ?? [];
		} catch (e) {
			error = e instanceof Error ? e.message : "Failed to load BIS data";
			data = [];
		} finally {
			loading = false;
		}
	}

	$effect(() => {
		selectedCountry;
		selectedIndicator;
		fetchData();
	});

	let chartSeries = $derived([
		{
			name: `${selectedCountry} — ${selectedIndicator}`,
			data: data.map((d) => [d.period, d.value] as [string, number]),
		},
	]);
</script>

<div class="space-y-3">
	<div class="flex items-center gap-3">
		<select
			class="rounded-md border border-(--netz-border) bg-(--netz-surface) px-2 py-1.5 text-sm text-(--netz-text-primary)"
			bind:value={selectedCountry}
		>
			{#each countries as c (c.value)}
				<option value={c.value}>{c.label}</option>
			{/each}
		</select>
		<select
			class="rounded-md border border-(--netz-border) bg-(--netz-surface) px-2 py-1.5 text-sm text-(--netz-text-primary)"
			bind:value={selectedIndicator}
		>
			{#each indicators as ind (ind.value)}
				<option value={ind.value}>{ind.label}</option>
			{/each}
		</select>
	</div>

	{#if error}
		<div class="rounded-md border border-(--netz-status-error) bg-(--netz-status-error)/10 p-3 text-sm text-(--netz-status-error)">
			{error}
		</div>
	{:else if data.length === 0 && !loading}
		<EmptyState title="No Data" message="No BIS data available for this selection." />
	{:else}
		<TimeSeriesChart
			series={chartSeries}
			yAxisLabel={selectedIndicator}
			height={280}
			loading={loading}
			empty={data.length === 0}
		/>
	{/if}

	<p class="text-xs text-(--netz-text-muted)">
		Source: BIS SDMX — Deterministic Metric
	</p>
</div>
