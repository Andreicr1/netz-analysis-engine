<!--
  Analytics — backtest trigger, optimization, pareto frontier, correlation heatmap.
-->
<script lang="ts">
	import { DataCard, HeatmapChart, ScatterChart, PageHeader, EmptyState, Button } from "@netz/ui";
	import type { PageData } from "./$types";
	import { createClientApiClient } from "$lib/api/client";

	let { data }: { data: PageData } = $props();

	type CorrelationMatrix = {
		matrix: number[][];
		labels: string[];
	};

	let correlation = $derived(data.correlation as CorrelationMatrix | null);

	// Heatmap data
	let heatmapData = $derived(
		correlation
			? {
					matrix: correlation.matrix,
					xLabels: correlation.labels,
					yLabels: correlation.labels,
				}
			: null,
	);

	// Backtest state
	let backtestProfile = $state("moderate");
	let backtestRunning = $state(false);
	let backtestResult = $state<Record<string, unknown> | null>(null);

	const profiles = ["conservative", "moderate", "growth"];

	async function triggerBacktest() {
		backtestRunning = true;
		backtestResult = null;
		try {
			const api = createClientApiClient(async () => "dev-token");
			const result = await api.post("/analytics/backtest", {
				profile: backtestProfile,
			}) as Record<string, unknown>;
			backtestResult = result;
		} catch {
			// Error handled by api-client
		} finally {
			backtestRunning = false;
		}
	}
</script>

<div class="space-y-6 p-6">
	<PageHeader title="Analytics" />

	<!-- Backtest Trigger -->
	<div class="rounded-lg border border-[var(--netz-border)] bg-white p-5">
		<h3 class="mb-4 text-sm font-semibold text-[var(--netz-text-primary)]">Backtest</h3>
		<div class="flex items-center gap-3">
			<select
				class="rounded-md border border-[var(--netz-border)] bg-white px-3 py-1.5 text-sm"
				bind:value={backtestProfile}
			>
				{#each profiles as p (p)}
					<option value={p} class="capitalize">{p}</option>
				{/each}
			</select>
			<Button
				onclick={triggerBacktest}
				disabled={backtestRunning}
			>
				{backtestRunning ? "Running..." : "Run Backtest"}
			</Button>
		</div>
		{#if backtestResult}
			<div class="mt-4 rounded-md bg-[var(--netz-surface-alt)] p-4">
				<p class="text-sm text-[var(--netz-text-secondary)]">
					Backtest submitted. Run ID: {backtestResult.run_id ?? "—"}
				</p>
			</div>
		{/if}
	</div>

	<!-- Correlation Matrix -->
	<div class="rounded-lg border border-[var(--netz-border)] bg-white p-5">
		<h3 class="mb-4 text-sm font-semibold text-[var(--netz-text-primary)]">Block Correlation Matrix</h3>
		{#if heatmapData}
			<div class="h-96">
				<HeatmapChart
					matrix={heatmapData.matrix}
					xLabels={heatmapData.xLabels}
					yLabels={heatmapData.yLabels}
				/>
			</div>
		{:else}
			<EmptyState title="No Correlation Data" message="Correlation matrix will appear once NAV data is available." />
		{/if}
	</div>
</div>
