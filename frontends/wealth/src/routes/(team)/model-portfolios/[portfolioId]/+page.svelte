<!--
  Model Portfolio Detail — composition, track record, backtest + stress results.
-->
<script lang="ts">
	import { DataCard, StatusBadge, TimeSeriesChart, BarChart, PageHeader, EmptyState } from "@netz/ui";
	import type { PageData } from "./$types";

	let { data }: { data: PageData } = $props();

	type ModelPortfolio = {
		id: string;
		profile: string;
		display_name: string;
		description: string | null;
		benchmark_composite: string | null;
		inception_date: string | null;
		inception_nav: number;
		status: string;
		fund_selection_schema: Record<string, unknown> | null;
	};

	type TrackRecord = {
		backtest: {
			equity_curve: [string, number][];
			annual_return: number | null;
			annual_volatility: number | null;
			sharpe_ratio: number | null;
			max_drawdown: number | null;
		} | null;
		stress: {
			scenarios: { name: string; impact: number }[];
		} | null;
	};

	let portfolio = $derived(data.portfolio as ModelPortfolio | null);
	let trackRecord = $derived(data.trackRecord as TrackRecord | null);

	// Chart data
	let equityCurveSeries = $derived(
		trackRecord?.backtest?.equity_curve
			? [{ name: portfolio?.display_name ?? "Portfolio", data: trackRecord.backtest.equity_curve }]
			: [],
	);

	let stressData = $derived(
		trackRecord?.stress?.scenarios?.map((s) => ({ name: s.name, value: s.impact * 100 })) ?? [],
	);

	function fmt(v: number | null | undefined, decimals = 2): string {
		return v != null ? v.toFixed(decimals) : "—";
	}

	function fmtPct(v: number | null | undefined): string {
		if (v == null) return "—";
		return `${(v * 100).toFixed(2)}%`;
	}
</script>

<div class="space-y-6 p-6">
	{#if portfolio}
		<PageHeader title={portfolio.display_name}>
			{#snippet actions()}
				<div class="flex items-center gap-2">
					<StatusBadge status={portfolio.status} />
					<span class="text-sm text-[var(--netz-text-muted)] capitalize">{portfolio.profile}</span>
				</div>
			{/snippet}
		</PageHeader>

		<!-- Portfolio Info -->
		<div class="grid gap-4 md:grid-cols-4">
			<DataCard label="Profile" value={portfolio.profile} trend="flat" />
			<DataCard label="Benchmark" value={portfolio.benchmark_composite ?? "—"} trend="flat" />
			<DataCard label="Inception" value={portfolio.inception_date ?? "—"} trend="flat" />
			<DataCard label="Inception NAV" value={portfolio.inception_nav.toFixed(2)} trend="flat" />
		</div>

		{#if portfolio.description}
			<div class="rounded-lg border border-[var(--netz-border)] bg-[var(--netz-surface-elevated)] p-4">
				<p class="text-sm text-[var(--netz-text-secondary)]">{portfolio.description}</p>
			</div>
		{/if}

		<!-- Backtest Equity Curve -->
		<div class="rounded-lg border border-[var(--netz-border)] bg-[var(--netz-surface-elevated)] p-5">
			<h3 class="mb-4 text-sm font-semibold text-[var(--netz-text-primary)]">Backtest Equity Curve</h3>
			{#if equityCurveSeries.length > 0 && equityCurveSeries[0]!.data.length > 0}
				<div class="h-80">
					<TimeSeriesChart
						series={equityCurveSeries}
						yAxisLabel="NAV"
						area={true}
					/>
				</div>
			{:else}
				<EmptyState title="No Backtest Data" message="Run a backtest to see the equity curve." />
			{/if}
		</div>

		<!-- Backtest Metrics -->
		{#if trackRecord?.backtest}
			<div class="grid gap-4 md:grid-cols-4">
				<DataCard label="Annual Return" value={fmtPct(trackRecord.backtest.annual_return)} trend={trackRecord.backtest.annual_return != null && trackRecord.backtest.annual_return >= 0 ? "up" : "down"} />
				<DataCard label="Volatility" value={fmtPct(trackRecord.backtest.annual_volatility)} trend="flat" />
				<DataCard label="Sharpe" value={fmt(trackRecord.backtest.sharpe_ratio)} trend="flat" />
				<DataCard label="Max Drawdown" value={fmtPct(trackRecord.backtest.max_drawdown)} trend="flat" />
			</div>
		{/if}

		<!-- Stress Scenarios -->
		{#if stressData.length > 0}
			<div class="rounded-lg border border-[var(--netz-border)] bg-[var(--netz-surface-elevated)] p-5">
				<h3 class="mb-4 text-sm font-semibold text-[var(--netz-text-primary)]">Stress Scenarios</h3>
				<div class="h-64">
					<BarChart
						data={stressData}
						orientation="horizontal"
					/>
				</div>
			</div>
		{/if}
	{:else}
		<EmptyState title="Portfolio Not Found" message="The requested model portfolio could not be loaded." />
	{/if}
</div>
