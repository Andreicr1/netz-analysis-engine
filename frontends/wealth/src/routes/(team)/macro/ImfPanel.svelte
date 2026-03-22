<!--
  IMF Panel — raw IMF WEO annual forecasts.
  Indicator Select dropdown, horizontal bar chart.
  Provenance: "Source: IMF WEO — Model Inference" (NOT deterministic)
-->
<script lang="ts">
	import { BarChart, EmptyState } from "@netz/ui";
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
		{ value: "IN", label: "India" },
	];

	const indicators = [
		{ value: "NGDP_RPCH", label: "GDP Growth (%)" },
		{ value: "PCPIPCH", label: "Inflation (%)" },
		{ value: "GGXCNL_NGDP", label: "Fiscal Balance (% GDP)" },
		{ value: "GGXWDG_NGDP", label: "Govt Debt (% GDP)" },
	];

	let selectedCountry = $state("US");
	let selectedIndicator = $state("NGDP_RPCH");
	let loading = $state(false);
	let error = $state<string | null>(null);
	let data = $state<{ year: number; value: number }[]>([]);

	async function fetchData() {
		loading = true;
		error = null;
		try {
			const api = createClientApiClient(getToken);
			const resp = await api.get(
				`/macro/imf?country=${selectedCountry}&indicator=${selectedIndicator}`,
			);
			data = resp.data ?? [];
		} catch (e) {
			error = e instanceof Error ? e.message : "Failed to load IMF data";
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

	let chartData = $derived(
		data.map((d) => ({ name: String(d.year), value: d.value })),
	);
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
		<EmptyState title="No Data" message="No IMF WEO data available for this selection." />
	{:else}
		<BarChart
			data={chartData}
			orientation="horizontal"
			height={280}
			loading={loading}
			empty={data.length === 0}
		/>
	{/if}

	<p class="text-xs text-(--netz-text-muted)">
		Source: IMF WEO — <span class="italic">Model Inference</span>
	</p>
</div>
